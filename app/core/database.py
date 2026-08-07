from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings


connect_args = (
    {"check_same_thread": False, "timeout": 5}
    if settings.database_url.startswith("sqlite")
    else {}
)

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    pool_pre_ping=True,
)


def configure_sqlite_connection(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


if engine.dialect.name == "sqlite":
    event.listen(engine, "connect", configure_sqlite_connection)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


class DatabaseSchemaError(RuntimeError):
    """The configured database is not safe to serve with this application."""


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_schema_ready(bind: Engine = engine) -> None:
    """Fail closed unless the database is at the sole Alembic head.

    Runtime startup is deliberately read-only with respect to schema. Creation,
    upgrades, and legacy adoption are explicit maintenance operations so a
    partially migrated database can never be served accidentally.
    """

    from app.services.legacy_database_adoption import current_schema_head

    expected_head = current_schema_head()
    table_names = set(inspect(bind).get_table_names())
    business_tables = table_names - {"alembic_version"}
    if "alembic_version" not in table_names:
        if business_tables and bind.dialect.name == "sqlite":
            raise DatabaseSchemaError(
                "The configured SQLite database has business tables but no "
                "Alembic revision. Run "
                "'python -m scripts.adopt_legacy_database --database "
                "openpartsflow.db' first; do not stamp it as head."
            )
        raise DatabaseSchemaError(
            "The configured database is not initialized. Run "
            "'alembic upgrade head' before starting the application."
        )

    with bind.connect() as connection:
        revisions = tuple(
            connection.execute(
                text("SELECT version_num FROM alembic_version ORDER BY version_num")
            ).scalars()
        )
    if revisions != (expected_head,):
        found = ", ".join(revisions) if revisions else "empty revision table"
        if not revisions and business_tables and bind.dialect.name == "sqlite":
            action = (
                "Run 'python -m scripts.adopt_legacy_database --database "
                "openpartsflow.db'; do not stamp the database."
            )
        else:
            action = "Run 'alembic upgrade head'."
        raise DatabaseSchemaError(
            f"Database schema is not current (found {found}; expected "
            f"{expected_head}). {action}"
        )
