from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import uuid4


RECOVERY_FORMAT = "opf-platform-recovery-v1"
REPORT_FORMAT = "opf-platform-recovery-rehearsal-v1"
MANIFEST_NAME = "manifest.json"
MANIFEST_HASH_NAME = "manifest.sha256"
DATABASE_ARCHIVE_NAME = "database.dump"
VOLUME_NAMES = ("public", "private", "rollback")
MAX_MANIFEST_BYTES = 32 * 1024 * 1024


class RecoveryError(RuntimeError):
    """A safe, operator-facing recovery failure."""


@dataclass(frozen=True)
class DatabaseTarget:
    host: str
    port: int
    database: str
    user: str
    password: str
    options: dict[str, str]

    def subprocess_environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        for key in tuple(environment):
            if key.startswith("PG"):
                environment.pop(key, None)
        environment.update(
            {
                "PGHOST": self.host,
                "PGPORT": str(self.port),
                "PGDATABASE": self.database,
                "PGUSER": self.user,
                "PGPASSWORD": self.password,
                # Forced tenant RLS remains active for the migration owner.
                # The recovery tool uses the same platform-wide scope as other
                # explicit owner-only maintenance commands.
                "PGOPTIONS": "-c openpartsflow.platform_access=on",
            }
        )
        environment.update(self.options)
        return environment


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise RecoveryError("Recovery evidence timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    payload = json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _database_target_from_environment(variable: str) -> DatabaseTarget:
    raw = os.environ.get(variable, "").strip()
    if not raw:
        raise RecoveryError(f"{variable} must contain a PostgreSQL URL")
    normalized = raw.replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"postgresql", "postgres"}:
        raise RecoveryError(f"{variable} must use PostgreSQL")
    if not parsed.hostname or not parsed.username or not parsed.path.strip("/"):
        raise RecoveryError(f"{variable} must include host, user, and database")
    query = parse_qs(parsed.query, keep_blank_values=False)
    supported = {
        "sslmode": "PGSSLMODE",
        "sslrootcert": "PGSSLROOTCERT",
        "sslcert": "PGSSLCERT",
        "sslkey": "PGSSLKEY",
    }
    unknown = set(query) - set(supported)
    if unknown:
        raise RecoveryError(
            f"{variable} contains unsupported PostgreSQL option(s): "
            + ", ".join(sorted(unknown))
        )
    options: dict[str, str] = {}
    for name, environment_name in supported.items():
        values = query.get(name, [])
        if len(values) > 1:
            raise RecoveryError(f"{variable} repeats PostgreSQL option {name}")
        if values:
            options[environment_name] = values[0]
    try:
        port = parsed.port or 5432
    except ValueError as exc:
        raise RecoveryError(f"{variable} contains an invalid port") from exc
    return DatabaseTarget(
        host=parsed.hostname,
        port=port,
        database=unquote(parsed.path.lstrip("/")),
        user=unquote(parsed.username),
        password=unquote(parsed.password or ""),
        options=options,
    )


