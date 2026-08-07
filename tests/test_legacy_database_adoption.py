from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect

from app.core.database import Base, DatabaseSchemaError, ensure_schema_ready
import app.models  # noqa: F401
from app.services.legacy_database_adoption import (
    LegacyDatabaseAdoptionError,
    adopt_legacy_sqlite_database,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _config(database_path: Path) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    database_url = f"sqlite:///{database_path.resolve().as_posix()}".replace(
        "%", "%%"
    )
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["database_url"] = database_url
    return config


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build_mosaic_legacy_database(path: Path) -> None:
    command.upgrade(_config(path), "20260711_0016")
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    try:
        # This reproduces the former runtime behavior: create later missing
        # tables from current models but never alter the existing old tables.
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()

    now = "2026-08-07 10:00:00"
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE alembic_version")
        connection.execute(
            "INSERT INTO users "
            "(id, name, email, role, organization_id) "
            "VALUES (10, 'Engineer One', 'engineer@example.com', 'ENGINEER', 1)"
        )
        connection.execute(
            "INSERT INTO warehouses "
            "(id, name, location, organization_id, code) "
            "VALUES (20, 'Main Warehouse', 'A', 1, 'MAIN')"
        )
        connection.execute(
            "INSERT INTO parts "
            "(id, part_number, name, safety_stock, organization_id) "
            "VALUES (30, 'P-30', 'Filter', 7, 1)"
        )
        connection.execute(
            "INSERT INTO work_orders "
            "(id, ticket_number, store_name, problem_description, assigned_user_id, "
            "engineer_id, status, organization_id) "
            "VALUES (40, 'WO-40', 'Shop', 'Blocked filter', 10, 10, 'open', 1)"
        )
        connection.execute(
            "INSERT INTO work_order_parts "
            "(id, work_order_id, part_id, warehouse_id, user_id, quantity, "
            "unit_cost, organization_id) "
            "VALUES (50, 40, 30, 20, 10, 2, 4.5, 1)"
        )
        connection.execute(
            "INSERT INTO qc_pictures VALUES "
            "(60, 1, 40, '/uploads/qc.jpg', 10, ?, ?)",
            (now, now),
        )
        connection.execute(
            "INSERT INTO job_status VALUES (61, 1, 40, 'open', ?, ?, ?)",
            (now, now, now),
        )
        connection.execute(
            "INSERT INTO return_equipments VALUES "
            "(62, 1, 40, 'old filter', 1, ?, ?)",
            (now, now),
        )
        connection.execute(
            "INSERT INTO audit_logs VALUES "
            "(70, 1, 10, 'view', 'work_order', 40, ?, '{}', ?, ?)",
            (now, now, now),
        )


def _table_result(report, table: str):
    return next(result for result in report.tables if result.table == table)


def test_legacy_adoption_dry_run_is_read_only_and_validates_derivations(tmp_path):
    database = tmp_path / "legacy.db"
    _build_mosaic_legacy_database(database)
    before_sha256 = _sha256(database)

    report = adopt_legacy_sqlite_database(database, project_root=PROJECT_ROOT)

    assert report.status == "validated"
    assert report.head_revision == "20260807_0046"
    assert report.source_row_count >= 10
    assert report.backup_database is None
    assert report.report_file is None
    assert _sha256(database) == before_sha256
    assert _table_result(report, "parts").derived_columns == ("min_stock",)
    assert _table_result(report, "work_order_parts").derived_columns == (
        "total_cost",
    )
    assert _table_result(report, "work_orders").derived_columns == (
        "wo_number",
        "outlet_name",
        "description",
    )
    assert not list(tmp_path.glob(".*adoption-*.tmp"))
    assert not list(tmp_path.glob("*.pre-alembic-*.db"))


def test_legacy_adoption_apply_preserves_data_backup_and_audit_report(tmp_path):
    database = tmp_path / "legacy.db"
    _build_mosaic_legacy_database(database)

    report = adopt_legacy_sqlite_database(
        database,
        apply=True,
        project_root=PROJECT_ROOT,
    )

    assert report.status == "applied"
    backup = Path(report.backup_database or "")
    report_file = Path(report.report_file or "")
    assert backup.is_file()
    assert report_file.is_file()
    assert json.loads(report_file.read_text(encoding="utf-8"))["status"] == "applied"
    assert _sha256(backup) == report.source_snapshot_sha256

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchall() == [
            ("20260807_0046",)
        ]
        assert connection.execute(
            "SELECT code, name, timezone, is_default FROM inventory_regions"
        ).fetchall() == [("PRIMARY", "Primary region", "UTC", 1)]
        assert connection.execute(
            "SELECT COUNT(*) FROM warehouses WHERE region_id IS NULL"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT ticket_number, wo_number, outlet_name, description, "
            "claim_version, form_version, form_data_json FROM work_orders"
        ).fetchall() == [
            ("WO-40", "WO-40", "Shop", "Blocked filter", 0, 0, "{}")
        ]
        assert connection.execute(
            "SELECT safety_stock, min_stock FROM parts"
        ).fetchall() == [(7, 7)]
        assert connection.execute(
            "SELECT quantity, unit_cost, total_cost FROM work_order_parts"
        ).fetchall() == [(2, 4.5, 9.0)]
        assert connection.execute(
            "SELECT image_url FROM qc_pictures"
        ).fetchall() == [("/uploads/qc.jpg",)]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]

    with sqlite3.connect(backup) as connection:
        assert "alembic_version" not in {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert connection.execute(
            "SELECT ticket_number, store_name FROM work_orders"
        ).fetchall() == [("WO-40", "Shop")]

    adopted_engine = create_engine(f"sqlite:///{database.as_posix()}")
    try:
        ensure_schema_ready(adopted_engine)
        migrated_tables = set(inspect(adopted_engine).get_table_names()) - {
            "alembic_version"
        }
        assert migrated_tables == set(Base.metadata.tables)
        for table_name in migrated_tables:
            migrated_columns = {
                column["name"] for column in inspect(adopted_engine).get_columns(table_name)
            }
            assert migrated_columns == {
                column.name for column in Base.metadata.tables[table_name].columns
            }
    finally:
        adopted_engine.dispose()

    with pytest.raises(
        LegacyDatabaseAdoptionError,
        match="already managed at the current Alembic head",
    ):
        adopt_legacy_sqlite_database(database, project_root=PROJECT_ROOT)


def test_legacy_adoption_refuses_unknown_data_and_live_database(tmp_path):
    database = tmp_path / "legacy.db"
    _build_mosaic_legacy_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE customer_extension (id INTEGER PRIMARY KEY, value TEXT)"
        )
        connection.execute(
            "INSERT INTO customer_extension (id, value) VALUES (1, 'keep me')"
        )

    before_sha256 = _sha256(database)
    with pytest.raises(
        LegacyDatabaseAdoptionError,
        match="source-only table.*customer_extension",
    ):
        adopt_legacy_sqlite_database(database, project_root=PROJECT_ROOT)
    assert _sha256(database) == before_sha256
    assert not list(tmp_path.glob(".*adoption-*.tmp"))

    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE customer_extension")

    lock = sqlite3.connect(database)
    lock.execute("BEGIN EXCLUSIVE")
    try:
        with pytest.raises(
            LegacyDatabaseAdoptionError,
            match="exclusive SQLite lock",
        ):
            adopt_legacy_sqlite_database(
                database,
                apply=True,
                project_root=PROJECT_ROOT,
                lock_timeout_seconds=0.05,
            )
    finally:
        lock.rollback()
        lock.close()
    assert not list(tmp_path.glob("*.pre-alembic-*.db"))
    assert not list(tmp_path.glob(".*adoption-*.tmp"))


