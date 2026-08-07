from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

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

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    info={"rls_platform_access": True},
)


class Base(DeclarativeBase):
    pass


class DatabaseSchemaError(RuntimeError):
    """The configured database is not safe to serve with this application."""


def _apply_postgres_rls_scope(session: Session, connection) -> None:
    if connection.dialect.name != "postgresql":
        return
    organization_id = session.info.get("organization_id")
    platform_access = bool(session.info.get("rls_platform_access", True))
    connection.execute(
        text(
            "SELECT "
            "set_config('openpartsflow.organization_id', :organization_id, true), "
            "set_config('openpartsflow.platform_access', :platform_access, true)"
        ),
        {
            "organization_id": str(organization_id) if organization_id else "",
            "platform_access": "on" if platform_access else "off",
        },
    )


@event.listens_for(Session, "after_begin")
def _initialize_postgres_rls_scope(session, _transaction, connection) -> None:
    _apply_postgres_rls_scope(session, connection)


def set_tenant_database_scope(db: Session, organization_id: int) -> None:
    if organization_id < 1:
        raise ValueError("organization_id must be positive")
    db.info["organization_id"] = organization_id
    db.info["rls_platform_access"] = False
    if db.in_transaction():
        _apply_postgres_rls_scope(db, db.connection())


def set_platform_database_scope(db: Session) -> None:
    db.info.pop("organization_id", None)
    db.info["rls_platform_access"] = True
    if db.in_transaction():
        _apply_postgres_rls_scope(db, db.connection())


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


def ensure_data_residency_ready(bind: Engine = engine) -> None:
    """Refuse a deployable runtime whose database belongs to another region."""

    if settings.app_env.strip().lower() not in {"production", "staging"}:
        return
    from app.core.data_residency import normalize_region_code

    deployment_region = normalize_region_code(settings.deployment_region)
    with bind.connect() as connection:
        mismatch = connection.scalar(
            text(
                "SELECT id FROM organizations "
                "WHERE data_residency_region IS NOT NULL "
                "AND data_residency_region <> :deployment_region LIMIT 1"
            ),
            {"deployment_region": deployment_region},
        )
    if mismatch is not None:
        raise DatabaseSchemaError(
            "Database data-residency assignments do not match "
            f"DEPLOYMENT_REGION={deployment_region}. Keep this deployment "
            "offline until the region setting or controlled data migration is corrected."
        )
