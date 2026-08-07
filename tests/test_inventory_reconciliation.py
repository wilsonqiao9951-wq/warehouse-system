from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta

from app.core.config import settings
from app.models import (
    InventoryCountLine,
    InventoryCountSession,
    InventoryTransaction,
    Organization,
    Part,
    ReplenishmentRequest,
    TransactionType,
    User,
    UserDevice,
    UserRole,
    VehicleReturnRequest,
    Warehouse,
)


@contextmanager
def _enforced_legacy_auth():
    original_rbac = settings.rbac_enforce
    original_legacy = settings.legacy_header_auth
    settings.rbac_enforce = True
    settings.legacy_header_auth = True
    try:
        yield
    finally:
        settings.rbac_enforce = original_rbac
        settings.legacy_header_auth = original_legacy


def _seed_reconciliation(client) -> dict[str, int]:
    sessions = client.app.state.testing_session_local
    with sessions() as db:
        warehouse_user = User(
            organization_id=1,
            name="Reconciliation Warehouse",
            email="reconciliation-warehouse@example.test",
            role=UserRole.WAREHOUSE,
        )
        manager = User(
            organization_id=1,
            name="Reconciliation Manager",
            email="reconciliation-manager@example.test",
            role=UserRole.MANAGER,
        )
        engineer = User(
            organization_id=1,
            name="Reconciliation Engineer",
            email="reconciliation-engineer@example.test",
            role=UserRole.ENGINEER,
        )
        assistant = User(
            organization_id=1,
            name="Reconciliation Assistant",
            email="reconciliation-assistant@example.test",
            role=UserRole.ASSISTANT,
        )
        part = Part(
            organization_id=1,
            part_number="RECON-001",
            name="Reconciliation seal",
            default_cost=4.5,
        )
        main = Warehouse(
            organization_id=1,
            code="RECON-MAIN",
            name="Reconciliation main",
        )
        van = Warehouse(
            organization_id=1,
            code="RECON-VAN",
            name="Reconciliation van",
            warehouse_type="van",
        )
        db.add_all([warehouse_user, manager, engineer, assistant, part, main, van])
        db.flush()
        van.assigned_user_id = engineer.id
        device = UserDevice(
            organization_id=1,
            user_id=engineer.id,
            device_id="reconciliation-device",
            device_token_hash="a" * 64,
            device_name="Reconciliation phone",
        )
        db.add(device)
        db.flush()
        base = datetime(2026, 8, 7, 18, 0, 0)

        legacy = ReplenishmentRequest(
            organization_id=1,
            part_id=part.id,
            source_warehouse_id=main.id,
            destination_warehouse_id=van.id,
            target_user_id=engineer.id,
            quantity=2,
            status="completed",
            requires_reconciliation=True,
            approval_status="approved",
            updated_at=base,
        )
        bad_replenishment = ReplenishmentRequest(
            organization_id=1,
            part_id=part.id,
            source_warehouse_id=main.id,
            destination_warehouse_id=van.id,
            target_user_id=engineer.id,
            quantity=3,
            status="received",
            approval_status="approved",
            updated_at=base + timedelta(minutes=1),
        )
        healthy_replenishment = ReplenishmentRequest(
            organization_id=1,
            part_id=part.id,
            source_warehouse_id=main.id,
            destination_warehouse_id=van.id,
            target_user_id=engineer.id,
            quantity=4,
            status="completed",
            approval_status="approved",
            updated_at=base + timedelta(minutes=2),
        )
        db.add_all([legacy, bad_replenishment, healthy_replenishment])
        db.flush()

        bad_ship = InventoryTransaction(
            organization_id=1,
            part_id=part.id,
            transaction_type=TransactionType.OUTBOUND,
            quantity=3,
            from_warehouse_id=main.id,
            replenishment_request_id=bad_replenishment.id,
            movement_stage="ship",
            user_id=warehouse_user.id,
        )
        healthy_ship = InventoryTransaction(
            organization_id=1,
            part_id=part.id,
            transaction_type=TransactionType.OUTBOUND,
            quantity=4,
            from_warehouse_id=main.id,
            replenishment_request_id=healthy_replenishment.id,
            movement_stage="ship",
            user_id=warehouse_user.id,
        )
        healthy_receipt = InventoryTransaction(
            organization_id=1,
            part_id=part.id,
            transaction_type=TransactionType.INBOUND,
            quantity=4,
            to_warehouse_id=van.id,
            replenishment_request_id=healthy_replenishment.id,
            movement_stage="receive",
            user_id=engineer.id,
        )
        db.add_all([bad_ship, healthy_ship, healthy_receipt])
        db.flush()
        bad_replenishment.shipment_transaction_id = bad_ship.id
        healthy_replenishment.shipment_transaction_id = healthy_ship.id
        healthy_replenishment.receipt_transaction_id = healthy_receipt.id

        bad_return = VehicleReturnRequest(
            organization_id=1,
            client_request_id="bad-return",
            part_id=part.id,
            source_warehouse_id=van.id,
            destination_warehouse_id=main.id,
            engineer_id=engineer.id,
            quantity=1,
            reason="Return excess stock",
            status="received",
            requested_by=engineer.id,
            requested_device_id=device.id,
            updated_at=base + timedelta(minutes=3),
        )
        db.add(bad_return)
        db.flush()
        return_ship = InventoryTransaction(
            organization_id=1,
            part_id=part.id,
            transaction_type=TransactionType.OUTBOUND,
            quantity=1,
            from_warehouse_id=van.id,
            vehicle_return_request_id=bad_return.id,
            movement_stage="return_ship",
            user_id=engineer.id,
        )
        db.add(return_ship)
        db.flush()
        bad_return.shipment_transaction_id = return_ship.id

        submitted_count = InventoryCountSession(
            organization_id=1,
            client_request_id="submitted-count",
            warehouse_id=main.id,
            title="Submitted variance",
            status="submitted",
            created_by=warehouse_user.id,
            submitted_by=warehouse_user.id,
            submitted_at=base,
            updated_at=base + timedelta(minutes=4),
        )
        bad_approved_count = InventoryCountSession(
            organization_id=1,
            client_request_id="bad-approved-count",
            warehouse_id=main.id,
            title="Missing adjustment",
            status="approved",
            created_by=warehouse_user.id,
            approved_by=manager.id,
            approved_at=base,
            updated_at=base + timedelta(minutes=5),
        )
        healthy_count = InventoryCountSession(
            organization_id=1,
            client_request_id="healthy-count",
            warehouse_id=main.id,
            title="Healthy adjustment",
            status="approved",
            created_by=warehouse_user.id,
            approved_by=manager.id,
            approved_at=base,
            updated_at=base + timedelta(minutes=6),
        )
        db.add_all([submitted_count, bad_approved_count, healthy_count])
        db.flush()
        pending_line = InventoryCountLine(
            organization_id=1,
            session_id=submitted_count.id,
            part_id=part.id,
            counted_quantity=8,
            submitted_book_quantity=10,
            counted_by=warehouse_user.id,
        )
        bad_line = InventoryCountLine(
            organization_id=1,
            session_id=bad_approved_count.id,
            part_id=part.id,
            counted_quantity=4,
            approved_book_quantity=10,
            variance_quantity=-6,
            counted_by=warehouse_user.id,
        )
        healthy_line = InventoryCountLine(
            organization_id=1,
            session_id=healthy_count.id,
            part_id=part.id,
            counted_quantity=8,
            approved_book_quantity=10,
            variance_quantity=-2,
            counted_by=warehouse_user.id,
        )
        db.add_all([pending_line, bad_line, healthy_line])
        db.flush()
        healthy_adjustment = InventoryTransaction(
            organization_id=1,
            part_id=part.id,
            transaction_type=TransactionType.ADJUSTMENT,
            quantity=2,
            from_warehouse_id=main.id,
            inventory_count_line_id=healthy_line.id,
            user_id=manager.id,
        )
        db.add(healthy_adjustment)
        db.flush()
        healthy_line.adjustment_transaction_id = healthy_adjustment.id

        hidden_org = Organization(name="Hidden reconciliation", slug="hidden-reconciliation")
        db.add(hidden_org)
        db.flush()
        hidden_part = Part(
            organization_id=hidden_org.id,
            part_number="HIDDEN-RECON",
            name="Hidden reconciliation part",
        )
        hidden_warehouse = Warehouse(
            organization_id=hidden_org.id,
            code="HIDDEN-RECON",
            name="Hidden reconciliation warehouse",
        )
        db.add_all([hidden_part, hidden_warehouse])
        db.flush()
        hidden_request = ReplenishmentRequest(
            organization_id=hidden_org.id,
            part_id=hidden_part.id,
            destination_warehouse_id=hidden_warehouse.id,
            quantity=999,
            status="completed",
            requires_reconciliation=True,
            request_reason="cross-tenant-secret",
        )
        db.add(hidden_request)
        db.commit()
        return {
            "warehouse_user_id": warehouse_user.id,
            "manager_id": manager.id,
            "engineer_id": engineer.id,
            "assistant_id": assistant.id,
            "legacy_id": legacy.id,
            "bad_replenishment_id": bad_replenishment.id,
            "healthy_replenishment_id": healthy_replenishment.id,
            "bad_return_id": bad_return.id,
            "submitted_count_id": submitted_count.id,
            "bad_approved_count_id": bad_approved_count.id,
            "healthy_count_id": healthy_count.id,
            "hidden_request_id": hidden_request.id,
        }


