from __future__ import annotations

from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import struct
from typing import Any
from uuid import uuid4

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory


class LegacyDatabaseAdoptionError(RuntimeError):
    """Raised when an unversioned SQLite database cannot be adopted safely."""


@dataclass(frozen=True)
class TableAdoptionResult:
    table: str
    row_count: int
    copied_columns: tuple[str, ...]
    derived_columns: tuple[str, ...]
    defaulted_columns: tuple[str, ...]
    common_data_sha256: str


@dataclass(frozen=True)
class LegacyDatabaseAdoptionReport:
    status: str
    source_database: str
    head_revision: str
    source_snapshot_sha256: str
    source_table_count: int
    source_row_count: int
    backup_database: str | None
    report_file: str | None
    started_at: str
    completed_at: str
    tables: tuple[TableAdoptionResult, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class _Column:
    name: str
    not_null: bool
    default: str | None
    primary_key_position: int


@dataclass(frozen=True)
class _CopyPlan:
    table: str
    copied_columns: tuple[str, ...]
    derived_columns: tuple[tuple[str, str], ...]
    defaulted_columns: tuple[str, ...]
    order_columns: tuple[str, ...]
    source_row_count: int


@dataclass(frozen=True)
class _DerivedColumn:
    expression: str
    dependencies: tuple[str, ...]


_DERIVED_COLUMNS: dict[str, dict[str, _DerivedColumn]] = {
    "parts": {
        "min_stock": _DerivedColumn(
            expression='COALESCE("safety_stock", 0)',
            dependencies=("safety_stock",),
        ),
    },
    "work_order_parts": {
        "total_cost": _DerivedColumn(
            expression='COALESCE("quantity" * "unit_cost", 0)',
            dependencies=("quantity", "unit_cost"),
        ),
    },
    "work_orders": {
        "wo_number": _DerivedColumn(
            expression='"ticket_number"',
            dependencies=("ticket_number",),
        ),
        "outlet_name": _DerivedColumn(
            expression='"store_name"',
            dependencies=("store_name",),
        ),
        "description": _DerivedColumn(
            expression='"problem_description"',
            dependencies=("problem_description",),
        ),
    },
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _sqlite_url(path: Path) -> str:
    # ConfigParser treats percent signs as interpolation markers.
    return f"sqlite:///{path.resolve().as_posix()}".replace("%", "%%")


def _alembic_config(project_root: Path, database_path: Path) -> Config:
    config_path = project_root / "alembic.ini"
    script_path = project_root / "alembic"
    if not config_path.is_file() or not script_path.is_dir():
        raise LegacyDatabaseAdoptionError(
            f"Alembic configuration was not found under {project_root}"
        )
    config = Config(str(config_path))
    config.set_main_option("script_location", str(script_path))
    database_url = _sqlite_url(database_path)
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["database_url"] = database_url
    return config


def current_schema_head(project_root: Path | None = None) -> str:
    root = (project_root or Path(__file__).resolve().parents[2]).resolve()
    config = _alembic_config(root, root / "unused-head-lookup.db")
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise LegacyDatabaseAdoptionError(
            f"Expected one Alembic head, found {len(heads)}: {', '.join(heads)}"
        )
    return heads[0]


def _connect_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


def _business_tables(connection: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
        if row[0] != "alembic_version"
    }


def _columns(connection: sqlite3.Connection, table: str) -> tuple[_Column, ...]:
    quoted = _quote_identifier(table)
    return tuple(
        _Column(
            name=row[1],
            not_null=bool(row[3]),
            default=row[4],
            primary_key_position=int(row[5]),
        )
        for row in connection.execute(f"PRAGMA table_info({quoted})")
    )


def _row_count(connection: sqlite3.Connection, table: str) -> int:
    return int(
        connection.execute(
            f"SELECT COUNT(*) FROM {_quote_identifier(table)}"
        ).fetchone()[0]
    )


def _assert_integrity(connection: sqlite3.Connection, label: str) -> None:
    integrity = connection.execute("PRAGMA integrity_check").fetchall()
    if integrity != [("ok",)]:
        details = "; ".join(str(row[0]) for row in integrity[:10])
        raise LegacyDatabaseAdoptionError(
            f"{label} failed SQLite integrity_check: {details}"
        )
    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        preview = "; ".join(str(tuple(row)) for row in violations[:10])
        raise LegacyDatabaseAdoptionError(
            f"{label} has {len(violations)} foreign-key violation(s): {preview}"
        )


def _source_revision(connection: sqlite3.Connection) -> tuple[str, ...]:
    table_names = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    if "alembic_version" not in table_names:
        return ()
    return tuple(
        row[0]
        for row in connection.execute(
            "SELECT version_num FROM alembic_version ORDER BY version_num"
        )
    )


def _build_copy_plan(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    *,
    head_revision: str,
) -> tuple[_CopyPlan, ...]:
    revisions = _source_revision(source)
    if revisions:
        if revisions == (head_revision,):
            raise LegacyDatabaseAdoptionError(
                "Database is already managed at the current Alembic head; "
                "legacy adoption is not required"
            )
        raise LegacyDatabaseAdoptionError(
            "Database already has Alembic revision metadata "
            f"({', '.join(revisions)}); use 'alembic upgrade head' instead"
        )

    source_tables = _business_tables(source)
    target_tables = _business_tables(target)
    if not source_tables:
        raise LegacyDatabaseAdoptionError(
            "Database has no legacy business tables; initialize it with "
            "'alembic upgrade head'"
        )

    unknown_tables = sorted(source_tables - target_tables)
    if unknown_tables:
        raise LegacyDatabaseAdoptionError(
            "Refusing to discard source-only table(s): " + ", ".join(unknown_tables)
        )

    plans: list[_CopyPlan] = []
    for table in sorted(source_tables):
        source_columns = _columns(source, table)
        target_columns = _columns(target, table)
        source_names = {column.name for column in source_columns}
        target_by_name = {column.name: column for column in target_columns}
        unknown_columns = sorted(source_names - target_by_name.keys())
        if unknown_columns:
            raise LegacyDatabaseAdoptionError(
                f"Refusing to discard source-only column(s) in {table}: "
                + ", ".join(unknown_columns)
            )

        row_count = _row_count(source, table)
        derived_columns = {
            name: derived
            for name, derived in _DERIVED_COLUMNS.get(table, {}).items()
            if name not in source_names
            and name in target_by_name
            and set(derived.dependencies) <= source_names
        }
        missing_required = [
            column.name
            for column in target_columns
            if column.name not in source_names
            and column.name not in derived_columns
            and column.not_null
            and column.default is None
            and not column.primary_key_position
        ]
        if row_count and missing_required:
            raise LegacyDatabaseAdoptionError(
                f"Table {table} has {row_count} row(s), but target column(s) "
                "have no safe database default: " + ", ".join(missing_required)
            )

        copied_columns = tuple(
            column.name for column in target_columns if column.name in source_names
        )
        if row_count and not copied_columns:
            raise LegacyDatabaseAdoptionError(
                f"Table {table} has rows but no columns compatible with the target"
            )
        primary_key_columns = tuple(
            column.name
            for column in sorted(
                source_columns,
                key=lambda item: item.primary_key_position or 2**31,
            )
            if column.primary_key_position
        )
        order_columns = primary_key_columns or copied_columns
        plans.append(
            _CopyPlan(
                table=table,
                copied_columns=copied_columns,
                derived_columns=tuple(
                    (column.name, derived_columns[column.name].expression)
                    for column in target_columns
                    if column.name in derived_columns
                ),
                defaulted_columns=tuple(
                    column.name
                    for column in target_columns
                    if column.name not in source_names
                    and column.name not in derived_columns
                ),
                order_columns=order_columns,
                source_row_count=row_count,
            )
        )
    return tuple(plans)


def _encode_value(value: Any) -> bytes:
    if value is None:
        return b"N"
    if isinstance(value, bytes):
        payload = value
        marker = b"B"
    elif isinstance(value, int):
        payload = str(value).encode("ascii")
        marker = b"I"
    elif isinstance(value, float):
        payload = struct.pack(">d", value)
        marker = b"F"
    else:
        payload = str(value).encode("utf-8")
        marker = b"T"
    return marker + len(payload).to_bytes(8, "big") + payload


def _common_data_digest(
    connection: sqlite3.Connection,
    plan: _CopyPlan,
) -> str:
    digest = hashlib.sha256()
    selected = ", ".join(_quote_identifier(name) for name in plan.copied_columns)
    ordered = ", ".join(_quote_identifier(name) for name in plan.order_columns)
    sql = f"SELECT {selected} FROM {_quote_identifier(plan.table)}"
    if ordered:
        sql += f" ORDER BY {ordered}"
    for row in connection.execute(sql):
        digest.update(b"R")
        for value in row:
            digest.update(_encode_value(value))
    return digest.hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _migrate_empty_candidate(
    candidate_path: Path,
    *,
    project_root: Path,
) -> str:
    config = _alembic_config(project_root, candidate_path)
    head_revision = current_schema_head(project_root)
    command.upgrade(config, "head")
    with closing(_connect_read_only(candidate_path)) as connection:
        versions = _source_revision(connection)
    if versions != (head_revision,):
        raise LegacyDatabaseAdoptionError(
            "Candidate migration did not reach the expected head "
            f"{head_revision}: {', '.join(versions) or 'no revision'}"
        )
    return head_revision


def _copy_snapshot_into_candidate(
    snapshot_path: Path,
    candidate_path: Path,
    *,
    head_revision: str,
) -> tuple[tuple[TableAdoptionResult, ...], int]:
    with closing(_connect_read_only(snapshot_path)) as source, closing(
        sqlite3.connect(candidate_path)
    ) as target:
        target.execute("PRAGMA busy_timeout=5000")
        _assert_integrity(source, "Source snapshot")
        plans = _build_copy_plan(
            source,
            target,
            head_revision=head_revision,
        )

        target.execute("PRAGMA foreign_keys=OFF")
        # The snapshot is a private temporary/backup file, so attaching it by
        # path avoids platform-specific SQLite URI handling without exposing
        # the live source to writes.
        target.execute(
            "ATTACH DATABASE ? AS legacy_source",
            (str(snapshot_path.resolve()),),
        )
        target.execute("BEGIN IMMEDIATE")
        try:
            for table in sorted(_business_tables(target)):
                target.execute(f"DELETE FROM {_quote_identifier(table)}")
            for plan in plans:
                if not plan.source_row_count:
                    continue
                insert_columns = plan.copied_columns + tuple(
                    name for name, _expression in plan.derived_columns
                )
                columns = ", ".join(
                    _quote_identifier(name) for name in insert_columns
                )
                selected_values = ", ".join(
                    [
                        *(_quote_identifier(name) for name in plan.copied_columns),
                        *(
                            f"{expression} AS {_quote_identifier(name)}"
                            for name, expression in plan.derived_columns
                        ),
                    ]
                )
                target.execute(
                    f"INSERT INTO main.{_quote_identifier(plan.table)} ({columns}) "
                    f"SELECT {selected_values} "
                    f"FROM legacy_source.{_quote_identifier(plan.table)}"
                )
            target.commit()
        except Exception:
            target.rollback()
            raise
        finally:
            target.execute("DETACH DATABASE legacy_source")
            target.execute("PRAGMA foreign_keys=ON")

        _assert_integrity(target, "Migrated candidate")
        results: list[TableAdoptionResult] = []
        for plan in plans:
            target_count = _row_count(target, plan.table)
            if target_count != plan.source_row_count:
                raise LegacyDatabaseAdoptionError(
                    f"Row-count mismatch for {plan.table}: source "
                    f"{plan.source_row_count}, candidate {target_count}"
                )
            source_digest = _common_data_digest(source, plan)
            target_digest = _common_data_digest(target, plan)
            if source_digest != target_digest:
                raise LegacyDatabaseAdoptionError(
                    f"Common-column checksum mismatch for {plan.table}"
                )
            for column_name, expression in plan.derived_columns:
                mismatch_count = int(
                    target.execute(
                        f"SELECT COUNT(*) FROM {_quote_identifier(plan.table)} "
                        f"WHERE NOT ({_quote_identifier(column_name)} IS ({expression}))"
                    ).fetchone()[0]
                )
                if mismatch_count:
                    raise LegacyDatabaseAdoptionError(
                        f"Derived-column verification failed for "
                        f"{plan.table}.{column_name}: {mismatch_count} mismatch(es)"
                    )
            results.append(
                TableAdoptionResult(
                    table=plan.table,
                    row_count=plan.source_row_count,
                    copied_columns=plan.copied_columns,
                    derived_columns=tuple(
                        name for name, _expression in plan.derived_columns
                    ),
                    defaulted_columns=plan.defaulted_columns,
                    common_data_sha256=source_digest,
                )
            )
        versions = _source_revision(target)
        if versions != (head_revision,):
            raise LegacyDatabaseAdoptionError(
                "Candidate revision changed during data copy"
            )
        return tuple(results), sum(result.row_count for result in results)


def _snapshot_read_only(source_path: Path, snapshot_path: Path) -> None:
    with closing(_connect_read_only(source_path)) as source, closing(
        sqlite3.connect(snapshot_path)
    ) as snapshot:
        source.backup(snapshot)


def _exclusive_backup(
    source_path: Path,
    backup_path: Path,
    *,
    lock_timeout_seconds: float,
) -> sqlite3.Connection:
    source = sqlite3.connect(source_path, timeout=lock_timeout_seconds)
    temporary_backup = backup_path.with_name(f".{backup_path.name}.{uuid4().hex}.tmp")
    try:
        source.execute(f"PRAGMA busy_timeout={int(lock_timeout_seconds * 1000)}")
        journal_mode = str(source.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        if journal_mode != "delete":
            raise LegacyDatabaseAdoptionError(
                "Apply mode requires SQLite journal_mode=DELETE. Stop all services, "
                "checkpoint WAL safely, switch journal mode, and retry. Dry-run mode "
                "remains available without changing the source."
            )
        source.execute("BEGIN EXCLUSIVE")
        _assert_integrity(source, "Live source")
        shutil.copy2(source_path, temporary_backup)
        _fsync_file(temporary_backup)
        os.replace(temporary_backup, backup_path)
        return source
    except sqlite3.OperationalError as exc:
        source.close()
        raise LegacyDatabaseAdoptionError(
            "Could not obtain an exclusive SQLite lock. Stop the backend and every "
            "process using the database, then retry."
        ) from exc
    except Exception:
        source.close()
        raise
    finally:
        temporary_backup.unlink(missing_ok=True)


def _fsync_file(path: Path) -> None:
    # Windows requires a writable file descriptor for fsync.
    with path.open("r+b") as handle:
        os.fsync(handle.fileno())


def _restore_backup(backup_path: Path, source_path: Path) -> None:
    recovery_path = source_path.with_name(
        f".{source_path.name}.recovery-{uuid4().hex}.tmp"
    )
    try:
        shutil.copy2(backup_path, recovery_path)
        _fsync_file(recovery_path)
        os.replace(recovery_path, source_path)
    finally:
        recovery_path.unlink(missing_ok=True)


def _write_report(path: Path, report: LegacyDatabaseAdoptionReport) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(report.as_dict(), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def adopt_legacy_sqlite_database(
    database_path: str | Path,
    *,
    apply: bool = False,
    project_root: str | Path | None = None,
    lock_timeout_seconds: float = 2.0,
) -> LegacyDatabaseAdoptionReport:
    """Validate or atomically adopt an unversioned SQLite database.

    Dry-run mode reads a SQLite snapshot and never changes the source. Apply mode
    requires an exclusive DELETE-journal lock, keeps an immutable pre-adoption
    backup, migrates a separate candidate, verifies every shared value, and only
    then replaces the live database file.
    """

    started_at = _utc_now()
    requested_path = Path(database_path).expanduser()
    if requested_path.is_symlink():
        raise LegacyDatabaseAdoptionError(
            "Refusing to replace a symbolic-link database path"
        )
    source_path = requested_path.resolve()
    root = Path(project_root).resolve() if project_root else Path(__file__).resolve().parents[2]
    if not source_path.is_file():
        raise LegacyDatabaseAdoptionError(
            f"SQLite database does not exist: {source_path}"
        )
    if lock_timeout_seconds <= 0:
        raise LegacyDatabaseAdoptionError("lock_timeout_seconds must be positive")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    candidate_path = source_path.with_name(
        f".{source_path.name}.adoption-candidate-{run_id}.tmp"
    )
    snapshot_path = source_path.with_name(
        f".{source_path.name}.adoption-snapshot-{run_id}.tmp"
    )
    backup_path = source_path.with_name(
        f"{source_path.stem}.pre-alembic-{run_id}{source_path.suffix or '.db'}"
    )
    report_path = source_path.with_name(
        f"{source_path.stem}.adoption-{run_id}.json"
    )
    exclusive_source: sqlite3.Connection | None = None
    persistent_backup: Path | None = None
    try:
        head_revision = _migrate_empty_candidate(candidate_path, project_root=root)
        if apply:
            exclusive_source = _exclusive_backup(
                source_path,
                backup_path,
                lock_timeout_seconds=lock_timeout_seconds,
            )
            persistent_backup = backup_path
            snapshot_path = backup_path
        else:
            _snapshot_read_only(source_path, snapshot_path)

        snapshot_sha256 = _sha256_file(snapshot_path)
        table_results, total_rows = _copy_snapshot_into_candidate(
            snapshot_path,
            candidate_path,
            head_revision=head_revision,
        )

        if not apply:
            return LegacyDatabaseAdoptionReport(
                status="validated",
                source_database=str(source_path),
                head_revision=head_revision,
                source_snapshot_sha256=snapshot_sha256,
                source_table_count=len(table_results),
                source_row_count=total_rows,
                backup_database=None,
                report_file=None,
                started_at=started_at,
                completed_at=_utc_now(),
                tables=table_results,
            )

        _fsync_file(candidate_path)
        assert exclusive_source is not None
        exclusive_source.rollback()
        exclusive_source.close()
        exclusive_source = None
        journal_path = source_path.with_name(source_path.name + "-journal")
        if journal_path.exists():
            raise LegacyDatabaseAdoptionError(
                f"SQLite journal remained after exclusive lock: {journal_path}"
            )

        os.replace(candidate_path, source_path)
        try:
            with closing(_connect_read_only(source_path)) as adopted:
                _assert_integrity(adopted, "Adopted database")
                if _source_revision(adopted) != (head_revision,):
                    raise LegacyDatabaseAdoptionError(
                        "Adopted database does not contain the expected revision"
                    )
        except Exception:
            _restore_backup(backup_path, source_path)
            raise

        report = LegacyDatabaseAdoptionReport(
            status="applied",
            source_database=str(source_path),
            head_revision=head_revision,
            source_snapshot_sha256=snapshot_sha256,
            source_table_count=len(table_results),
            source_row_count=total_rows,
            backup_database=str(backup_path),
            report_file=str(report_path),
            started_at=started_at,
            completed_at=_utc_now(),
            tables=table_results,
        )
        _write_report(report_path, report)
        return report
    except sqlite3.DatabaseError as exc:
        raise LegacyDatabaseAdoptionError(
            f"SQLite rejected the adoption candidate: {exc}"
        ) from exc
    finally:
        if exclusive_source is not None:
            exclusive_source.rollback()
            exclusive_source.close()
        candidate_path.unlink(missing_ok=True)
        if snapshot_path != persistent_backup:
            snapshot_path.unlink(missing_ok=True)
