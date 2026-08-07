from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta

from app.core.config import settings
from app.models import (
    InventoryTransaction,
    Organization,
    Part,
    StorageLocation,
    TransactionType,
    User,
    UserRole,
    Warehouse,
    WorkOrder,
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


def _seed_ledger(client) -> dict:
    sessions = client.app.state.testing_session_local
    with sessions() as db:
        warehouse_user = User(
            organization_id=1,
            name="Warehouse Operator",
            email="ledger-warehouse@example.test",
            role=UserRole.WAREHOUSE,
        )
        engineer = User(
            organization_id=1,
            name="Ledger Engineer",
            email="ledger-engineer@example.test",
            role=UserRole.ENGINEER,
        )
        manager = User(
            organization_id=1,
            name="Ledger Manager",
            email="ledger-manager@example.test",
            role=UserRole.MANAGER,
        )
        assistant = User(
            organization_id=1,
            name="Ledger Assistant",
            email="ledger-assistant@example.test",
            role=UserRole.ASSISTANT,
        )
        first_part = Part(
            organization_id=1,
            part_number="LEDGER-001",
            name="Ledger filter",
        )
        second_part = Part(
            organization_id=1,
            part_number="LEDGER-002",
            name="Ledger seal",
        )
        first_warehouse = Warehouse(
            organization_id=1,
            code="MAIN-LEDGER",
            name="Main ledger warehouse",
        )
        second_warehouse = Warehouse(
            organization_id=1,
            code="VAN-LEDGER",
            name="Ledger vehicle",
            warehouse_type="van",
        )
        work_order = WorkOrder(
            organization_id=1,
            ticket_number="WO-LEDGER-001",
            store_name="Ledger customer",
        )
        db.add_all(
            [
                warehouse_user,
                engineer,
                manager,
                assistant,
                first_part,
                second_part,
                first_warehouse,
                second_warehouse,
                work_order,
            ]
        )
        db.flush()
        first_location = StorageLocation(
            organization_id=1,
            warehouse_id=first_warehouse.id,
            code="A-01",
            name="Inbound shelf",
        )
        second_location = StorageLocation(
            organization_id=1,
            warehouse_id=second_warehouse.id,
            code="V-01",
            name="Vehicle bin",
        )
        db.add_all([first_location, second_location])
        db.flush()
        base = datetime(2026, 8, 1, 12, 0, 0)
        inbound = InventoryTransaction(
            organization_id=1,
            part_id=first_part.id,
            transaction_type=TransactionType.INBOUND,
            quantity=20,
            to_warehouse_id=first_warehouse.id,
            to_location_id=first_location.id,
            user_id=warehouse_user.id,
            unit_cost=5.25,
            notes="Opening receipt PO-100",
            created_at=base,
            updated_at=base,
        )
        transfer = InventoryTransaction(
            organization_id=1,
            part_id=second_part.id,
            transaction_type=TransactionType.TRANSFER,
            quantity=4,
            from_warehouse_id=first_warehouse.id,
            to_warehouse_id=second_warehouse.id,
            from_location_id=first_location.id,
            to_location_id=second_location.id,
            user_id=warehouse_user.id,
            unit_cost=3.0,
            notes="Vehicle refill",
            created_at=base + timedelta(hours=1),
            updated_at=base + timedelta(hours=1),
        )
        used = InventoryTransaction(
            organization_id=1,
            part_id=first_part.id,
            transaction_type=TransactionType.WORK_ORDER_USED,
            quantity=2,
            from_warehouse_id=second_warehouse.id,
            from_location_id=second_location.id,
            work_order_id=work_order.id,
            user_id=engineer.id,
            unit_cost=5.25,
            notes="Installed at site",
            created_at=base + timedelta(hours=2),
            updated_at=base + timedelta(hours=2),
        )
        legacy_adjustment = InventoryTransaction(
            organization_id=1,
            part_id=first_part.id,
            transaction_type=TransactionType.ADJUSTMENT,
            quantity=-1,
            to_warehouse_id=first_warehouse.id,
            user_id=warehouse_user.id,
            unit_cost=-9,
            notes="Legacy signed correction",
            created_at=base - timedelta(hours=1),
            updated_at=base - timedelta(hours=1),
        )
        db.add_all([legacy_adjustment, inbound, transfer, used])

        second_org = Organization(
            name="Hidden ledger tenant",
            slug="hidden-ledger-tenant",
        )
        db.add(second_org)
        db.flush()
        hidden_part = Part(
            organization_id=second_org.id,
            part_number="HIDDEN-LEDGER",
            name="Hidden part",
        )
        hidden_warehouse = Warehouse(
            organization_id=second_org.id,
            code="HIDDEN-WH",
            name="Hidden warehouse",
        )
        hidden_user = User(
            organization_id=second_org.id,
            name="Hidden operator",
            email="hidden-ledger@example.test",
            role=UserRole.WAREHOUSE,
        )
        db.add_all([hidden_part, hidden_warehouse, hidden_user])
        db.flush()
        db.add(
            InventoryTransaction(
                organization_id=second_org.id,
                part_id=hidden_part.id,
                transaction_type=TransactionType.INBOUND,
                quantity=999,
                to_warehouse_id=hidden_warehouse.id,
                user_id=hidden_user.id,
                unit_cost=999,
                notes="cross-tenant-secret",
                created_at=base,
                updated_at=base,
            )
        )
        db.commit()
        db.refresh(inbound)
        db.refresh(transfer)
        db.refresh(used)
        db.refresh(legacy_adjustment)
        return {
            "warehouse_user_id": warehouse_user.id,
            "engineer_id": engineer.id,
            "manager_id": manager.id,
            "assistant_id": assistant.id,
            "first_part_id": first_part.id,
            "second_part_id": second_part.id,
            "first_warehouse_id": first_warehouse.id,
            "second_warehouse_id": second_warehouse.id,
            "work_order_id": work_order.id,
            "inbound_id": inbound.id,
            "transfer_id": transfer.id,
            "used_id": used.id,
            "legacy_adjustment_id": legacy_adjustment.id,
        }


def test_inventory_ledger_resolves_business_labels_and_excludes_other_tenants(client):
    seeded = _seed_ledger(client)

    response = client.get("/api/inventory/ledger?limit=10")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload["total"] == 4
    assert payload["next_before_id"] is None
    assert [row["id"] for row in payload["items"]] == [
        seeded["used_id"],
        seeded["transfer_id"],
        seeded["inbound_id"],
        seeded["legacy_adjustment_id"],
    ]
    assert "cross-tenant-secret" not in response.text
    assert "Hidden operator" not in response.text

    used = payload["items"][0]
    assert used["source"] == "work_order"
    assert used["part_number"] == "LEDGER-001"
    assert used["from_warehouse_code"] == "VAN-LEDGER"
    assert used["from_location_code"] == "V-01"
    assert used["work_order_ticket_number"] == "WO-LEDGER-001"
    assert used["user_name"] == "Ledger Engineer"
    assert used["total_cost"] == 10.5

    legacy = payload["items"][3]
    assert legacy["quantity"] == -1
    assert legacy["unit_cost"] == 0
    assert legacy["total_cost"] == 0

    transfer = payload["items"][1]
    assert transfer["source"] == "manual"
    assert transfer["from_warehouse_code"] == "MAIN-LEDGER"
    assert transfer["to_warehouse_code"] == "VAN-LEDGER"
    assert transfer["from_location_code"] == "A-01"
    assert transfer["to_location_code"] == "V-01"

    options = client.get("/api/inventory/ledger/options")
    assert options.status_code == 200, options.text
    option_payload = options.json()
    assert {row["id"] for row in option_payload["parts"]} == {
        seeded["first_part_id"],
        seeded["second_part_id"],
    }
    assert {row["id"] for row in option_payload["warehouses"]} == {
        seeded["first_warehouse_id"],
        seeded["second_warehouse_id"],
    }
    assert {row["label"] for row in option_payload["users"]} == {
        "Warehouse Operator",
        "Ledger Engineer",
    }
    assert "HIDDEN-LEDGER" not in options.text


def test_inventory_ledger_filters_and_cursor_are_server_enforced(client):
    seeded = _seed_ledger(client)

    cases = (
        ("transaction_type=transfer", [seeded["transfer_id"]]),
        (f"part_id={seeded['second_part_id']}", [seeded["transfer_id"]]),
        (
            f"warehouse_id={seeded['first_warehouse_id']}",
            [
                seeded["transfer_id"],
                seeded["inbound_id"],
                seeded["legacy_adjustment_id"],
            ],
        ),
        (f"user_id={seeded['engineer_id']}", [seeded["used_id"]]),
        (f"work_order_id={seeded['work_order_id']}", [seeded["used_id"]]),
        (
            "from_at=2026-08-01T13:30:00Z&to_at=2026-08-01T14:30:00Z",
            [seeded["used_id"]],
        ),
    )
    for query, expected_ids in cases:
        response = client.get(f"/api/inventory/ledger?{query}&limit=10")
        assert response.status_code == 200, response.text
        assert [row["id"] for row in response.json()["items"]] == expected_ids
        assert response.json()["total"] == len(expected_ids)

    first_page = client.get("/api/inventory/ledger?limit=1")
    assert first_page.status_code == 200
    first_payload = first_page.json()
    assert first_payload["total"] == 4
    assert first_payload["next_before_id"] == seeded["used_id"]
    second_page = client.get(
        "/api/inventory/ledger",
        params={"limit": 1, "before_id": first_payload["next_before_id"]},
    )
    assert second_page.status_code == 200
    assert second_page.json()["items"][0]["id"] == seeded["transfer_id"]
    assert second_page.json()["total"] == 4

    assert client.get(
        "/api/inventory/ledger?from_at=2026-08-02T00:00:00Z&to_at=2026-08-01T00:00:00Z"
    ).status_code == 422
    assert client.get(
        "/api/inventory/ledger?from_at=2025-01-01T00:00:00Z&to_at=2026-08-01T00:00:00Z"
    ).status_code == 422
    assert client.get(
        "/api/inventory/ledger?transaction_type=made_up"
    ).status_code == 422


def test_inventory_ledger_allows_warehouse_but_denies_engineers(client):
    seeded = _seed_ledger(client)

    with _enforced_legacy_auth():
        warehouse = client.get(
            "/api/inventory/ledger",
            headers={"X-User-Id": str(seeded["warehouse_user_id"])},
        )
        assert warehouse.status_code == 200, warehouse.text
        manager = client.get(
            "/api/inventory/ledger",
            headers={"X-User-Id": str(seeded["manager_id"])},
        )
        assert manager.status_code == 200, manager.text
        engineer = client.get(
            "/api/inventory/ledger",
            headers={"X-User-Id": str(seeded["engineer_id"])},
        )
        assert engineer.status_code == 403
        engineer_options = client.get(
            "/api/inventory/ledger/options",
            headers={"X-User-Id": str(seeded["engineer_id"])},
        )
        assert engineer_options.status_code == 403
        assistant = client.get(
            "/api/inventory/ledger",
            headers={"X-User-Id": str(seeded["assistant_id"])},
        )
        assert assistant.status_code == 403
