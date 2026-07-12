from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

connect_args = {"check_same_thread": False, "timeout": 5} if settings.database_url.startswith("sqlite") else {}

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


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_schema_compatibility() -> None:
    """
    Keep existing databases compatible with newly added non-null fields.
    This avoids runtime failures when older SQLite/PostgreSQL files are reused.
    """
    tracked_tables = [
        "users",
        "warehouses",
        "parts",
        "work_orders",
        "inventory_transactions",
        "work_order_parts",
    ]
    inspector = inspect(engine)
    dialect = engine.dialect.name

    with engine.begin() as conn:
        for table_name in tracked_tables:
            existing_columns = {col["name"] for col in inspector.get_columns(table_name)}
            if "updated_at" in existing_columns:
                continue

            if dialect == "sqlite":
                conn.execute(
                    text(
                        f"ALTER TABLE {table_name} "
                        "ADD COLUMN updated_at DATETIME"
                    )
                )
                conn.execute(
                    text(
                        f"UPDATE {table_name} "
                        "SET updated_at = COALESCE(updated_at, created_at)"
                    )
                )
            elif dialect == "postgresql":
                conn.execute(
                    text(
                        f"ALTER TABLE {table_name} "
                        "ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITHOUT TIME ZONE "
                        "NOT NULL DEFAULT NOW()"
                    )
                )

        work_order_columns = {col["name"] for col in inspector.get_columns("work_orders")}
        if "engineer_id" not in work_order_columns:
            if dialect == "sqlite":
                conn.execute(text("ALTER TABLE work_orders ADD COLUMN engineer_id INTEGER"))
            elif dialect == "postgresql":
                conn.execute(text("ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS engineer_id INTEGER"))
        if "assistant_id" not in work_order_columns:
            if dialect == "sqlite":
                conn.execute(text("ALTER TABLE work_orders ADD COLUMN assistant_id INTEGER"))
            elif dialect == "postgresql":
                conn.execute(text("ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS assistant_id INTEGER"))
        if "labor_cost" not in work_order_columns:
            if dialect == "sqlite":
                conn.execute(text("ALTER TABLE work_orders ADD COLUMN labor_cost FLOAT"))
            elif dialect == "postgresql":
                conn.execute(text("ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS labor_cost DOUBLE PRECISION"))
        if "wo_number" not in work_order_columns:
            if dialect == "sqlite":
                conn.execute(text("ALTER TABLE work_orders ADD COLUMN wo_number VARCHAR(120)"))
            elif dialect == "postgresql":
                conn.execute(text("ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS wo_number VARCHAR(120)"))
        if "schedule_date" not in work_order_columns:
            if dialect == "sqlite":
                conn.execute(text("ALTER TABLE work_orders ADD COLUMN schedule_date DATE"))
            elif dialect == "postgresql":
                conn.execute(text("ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS schedule_date DATE"))
        for extra_col, extra_type in [
            ("outlet_name", "VARCHAR(255)"),
            ("job_type", "VARCHAR(120)"),
            ("description", "TEXT"),
            ("city", "VARCHAR(120)"),
            ("state", "VARCHAR(120)"),
            ("zip", "VARCHAR(20)"),
            ("contact_phone", "VARCHAR(50)"),
        ]:
            if extra_col not in work_order_columns:
                if dialect == "sqlite":
                    conn.execute(text(f"ALTER TABLE work_orders ADD COLUMN {extra_col} {extra_type}"))
                elif dialect == "postgresql":
                    conn.execute(text(f"ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS {extra_col} {extra_type}"))

        conn.execute(
            text(
                "UPDATE work_orders "
                "SET engineer_id = COALESCE(engineer_id, assigned_user_id), "
                "labor_cost = COALESCE(labor_cost, 0), "
                "wo_number = COALESCE(wo_number, ticket_number), "
                "outlet_name = COALESCE(outlet_name, store_name), "
                "description = COALESCE(description, problem_description)"
            )
        )

        warehouse_columns = {col["name"] for col in inspector.get_columns("warehouses")}
        if "warehouse_type" not in warehouse_columns:
            if dialect == "sqlite":
                conn.execute(text("ALTER TABLE warehouses ADD COLUMN warehouse_type VARCHAR(20)"))
            elif dialect == "postgresql":
                conn.execute(text("ALTER TABLE warehouses ADD COLUMN IF NOT EXISTS warehouse_type VARCHAR(20)"))
            conn.execute(text("UPDATE warehouses SET warehouse_type = COALESCE(warehouse_type, 'main')"))

        work_order_part_columns = {col["name"] for col in inspector.get_columns("work_order_parts")}
        if "total_cost" not in work_order_part_columns:
            if dialect == "sqlite":
                conn.execute(text("ALTER TABLE work_order_parts ADD COLUMN total_cost FLOAT"))
            elif dialect == "postgresql":
                conn.execute(text("ALTER TABLE work_order_parts ADD COLUMN IF NOT EXISTS total_cost DOUBLE PRECISION"))
            conn.execute(text("UPDATE work_order_parts SET total_cost = COALESCE(total_cost, quantity * unit_cost)"))

        part_columns = {col["name"] for col in inspector.get_columns("parts")}
        if "min_stock" not in part_columns:
            if dialect == "sqlite":
                conn.execute(text("ALTER TABLE parts ADD COLUMN min_stock INTEGER"))
            elif dialect == "postgresql":
                conn.execute(text("ALTER TABLE parts ADD COLUMN IF NOT EXISTS min_stock INTEGER"))
            conn.execute(text("UPDATE parts SET min_stock = COALESCE(min_stock, safety_stock, 0)"))

        if "started_at" not in work_order_columns:
            if dialect == "sqlite":
                conn.execute(text("ALTER TABLE work_orders ADD COLUMN started_at DATETIME"))
            elif dialect == "postgresql":
                conn.execute(text("ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS started_at TIMESTAMP WITHOUT TIME ZONE"))
        if "completed_at" not in work_order_columns:
            if dialect == "sqlite":
                conn.execute(text("ALTER TABLE work_orders ADD COLUMN completed_at DATETIME"))
            elif dialect == "postgresql":
                conn.execute(text("ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP WITHOUT TIME ZONE"))
        if "is_locked" not in work_order_columns:
            if dialect == "sqlite":
                conn.execute(text("ALTER TABLE work_orders ADD COLUMN is_locked BOOLEAN"))
            elif dialect == "postgresql":
                conn.execute(text("ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS is_locked BOOLEAN"))
            conn.execute(text("UPDATE work_orders SET is_locked = COALESCE(is_locked, 0)"))

        if "qc_pictures" not in inspector.get_table_names():
            if dialect == "sqlite":
                conn.execute(
                    text(
                        "CREATE TABLE qc_pictures ("
                        "id INTEGER PRIMARY KEY, "
                        "work_order_id INTEGER NOT NULL, "
                        "image_url VARCHAR(500) NOT NULL, "
                        "uploaded_by INTEGER NULL, "
                        "created_at DATETIME, "
                        "updated_at DATETIME)"
                    )
                )
            elif dialect == "postgresql":
                conn.execute(
                    text(
                        "CREATE TABLE IF NOT EXISTS qc_pictures ("
                        "id SERIAL PRIMARY KEY, "
                        "work_order_id INTEGER NOT NULL REFERENCES work_orders(id), "
                        "image_url VARCHAR(500) NOT NULL, "
                        "uploaded_by INTEGER NULL REFERENCES users(id), "
                        "created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(), "
                        "updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW())"
                    )
                )

        if "job_status" not in inspector.get_table_names():
            if dialect == "sqlite":
                conn.execute(
                    text(
                        "CREATE TABLE job_status ("
                        "id INTEGER PRIMARY KEY, "
                        "work_order_id INTEGER NOT NULL, "
                        "status VARCHAR(50) NOT NULL, "
                        "timestamp DATETIME, "
                        "created_at DATETIME, "
                        "updated_at DATETIME)"
                    )
                )
            elif dialect == "postgresql":
                conn.execute(
                    text(
                        "CREATE TABLE IF NOT EXISTS job_status ("
                        "id SERIAL PRIMARY KEY, "
                        "work_order_id INTEGER NOT NULL REFERENCES work_orders(id), "
                        "status VARCHAR(50) NOT NULL, "
                        "\"timestamp\" TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(), "
                        "created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(), "
                        "updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW())"
                    )
                )

        if "return_equipments" not in inspector.get_table_names():
            if dialect == "sqlite":
                conn.execute(
                    text(
                        "CREATE TABLE return_equipments ("
                        "id INTEGER PRIMARY KEY, "
                        "work_order_id INTEGER NOT NULL, "
                        "equipment_type VARCHAR(255) NOT NULL, "
                        "quantity INTEGER NOT NULL DEFAULT 1, "
                        "created_at DATETIME, "
                        "updated_at DATETIME)"
                    )
                )

        if "audit_logs" not in inspector.get_table_names():
            if dialect == "sqlite":
                conn.execute(
                    text(
                        "CREATE TABLE audit_logs ("
                        "id INTEGER PRIMARY KEY, "
                        "user_id INTEGER NULL, "
                        "action VARCHAR(120) NOT NULL, "
                        "entity_type VARCHAR(120) NOT NULL, "
                        "entity_id INTEGER NULL, "
                        "timestamp DATETIME, "
                        "metadata_json TEXT NULL, "
                        "created_at DATETIME, "
                        "updated_at DATETIME)"
                    )
                )
            elif dialect == "postgresql":
                conn.execute(
                    text(
                        "CREATE TABLE IF NOT EXISTS audit_logs ("
                        "id SERIAL PRIMARY KEY, "
                        "user_id INTEGER NULL REFERENCES users(id), "
                        "action VARCHAR(120) NOT NULL, "
                        "entity_type VARCHAR(120) NOT NULL, "
                        "entity_id INTEGER NULL, "
                        "\"timestamp\" TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(), "
                        "metadata_json TEXT NULL, "
                        "created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(), "
                        "updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW())"
                    )
                )
            elif dialect == "postgresql":
                conn.execute(
                    text(
                        "CREATE TABLE IF NOT EXISTS return_equipments ("
                        "id SERIAL PRIMARY KEY, "
                        "work_order_id INTEGER NOT NULL REFERENCES work_orders(id), "
                        "equipment_type VARCHAR(255) NOT NULL, "
                        "quantity INTEGER NOT NULL DEFAULT 1, "
                        "created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(), "
                        "updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW())"
                    )
                )

        # Clean up legacy placeholder warehouse rows created by old test/seed flows.
        conn.execute(
            text(
                "UPDATE warehouses "
                "SET name = 'Legacy Warehouse' "
                "WHERE name = 'string'"
            )
        )
        conn.execute(
            text(
                "UPDATE warehouses "
                "SET assigned_user_id = NULL "
                "WHERE assigned_user_id = 0"
            )
        )