def test_reconciliation_queue_finds_actionable_exceptions_and_excludes_healthy_rows(client):
    seeded = _seed_reconciliation(client)

    response = client.get("/api/inventory/reconciliation-exceptions")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload["total"] == 5
    assert payload["critical"] == 3
    assert payload["warning"] == 2
    assert payload["replenishment"] == 2
    assert payload["vehicle_return"] == 1
    assert payload["inventory_count"] == 2
    assert payload["truncated"] is False
    assert [row["severity"] for row in payload["items"][:3]] == [
        "critical",
        "critical",
        "critical",
    ]
    identifiers = {row["id"] for row in payload["items"]}
    assert f"replenishment:{seeded['legacy_id']}:legacy" in identifiers
    assert f"replenishment:{seeded['bad_replenishment_id']}:ledger" in identifiers
    assert f"vehicle-return:{seeded['bad_return_id']}:ledger" in identifiers
    assert f"inventory-count:{seeded['submitted_count_id']}" in " ".join(identifiers)
    assert f"inventory-count:{seeded['bad_approved_count_id']}" in " ".join(identifiers)
    assert str(seeded["healthy_replenishment_id"]) not in " ".join(identifiers)
    assert str(seeded["healthy_count_id"]) not in " ".join(identifiers)
    assert "cross-tenant-secret" not in response.text
    assert "HIDDEN-RECON" not in response.text