def test_schema_guard_refuses_unversioned_and_empty_revision_databases(tmp_path):
    database = tmp_path / "legacy.db"
    _build_mosaic_legacy_database(database)
    schema_engine = create_engine(f"sqlite:///{database.as_posix()}")
    try:
        with pytest.raises(DatabaseSchemaError, match="do not stamp"):
            ensure_schema_ready(schema_engine)
        with sqlite3.connect(database) as connection:
            connection.execute(
                "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
            )
        with pytest.raises(DatabaseSchemaError, match="empty revision table"):
            ensure_schema_ready(schema_engine)
    finally:
        schema_engine.dispose()


def test_0040_migration_backfills_compatibility_fields_and_guards_history(tmp_path):
    database = tmp_path / "versioned.db"
    config = _config(database)
    command.upgrade(config, "20260807_0039")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO users "
            "(id, name, email, role, organization_id) "
            "VALUES (10, 'Engineer One', 'engineer@example.com', 'ENGINEER', 1)"
        )
        connection.execute(
            "INSERT INTO warehouses "
            "(id, name, location, organization_id, code, warehouse_type) "
            "VALUES (20, 'Main Warehouse', 'A', 1, 'MAIN', 'main')"
        )
        connection.execute(
            "INSERT INTO parts "
            "(id, part_number, name, safety_stock, organization_id) "
            "VALUES (30, 'P-30', 'Filter', 7, 1)"
        )
        connection.execute(
            "INSERT INTO work_orders "
            "(id, ticket_number, store_name, problem_description, assigned_user_id, "
            "engineer_id, status, organization_id) "
            "VALUES (40, 'WO-40', 'Shop', 'Blocked filter', 10, 10, 'open', 1)"
        )
        connection.execute(
            "INSERT INTO work_order_parts "
            "(id, work_order_id, part_id, warehouse_id, user_id, quantity, "
            "unit_cost, organization_id) "
            "VALUES (50, 40, 30, 20, 10, 2, 4.5, 1)"
        )

    command.upgrade(config, "20260807_0040")
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT min_stock FROM parts WHERE id = 30"
        ).fetchone() == (7,)
        assert connection.execute(
            "SELECT total_cost FROM work_order_parts WHERE id = 50"
        ).fetchone() == (9.0,)
        assert connection.execute(
            "SELECT wo_number, outlet_name, description FROM work_orders WHERE id = 40"
        ).fetchone() == ("WO-40", "Shop", "Blocked filter")
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {"audit_logs", "job_status", "qc_pictures", "return_equipments"} <= tables

    command.downgrade(config, "20260807_0039")
    command.upgrade(config, "20260807_0040")
    with sqlite3.connect(database) as connection:
        now = "2026-08-07 10:00:00"
        connection.execute(
            "INSERT INTO audit_logs "
            "(id, organization_id, user_id, action, entity_type, entity_id, "
            "timestamp, metadata_json, created_at, updated_at) "
            "VALUES (70, 1, 10, 'view', 'work_order', 40, ?, '{}', ?, ?)",
            (now, now, now),
        )
    with pytest.raises(RuntimeError, match="operational history exists"):
        command.downgrade(config, "20260807_0039")