def _run_postgres(
    command: list[str],
    target: DatabaseTarget,
    *,
    capture_output: bool = False,
) -> str:
    try:
        completed = subprocess.run(
            command,
            check=False,
            env=target.subprocess_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if capture_output else subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RecoveryError(f"Required PostgreSQL utility is unavailable: {command[0]}") from exc
    if completed.returncode:
        raise RecoveryError(
            f"{command[0]} failed with exit code {completed.returncode}; "
            "inspect the protected operator console for infrastructure details"
        )
    return (completed.stdout or "").strip()


def _query(target: DatabaseTarget, sql: str) -> str:
    return _run_postgres(
        [
            "psql",
            "--no-psqlrc",
            "--set=ON_ERROR_STOP=1",
            "--tuples-only",
            "--no-align",
            "--command",
            sql,
        ],
        target,
        capture_output=True,
    )


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _database_evidence(target: DatabaseTarget) -> tuple[str, dict[str, int]]:
    full_access = _query(
        target,
        "SELECT rolsuper OR rolbypassrls FROM pg_catalog.pg_roles "
        "WHERE rolname = CURRENT_USER",
    )
    if full_access not in {"t", "true", "1"}:
        raise RecoveryError(
            "Complete platform backup requires a PostgreSQL role with BYPASSRLS; "
            "the restricted application role is not sufficient"
        )
    revision_rows = [
        item for item in _query(target, "SELECT version_num FROM alembic_version ORDER BY version_num").splitlines() if item
    ]
    if len(revision_rows) != 1:
        raise RecoveryError("Database must contain exactly one Alembic revision")
    tables = [
        item
        for item in _query(
            target,
            "SELECT tablename FROM pg_catalog.pg_tables "
            "WHERE schemaname = 'public' ORDER BY tablename",
        ).splitlines()
        if item and item != "alembic_version"
    ]
    counts: dict[str, int] = {}
    for table in tables:
        raw = _query(target, f"SELECT COUNT(*) FROM {_quote_identifier(table)}")
        try:
            counts[table] = int(raw)
        except ValueError as exc:
            raise RecoveryError("PostgreSQL returned invalid row-count evidence") from exc
    return revision_rows[0], counts


def _assert_directory(path: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_dir():
        raise RecoveryError(f"{label} must be an existing non-symlink directory")
    return path.resolve()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _volume_entries(root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise RecoveryError("Evidence volumes may not contain symbolic links")
        if path.is_dir():
            continue
        if not path.is_file():
            raise RecoveryError("Evidence volumes may contain regular files only")
        relative = path.relative_to(root).as_posix()
        entries.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    return entries


def _archive_volume(root: Path, destination: Path) -> dict[str, Any]:
    entries = _volume_entries(root)
    with tarfile.open(destination, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
        for entry in entries:
            source = root / Path(entry["path"])
            archive.add(source, arcname=entry["path"], recursive=False)
    expected = {
        str(item["path"]): (int(item["bytes"]), str(item["sha256"]))
        for item in entries
    }
    archived: dict[str, tuple[int, str]] = {}
    with tarfile.open(destination, mode="r:gz") as archive:
        for member in _safe_members(archive):
            if member.name in archived:
                raise RecoveryError("Evidence archive contains duplicate members")
            source = archive.extractfile(member)
            if source is None:
                raise RecoveryError("Evidence archive member cannot be read")
            digest = hashlib.sha256()
            size = 0
            with source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    size += len(chunk)
                    digest.update(chunk)
            archived[member.name] = (size, digest.hexdigest())
    if archived != expected:
        raise RecoveryError("Evidence changed while the recovery archive was created")
    return {
        "archive": destination.name,
        "archive_bytes": destination.stat().st_size,
        "archive_sha256": _sha256_file(destination),
        "file_count": len(entries),
        "content_bytes": sum(int(entry["bytes"]) for entry in entries),
        "files": entries,
    }


def create_recovery_point(
    *,
    database: DatabaseTarget,
    output_root: Path,
    public_root: Path,
    private_root: Path,
    rollback_root: Path,
    source_version: str,
) -> dict[str, Any]:
    started_at = _utc_now()
    output_root = _assert_directory(output_root, "Output root")
    roots = {
        "public": _assert_directory(public_root, "Public evidence root"),
        "private": _assert_directory(private_root, "Private evidence root"),
        "rollback": _assert_directory(rollback_root, "Rollback evidence root"),
    }
    if len(set(roots.values())) != len(roots):
        raise RecoveryError("Evidence roots must be distinct")
    for root in roots.values():
        if _is_relative_to(output_root, root) or _is_relative_to(root, output_root):
            raise RecoveryError("Output and evidence roots must not contain one another")

    timestamp = started_at.strftime("%Y%m%dT%H%M%SZ")
    recovery_point_id = f"{timestamp}-{uuid4().hex[:12]}"
    final_path = output_root / f"opf-recovery-{recovery_point_id}"
    if final_path.exists():
        raise RecoveryError("Recovery point already exists")
    temporary_path = Path(tempfile.mkdtemp(prefix=".opf-recovery-", dir=output_root))
    try:
        revision, table_counts = _database_evidence(database)
        database_archive = temporary_path / DATABASE_ARCHIVE_NAME
        _run_postgres(
            [
                "pg_dump",
                "--format=custom",
                "--compress=6",
                "--no-owner",
                "--no-acl",
                "--file",
                str(database_archive),
            ],
            database,
        )
        confirmed_revision, confirmed_counts = _database_evidence(database)
        if confirmed_revision != revision or confirmed_counts != table_counts:
            raise RecoveryError(
                "Database row-count evidence changed during backup; keep user writes closed"
            )
        volume_evidence = {
            name: _archive_volume(root, temporary_path / f"{name}.tar.gz")
            for name, root in roots.items()
        }
        completed_at = _utc_now()
        manifest = {
            "format": RECOVERY_FORMAT,
            "recovery_point_id": recovery_point_id,
            "created_at": _iso(completed_at),
            "source_version": source_version.strip() or "unknown",
            "schema_revision": revision,
            "database": {
                "archive": DATABASE_ARCHIVE_NAME,
                "archive_bytes": database_archive.stat().st_size,
                "archive_sha256": _sha256_file(database_archive),
                "table_count": len(table_counts),
                "row_count": sum(table_counts.values()),
                "table_counts": table_counts,
            },
            "volumes": volume_evidence,
            "duration_seconds": round((completed_at - started_at).total_seconds(), 3),
        }
        manifest_bytes = _canonical_json(manifest)
        _write_json(temporary_path / MANIFEST_NAME, manifest)
        (temporary_path / MANIFEST_HASH_NAME).write_text(
            _sha256_bytes(manifest_bytes) + "\n",
            encoding="ascii",
            newline="\n",
        )
        os.replace(temporary_path, final_path)
        return {
            "status": "created",
            "recovery_point_id": recovery_point_id,
            "recovery_point": str(final_path),
            "schema_revision": revision,
            "manifest_sha256": _sha256_bytes(manifest_bytes),
            "database_rows": sum(table_counts.values()),
            "evidence_files": sum(
                int(item["file_count"]) for item in volume_evidence.values()
            ),
            "duration_seconds": manifest["duration_seconds"],
        }
    except Exception:
        shutil.rmtree(temporary_path, ignore_errors=True)
        raise


def _load_manifest(recovery_point: Path) -> tuple[dict[str, Any], str]:
    if recovery_point.is_symlink() or not recovery_point.is_dir():
        raise RecoveryError("Recovery point must be an existing non-symlink directory")
    manifest_path = recovery_point / MANIFEST_NAME
    hash_path = recovery_point / MANIFEST_HASH_NAME
    if (
        manifest_path.is_symlink()
        or hash_path.is_symlink()
        or not manifest_path.is_file()
        or not hash_path.is_file()
    ):
        raise RecoveryError("Recovery point manifest evidence is incomplete")
    if manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
        raise RecoveryError("Recovery point manifest exceeds the safety limit")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecoveryError("Recovery point manifest is invalid") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != RECOVERY_FORMAT:
        raise RecoveryError("Unsupported recovery point format")
    canonical_hash = _sha256_bytes(_canonical_json(manifest))
    expected_hash = hash_path.read_text(encoding="ascii").strip().lower()
    if expected_hash != canonical_hash:
        raise RecoveryError("Recovery point manifest hash does not match")
    return manifest, canonical_hash


def _safe_members(archive: tarfile.TarFile) -> Iterable[tarfile.TarInfo]:
    for member in archive.getmembers():
        path = PurePosixPath(member.name)
        if (
            not member.isfile()
            or "\\" in member.name
            or "\x00" in member.name
            or path.is_absolute()
            or not path.parts
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise RecoveryError("Evidence archive contains an unsafe member")
        yield member


def _validate_recovery_archives(
    recovery_point: Path, manifest: dict[str, Any]
) -> None:
    def valid_hash(value: Any) -> bool:
        return (
            isinstance(value, str)
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value.lower())
        )

    try:
        database = manifest["database"]
        volumes = manifest["volumes"]
        if (
            not isinstance(manifest["recovery_point_id"], str)
            or not manifest["recovery_point_id"]
            or not isinstance(manifest["schema_revision"], str)
            or not manifest["schema_revision"]
            or not isinstance(database, dict)
            or not isinstance(volumes, dict)
            or set(volumes) != set(VOLUME_NAMES)
        ):
            raise ValueError
        _parse_iso(str(manifest["created_at"]))
        table_counts = database["table_counts"]
        if (
            database["archive"] != DATABASE_ARCHIVE_NAME
            or int(database["archive_bytes"]) < 0
            or not valid_hash(database["archive_sha256"])
            or not isinstance(table_counts, dict)
            or any(
                not isinstance(name, str)
                or not name
                or not isinstance(count, int)
                or count < 0
                for name, count in table_counts.items()
            )
            or int(database["table_count"]) != len(table_counts)
            or int(database["row_count"]) != sum(table_counts.values())
        ):
            raise ValueError

        expected_archives = {
            MANIFEST_NAME,
            MANIFEST_HASH_NAME,
            DATABASE_ARCHIVE_NAME,
        }
        for name in VOLUME_NAMES:
            evidence = volumes[name]
            files = evidence["files"]
            if (
                not isinstance(evidence, dict)
                or evidence["archive"] != f"{name}.tar.gz"
                or int(evidence["archive_bytes"]) < 0
                or not valid_hash(evidence["archive_sha256"])
                or not isinstance(files, list)
            ):
                raise ValueError
            normalized_files: dict[str, tuple[int, str]] = {}
            for item in files:
                path = str(item["path"])
                pure_path = PurePosixPath(path)
                size = int(item["bytes"])
                if (
                    not isinstance(item, dict)
                    or not path
                    or "\\" in path
                    or "\x00" in path
                    or pure_path.is_absolute()
                    or any(part in {"", ".", ".."} for part in pure_path.parts)
                    or size < 0
                    or not valid_hash(item["sha256"])
                    or path in normalized_files
                ):
                    raise ValueError
                normalized_files[path] = (size, str(item["sha256"]))
            if (
                int(evidence["file_count"]) != len(normalized_files)
                or int(evidence["content_bytes"])
                != sum(size for size, _hash in normalized_files.values())
            ):
                raise ValueError
            expected_archives.add(str(evidence["archive"]))
    except (KeyError, TypeError, ValueError, RecoveryError) as exc:
        raise RecoveryError("Recovery point manifest sections are invalid") from exc

    entries = list(recovery_point.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in entries):
        raise RecoveryError("Recovery point contains unsafe filesystem entries")
    actual = {path.name for path in entries}
    if actual != expected_archives:
        raise RecoveryError("Recovery point contains missing or unexpected files")
    for evidence in [database, *(volumes[name] for name in VOLUME_NAMES)]:
        archive = recovery_point / str(evidence["archive"])
        if archive.stat().st_size != int(evidence["archive_bytes"]):
            raise RecoveryError("Recovery archive byte count does not match")
        if _sha256_file(archive) != str(evidence["archive_sha256"]):
            raise RecoveryError("Recovery archive hash does not match")


def _extract_volume(
    recovery_point: Path,
    evidence: dict[str, Any],
    destination: Path,
) -> None:
    expected = {
        str(item["path"]): (int(item["bytes"]), str(item["sha256"]))
        for item in evidence.get("files", [])
    }
    if len(expected) != int(evidence.get("file_count", -1)):
        raise RecoveryError("Recovery volume file evidence is invalid")
    archive_path = recovery_point / str(evidence["archive"])
    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            members = list(_safe_members(archive))
            if (
                len(members) != len(expected)
                or {member.name for member in members} != set(expected)
                or any(member.size != expected[member.name][0] for member in members)
            ):
                raise RecoveryError("Recovery archive members do not match the manifest")
            for member in members:
                target = destination.joinpath(*PurePosixPath(member.name).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise RecoveryError("Recovery archive member cannot be read")
                with source, target.open("xb") as handle:
                    shutil.copyfileobj(source, handle, length=1024 * 1024)
    except tarfile.TarError as exc:
        raise RecoveryError("Recovery evidence archive is invalid") from exc
    actual = _volume_entries(destination)
    actual_map = {
        str(item["path"]): (int(item["bytes"]), str(item["sha256"]))
        for item in actual
    }
    if actual_map != expected:
        raise RecoveryError("Restored evidence does not match the manifest")


def _assert_empty_database(target: DatabaseTarget) -> None:
    raw = _query(
        target,
        "SELECT COUNT(*) FROM pg_catalog.pg_tables WHERE schemaname = 'public'",
    )
    if raw != "0":
        raise RecoveryError("Isolated target database must not contain application tables")


def restore_recovery_point(
    *,
    source_database: DatabaseTarget,
    target_database: DatabaseTarget,
    recovery_point: Path,
    target_public_root: Path,
    target_private_root: Path,
    target_rollback_root: Path,
    report_path: Path,
    confirm_isolated: bool,
) -> dict[str, Any]:
    if not confirm_isolated:
        raise RecoveryError("Restore requires the explicit isolated-rehearsal confirmation")
    if (
        source_database.host.lower(),
        source_database.port,
        source_database.database.lower(),
    ) == (
        target_database.host.lower(),
        target_database.port,
        target_database.database.lower(),
    ):
        raise RecoveryError("Restore target must not be the source database")
    recovery_point = recovery_point.resolve()
    manifest, manifest_hash = _load_manifest(recovery_point)
    _validate_recovery_archives(recovery_point, manifest)
    started_at = _utc_now()
    recovery_created_at = _parse_iso(str(manifest["created_at"]))
    if recovery_created_at > started_at:
        raise RecoveryError("Recovery point timestamp is in the future")
    _assert_empty_database(target_database)

    target_roots = {
        "public": target_public_root.resolve(),
        "private": target_private_root.resolve(),
        "rollback": target_rollback_root.resolve(),
    }
    if len(set(target_roots.values())) != len(target_roots):
        raise RecoveryError("Restore evidence targets must be distinct")
    for target in target_roots.values():
        if target.exists() or _is_relative_to(target, recovery_point):
            raise RecoveryError(
                "Restore evidence targets must be absent and outside the recovery point"
            )
        if not target.parent.is_dir():
            raise RecoveryError("Restore evidence target parent must already exist")

    staging: dict[str, Path] = {}
    try:
        for name, target in target_roots.items():
            stage = Path(tempfile.mkdtemp(prefix=f".opf-{name}-", dir=target.parent))
            staging[name] = stage
            _extract_volume(recovery_point, manifest["volumes"][name], stage)

        _run_postgres(
            [
                "pg_restore",
                "--exit-on-error",
                "--single-transaction",
                "--no-owner",
                "--no-acl",
                "--dbname",
                target_database.database,
                str(recovery_point / DATABASE_ARCHIVE_NAME),
            ],
            target_database,
        )
        revision, counts = _database_evidence(target_database)
        expected_counts = {
            str(name): int(count)
            for name, count in manifest["database"]["table_counts"].items()
        }
        if revision != manifest["schema_revision"] or counts != expected_counts:
            raise RecoveryError("Restored database evidence does not match the recovery point")
        for name, target in target_roots.items():
            os.replace(staging[name], target)
            staging.pop(name)
        completed_at = _utc_now()
        report = {
            "format": REPORT_FORMAT,
            "status": "passed",
            "recovery_point_id": manifest["recovery_point_id"],
            "manifest_sha256": manifest_hash,
            "schema_revision": revision,
            "started_at": _iso(started_at),
            "completed_at": _iso(completed_at),
            "rpo_seconds": round((started_at - recovery_created_at).total_seconds(), 3),
            "rto_seconds": round((completed_at - started_at).total_seconds(), 3),
            "database_table_count": len(counts),
            "database_row_count": sum(counts.values()),
            "evidence_file_count": sum(
                int(manifest["volumes"][name]["file_count"])
                for name in VOLUME_NAMES
            ),
            "evidence_content_bytes": sum(
                int(manifest["volumes"][name]["content_bytes"])
                for name in VOLUME_NAMES
            ),
            "isolation_confirmed": True,
        }
        _write_json(report_path, report)
        return report
    finally:
        for path in staging.values():
            shutil.rmtree(path, ignore_errors=True)


def verify_rehearsal_report(
    report_path: Path,
    *,
    max_rpo_seconds: float,
    max_rto_seconds: float,
) -> dict[str, Any]:
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecoveryError("Recovery rehearsal report is invalid") from exc
    if (
        not isinstance(report, dict)
        or report.get("format") != REPORT_FORMAT
        or report.get("status") != "passed"
        or report.get("isolation_confirmed") is not True
    ):
        raise RecoveryError("Recovery rehearsal report did not pass")
    rpo = float(report.get("rpo_seconds", -1))
    rto = float(report.get("rto_seconds", -1))
    if rpo < 0 or rpo > max_rpo_seconds:
        raise RecoveryError("Recovery rehearsal exceeded the RPO evidence budget")
    if rto < 0 or rto > max_rto_seconds:
        raise RecoveryError("Recovery rehearsal exceeded the RTO evidence budget")
    return {
        "status": "verified",
        "recovery_point_id": report["recovery_point_id"],
        "manifest_sha256": report["manifest_sha256"],
        "rpo_seconds": rpo,
        "rto_seconds": rto,
        "database_row_count": int(report["database_row_count"]),
        "evidence_file_count": int(report["evidence_file_count"]),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create and rehearse complete OpenPartsFlow platform recovery points."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create")
    create.add_argument("--database-url-env", default="DATABASE_URL")
    create.add_argument("--output-root", type=Path, required=True)
    create.add_argument("--public-root", type=Path, required=True)
    create.add_argument("--private-root", type=Path, required=True)
    create.add_argument("--rollback-root", type=Path, required=True)
    create.add_argument("--source-version", default=os.environ.get("VCS_REF", "unknown"))

    restore = subparsers.add_parser("restore-rehearsal")
    restore.add_argument("--source-database-url-env", default="DATABASE_URL")
    restore.add_argument("--target-database-url-env", default="TARGET_DATABASE_URL")
    restore.add_argument("--recovery-point", type=Path, required=True)
    restore.add_argument("--target-public-root", type=Path, required=True)
    restore.add_argument("--target-private-root", type=Path, required=True)
    restore.add_argument("--target-rollback-root", type=Path, required=True)
    restore.add_argument("--report", type=Path, required=True)
    restore.add_argument("--confirm-isolated-rehearsal", action="store_true")

    verify = subparsers.add_parser("verify-report")
    verify.add_argument("--report", type=Path, required=True)
    verify.add_argument("--max-rpo-seconds", type=float, required=True)
    verify.add_argument("--max-rto-seconds", type=float, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "create":
            result = create_recovery_point(
                database=_database_target_from_environment(args.database_url_env),
                output_root=args.output_root,
                public_root=args.public_root,
                private_root=args.private_root,
                rollback_root=args.rollback_root,
                source_version=args.source_version,
            )
        elif args.command == "restore-rehearsal":
            result = restore_recovery_point(
                source_database=_database_target_from_environment(
                    args.source_database_url_env
                ),
                target_database=_database_target_from_environment(
                    args.target_database_url_env
                ),
                recovery_point=args.recovery_point,
                target_public_root=args.target_public_root,
                target_private_root=args.target_private_root,
                target_rollback_root=args.target_rollback_root,
                report_path=args.report,
                confirm_isolated=args.confirm_isolated_rehearsal,
            )
        else:
            if args.max_rpo_seconds < 0 or args.max_rto_seconds <= 0:
                raise RecoveryError("RPO/RTO budgets must be non-negative and positive")
            result = verify_rehearsal_report(
                args.report,
                max_rpo_seconds=args.max_rpo_seconds,
                max_rto_seconds=args.max_rto_seconds,
            )
    except RecoveryError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 1
    except (OSError, tarfile.TarError, KeyError, TypeError, ValueError):
        print(
            json.dumps(
                {"status": "failed", "error": "recovery filesystem evidence is invalid"},
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
