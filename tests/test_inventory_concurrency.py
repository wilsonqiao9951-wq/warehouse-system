from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, configure_sqlite_connection
from app.models import (
    InventoryTransaction,
    Organization,
    Part,
    ReplenishmentRequest,
    TransactionType,
    User,
    UserRole,
    Warehouse,
)
from app.services.inventory import begin_inventory_write, get_available_stock_quantity, get_stock_quantity


def _file_sqlite_sessions(tmp_path):
    database_path = (tmp_path / "inventory-concurrency.db").as_posix()
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )
    event.listen(engine, "connect", configure_sqlite_connection)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _seed_competing_requests(Session):
    with Session() as db:
        organization = Organization(id=1, name="Concurrency Organization", slug="concurrency-org")
        engineer = User(
            organization_id=1,
            name="Concurrency engineer",
            email="concurrency-engineer@example.com",
            role=UserRole.ENGINEER,
        )
        db.add_all([organization, engineer])
        db.flush()
        source = Warehouse(
            organization_id=1,
            code="CONCURRENCY-SOURCE",
            name="Concurrency source",
            warehouse_type="main",
        )
        destination = Warehouse(
            organization_id=1,
            code="CONCURRENCY-VAN",
            name="Concurrency van",
            warehouse_type="van",
            assigned_user_id=engineer.id,
        )
        part = Part(
            organization_id=1,
            part_number="CONCURRENCY-PART",
            name="Concurrency part",
        )
        db.add_all([source, destination, part])
        db.flush()
        db.add(
            InventoryTransaction(
                organization_id=1,
                part_id=part.id,
                transaction_type=TransactionType.INBOUND,
                quantity=5,
                to_warehouse_id=source.id,
                notes="Concurrency opening stock",
            )
        )
        first = ReplenishmentRequest(
            organization_id=1,
            client_request_id="concurrency-request-one",
            request_reason="First competing reservation",
            part_id=part.id,
            destination_warehouse_id=destination.id,
            source_warehouse_id=source.id,
            target_user_id=engineer.id,
            quantity=4,
            status="requested",
        )
        second = ReplenishmentRequest(
            organization_id=1,
            client_request_id="concurrency-request-two",
            request_reason="Second competing reservation",
            part_id=part.id,
            destination_warehouse_id=destination.id,
            source_warehouse_id=source.id,
            target_user_id=engineer.id,
            quantity=4,
            status="requested",
        )
        db.add_all([first, second])
        db.commit()
        return {
            "part_id": part.id,
            "source_id": source.id,
            "destination_id": destination.id,
            "engineer_id": engineer.id,
            "request_ids": (first.id, second.id),
        }


def test_file_sqlite_serializes_competing_replenishment_reservations(tmp_path):
    engine, Session = _file_sqlite_sessions(tmp_path)
    seeded = _seed_competing_requests(Session)
    barrier = Barrier(2)

    def reserve(request_id: int) -> tuple[str, int]:
        with Session() as db:
            db.info["organization_id"] = 1
            barrier.wait(timeout=5)
            begin_inventory_write(db)
            request = db.get(ReplenishmentRequest, request_id)
            available = get_available_stock_quantity(
                db,
                request.part_id,
                request.source_warehouse_id,
            )
            if available < request.quantity:
                db.rollback()
                return "insufficient", available
            request.status = "picking"
            request.version += 1
            db.commit()
            return "reserved", available

    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
            assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one() >= 5000

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(reserve, seeded["request_ids"]))
        assert sorted(results) == [("insufficient", 1), ("reserved", 5)]

        with Session() as db:
            requests = db.scalars(
                select(ReplenishmentRequest)
                .where(ReplenishmentRequest.id.in_(seeded["request_ids"]))
                .order_by(ReplenishmentRequest.id)
            ).all()
            assert sorted(row.status for row in requests) == ["picking", "requested"]
            assert sorted(row.version for row in requests) == [0, 1]
            assert get_stock_quantity(db, seeded["part_id"], seeded["source_id"]) == 5
            assert get_available_stock_quantity(db, seeded["part_id"], seeded["source_id"]) == 1
    finally:
        engine.dispose()


def test_file_sqlite_unique_client_request_key_closes_double_session_race(tmp_path):
    engine, Session = _file_sqlite_sessions(tmp_path)
    seeded = _seed_competing_requests(Session)
    first_session = Session()
    second_session = Session()
    try:
        first_session.add(
            ReplenishmentRequest(
                organization_id=1,
                client_request_id="same-concurrent-client-key",
                request_reason="Original concurrent request",
                part_id=seeded["part_id"],
                destination_warehouse_id=seeded["destination_id"],
                source_warehouse_id=seeded["source_id"],
                target_user_id=seeded["engineer_id"],
                quantity=1,
                status="requested",
            )
        )
        second_session.add(
            ReplenishmentRequest(
                organization_id=1,
                client_request_id="same-concurrent-client-key",
                request_reason="Conflicting concurrent request",
                part_id=seeded["part_id"],
                destination_warehouse_id=seeded["destination_id"],
                source_warehouse_id=seeded["source_id"],
                target_user_id=seeded["engineer_id"],
                quantity=2,
                status="requested",
            )
        )
        first_session.commit()
        with pytest.raises(IntegrityError):
            second_session.commit()
        second_session.rollback()

        with Session() as verification:
            stored = verification.scalars(
                select(ReplenishmentRequest).where(
                    ReplenishmentRequest.client_request_id == "same-concurrent-client-key"
                )
            ).all()
            assert len(stored) == 1
            assert stored[0].quantity == 1
    finally:
        first_session.close()
        second_session.close()
        engine.dispose()
