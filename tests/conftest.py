import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.database import configure_sqlite_connection
from app.core.database import get_db
from app.models import InventoryTransaction, Organization, TransactionType
from app.main import app
from app.core.config import settings


TEST_DB_URL = "sqlite://"

engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


event.listen(engine, "connect", configure_sqlite_connection)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def seed_inventory_ledger():
    """Seed trusted historical stock without exercising public custody APIs.

    This is intentionally limited to legacy feature tests that need opening van
    stock. Public API security tests must use the replenishment custody flow.
    """

    def seed(
        *,
        part_id: int,
        transaction_type: str = "inbound",
        quantity: int,
        from_warehouse_id: int | None = None,
        to_warehouse_id: int | None = None,
        from_location_id: int | None = None,
        to_location_id: int | None = None,
        work_order_id: int | None = None,
        user_id: int | None = None,
        unit_cost: float = 0.0,
        notes: str = "Trusted legacy test fixture",
        organization_id: int = 1,
    ) -> int:
        with TestingSessionLocal() as db:
            row = InventoryTransaction(
                organization_id=organization_id,
                part_id=part_id,
                transaction_type=TransactionType(transaction_type),
                quantity=quantity,
                from_warehouse_id=from_warehouse_id,
                to_warehouse_id=to_warehouse_id,
                from_location_id=from_location_id,
                to_location_id=to_location_id,
                work_order_id=work_order_id,
                user_id=user_id,
                unit_cost=unit_cost,
                notes=notes,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return row.id

    return seed


@pytest.fixture()
def client():
    original_rbac_enforce = settings.rbac_enforce
    original_legacy_header_auth = settings.legacy_header_auth
    settings.rbac_enforce = False
    settings.legacy_header_auth = True
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestingSessionLocal() as db:
        db.add(Organization(id=1, name="Test Organization", slug="test"))
        db.commit()
    app.dependency_overrides[get_db] = override_get_db
    app.state.testing_session_local = TestingSessionLocal

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    del app.state.testing_session_local
    Base.metadata.drop_all(bind=engine)
    settings.rbac_enforce = original_rbac_enforce
    settings.legacy_header_auth = original_legacy_header_auth
