from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.database import ensure_schema_ready
from app.services.legacy_database_adoption import (
    LegacyDatabaseAdoptionError,
    adopt_legacy_sqlite_database,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _config() -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    database_url = settings.database_url.replace("%", "%%")
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["database_url"] = database_url
    return config


def _sqlite_path() -> Path | None:
    url = make_url(settings.database_url)
    if url.get_backend_name() != "sqlite":
        return None
    if not url.database or url.database == ":memory:":
        raise LegacyDatabaseAdoptionError(
            "Persistent startup preparation requires a file-backed SQLite database"
        )
    path = Path(url.database).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _is_unversioned_legacy(path: Path) -> bool:
    if not path.is_file():
        return False
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        business_tables = tables - {"alembic_version"}
        if not business_tables:
            return False
        if "alembic_version" not in tables:
            return True
        return not connection.execute(
            "SELECT 1 FROM alembic_version LIMIT 1"
        ).fetchone()


def main() -> int:
    try:
        sqlite_path = _sqlite_path()
        adoption_report = None
        if sqlite_path is not None and _is_unversioned_legacy(sqlite_path):
            adoption_report = adopt_legacy_sqlite_database(
                sqlite_path,
                apply=True,
                project_root=PROJECT_ROOT,
            )
        command.upgrade(_config(), "head")
        ensure_schema_ready()
    except Exception as exc:
        print(f"Database preparation failed: {exc}", file=sys.stderr)
        return 2

    result = {
        "status": "ready",
        "database_url": settings.database_url,
        "legacy_adoption": (
            {
                "backup_database": adoption_report.backup_database,
                "report_file": adoption_report.report_file,
                "source_row_count": adoption_report.source_row_count,
                "head_revision": adoption_report.head_revision,
            }
            if adoption_report
            else None
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