def test_reconciliation_queue_filters_and_truncates_the_response(client):
    _seed_reconciliation(client)

    counts = client.get(
        "/api/inventory/reconciliation-exceptions?source=inventory_count"
    )
    assert counts.status_code == 200
    assert counts.json()["total"] == 2
    assert {row["source"] for row in counts.json()["items"]} == {"inventory_count"}

    critical = client.get(
        "/api/inventory/reconciliation-exceptions?severity=critical&limit=2"
    )
    assert critical.status_code == 200
    assert critical.json()["total"] == 3
    assert len(critical.json()["items"]) == 2
    assert critical.json()["truncated"] is True
    assert {row["severity"] for row in critical.json()["items"]} == {"critical"}

    assert client.get(
        "/api/inventory/reconciliation-exceptions?source=made_up"
    ).status_code == 422
    assert client.get(
        "/api/inventory/reconciliation-exceptions?severity=made_up"
    ).status_code == 422


def test_reconciliation_queue_allows_operations_roles_and_denies_field_roles(client):
    seeded = _seed_reconciliation(client)

    with _enforced_legacy_auth():
        for user_id in (seeded["warehouse_user_id"], seeded["manager_id"]):
            response = client.get(
                "/api/inventory/reconciliation-exceptions",
                headers={"X-User-Id": str(user_id)},
            )
            assert response.status_code == 200, response.text
        assert client.get(
            f"/api/inventory/replenishment-requests/{seeded['legacy_id']}",
            headers={"X-User-Id": str(seeded["manager_id"])},
        ).status_code == 200
        assert client.get(
            f"/api/inventory/vehicle-returns/{seeded['bad_return_id']}",
            headers={"X-User-Id": str(seeded["manager_id"])},
        ).status_code == 200
        assert client.get(
            f"/api/inventory/counts/{seeded['submitted_count_id']}",
            headers={"X-User-Id": str(seeded["manager_id"])},
        ).status_code == 200
        assert client.get(
            f"/api/inventory/replenishment-requests/{seeded['hidden_request_id']}",
            headers={"X-User-Id": str(seeded["manager_id"])},
        ).status_code == 404
        for user_id in (seeded["engineer_id"], seeded["assistant_id"]):
            response = client.get(
                "/api/inventory/reconciliation-exceptions",
                headers={"X-User-Id": str(user_id)},
            )
            assert response.status_code == 403
