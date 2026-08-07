from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta

from app.core.config import settings
from app.models import (
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


def _seed_planning(client) -> dict[str, int]:
    sessions = client.app.state.testing_session_local
    with sessions() as db:
        manager = User(
            organization_id=1,
            name="Planning Manager",
            email="planning-manager@example.test",
            role=UserRole.MANAGER,
        )
        warehouse_user = User(
            organization_id=1,
            name="Planning Warehouse",
            email="planning-warehouse@example.test",
            role=UserRole.WAREHOUSE,
        )
        engineer = User(
            organization_id=1,
            name="Alice Engineer",
            email="planning-engineer@example.test",
            role=UserRole.ENGINEER,
        )
        assistant = User(
            organization_id=1,
            name="Planning Assistant",
            email="planning-assistant@example.test",
            role=UserRole.ASSISTANT,
        )
        main = Warehouse(
            organization_id=1,
            code="MAIN-PLAN",
            name="Planning main warehouse",
            warehouse_type="main",
            region_id=None,
        )
        db.add_all([manager, warehouse_user, engineer, assistant, main])
        db.flush()
        van = Warehouse(
            organization_id=1,
            code="VAN-ALICE",
            name="Alice service vehicle",
            warehouse_type="van",
            assigned_user_id=engineer.id,
            region_id=None,
        )
        low_part = Part(
            organization_id=1,
            part_number="PLAN-LOW",
            name="Planning low part",
            safety_stock=5,
            min_stock=3,
        )
        excess_part = Part(
            organization_id=1,
            part_number="PLAN-EXCESS",
            name="Planning excess part",
            safety_stock=1,
            min_stock=1,
        )
        balanced_part = Part(
            organization_id=1,
            part_number="PLAN-BALANCED",
            name="Planning balanced part",
            safety_stock=0,
            min_stock=0,
        )
        first_work_order = WorkOrder(
            organization_id=1,
            ticket_number="PLAN-WO-1",
            store_name="Planning customer one",
        )
        second_work_order = WorkOrder(
            organization_id=1,
            ticket_number="PLAN-WO-2",
            store_name="Planning customer two",
        )
        db.add_all(
            [van, low_part, excess_part, balanced_part, first_work_order, second_work_order]
        )
        db.flush()
        device = UserDevice(
            organization_id=1,
            user_id=engineer.id,
            device_id="planning-device",
            device_token_hash="a" * 64,
        )
        db.add(device)
        db.flush()
        now = datetime.utcnow()
        db.add_all(
            [
                InventoryTransaction(
                    organization_id=1,
                    part_id=low_part.id,
                    transaction_type=TransactionType.INBOUND,
                    quantity=100,
                    to_warehouse_id=main.id,
                    created_at=now - timedelta(days=60),
                ),
                InventoryTransaction(
                    organization_id=1,
                    part_id=excess_part.id,
                    transaction_type=TransactionType.INBOUND,
                    quantity=100,
                    to_warehouse_id=main.id,
                    created_at=now - timedelta(days=60),
                ),
                InventoryTransaction(
                    organization_id=1,
                    part_id=low_part.id,
                    transaction_type=TransactionType.TRANSFER,
                    quantity=3,
                    from_warehouse_id=main.id,
                    to_warehouse_id=van.id,
                    created_at=now - timedelta(days=20),
                ),
                InventoryTransaction(
                    organization_id=1,
                    part_id=excess_part.id,
                    transaction_type=TransactionType.TRANSFER,
                    quantity=10,
                    from_warehouse_id=main.id,
                    to_warehouse_id=van.id,
                    created_at=now - timedelta(days=20),
                ),
                InventoryTransaction(
                    organization_id=1,
                    part_id=low_part.id,
                    transaction_type=TransactionType.WORK_ORDER_USED,
                    quantity=2,
                    from_warehouse_id=van.id,
                    work_order_id=first_work_order.id,
                    user_id=engineer.id,
                    created_at=now - timedelta(days=2),
                ),
                InventoryTransaction(
                    organization_id=1,
                    part_id=excess_part.id,
                    transaction_type=TransactionType.WORK_ORDER_USED,
                    quantity=2,
                    from_warehouse_id=van.id,
                    work_order_id=second_work_order.id,
                    user_id=engineer.id,
                    created_at=now - timedelta(days=1),
                ),
            ]
        )
        db.add(
            ReplenishmentRequest(
                organization_id=1,
                part_id=low_part.id,
                destination_warehouse_id=van.id,
                source_warehouse_id=main.id,
                quantity=2,
                target_user_id=engineer.id,
                requested_by=warehouse_user.id,
                request_reason="Existing planned refill",
                status="requested",
            )
        )
        db.add(
            VehicleReturnRequest(
                organization_id=1,
                client_request_id="planning-return-1",
                part_id=excess_part.id,
                source_warehouse_id=van.id,
                destination_warehouse_id=main.id,
                engineer_id=engineer.id,
                quantity=1,
                reason="Existing planned return",
                requested_by=engineer.id,
                requested_device_id=device.id,
                status="requested",
            )
        )

        hidden_org = Organization(name="Hidden planning tenant", slug="hidden-planning")
        db.add(hidden_org)
        db.flush()
        hidden_manager = User(
            organization_id=hidden_org.id,
            name="Hidden Manager",
            email="hidden-planning-manager@example.test",
            role=UserRole.MANAGER,
        )
        hidden_engineer = User(
            organization_id=hidden_org.id,
            name="Hidden Engineer",
            email="hidden-planning-engineer@example.test",
            role=UserRole.ENGINEER,
        )
        hidden_part = Part(
            organization_id=hidden_org.id,
            part_number="HIDDEN-PLAN",
            name="Hidden planning secret",
            safety_stock=99,
        )
        db.add_all([hidden_manager, hidden_engineer, hidden_part])
        db.flush()
        hidden_van = Warehouse(
            organization_id=hidden_org.id,
            code="HIDDEN-VAN",
            name="Hidden service vehicle",
            warehouse_type="van",
            assigned_user_id=hidden_engineer.id,
        )
        db.add(hidden_van)
        db.flush()
        db.add(
            InventoryTransaction(
                organization_id=hidden_org.id,
                part_id=hidden_part.id,
                transaction_type=TransactionType.INBOUND,
                quantity=999,
                to_warehouse_id=hidden_van.id,
                notes="cross-tenant-secret",
            )
        )
        db.commit()
        return {
            "manager_id": manager.id,
            "warehouse_user_id": warehouse_user.id,
            "engineer_id": engineer.id,
            "assistant_id": assistant.id,
            "van_id": van.id,
            "main_id": main.id,
            "low_part_id": low_part.id,
            "excess_part_id": excess_part.id,
            "balanced_part_id": balanced_part.id,
            "hidden_manager_id": hidden_manager.id,
            "hidden_engineer_id": hidden_engineer.id,
            "hidden_part_id": hidden_part.id,
        }


def test_van_planning_calculates_forecast_pending_custody_and_trends(client):
    seeded = _seed_planning(client)

    response = client.get(
        f"/api/inventory/van-planning?engineer_id={seeded['engineer_id']}"
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload["lookback_days"] == 30
    assert payload["coverage_days"] == 14
    assert payload["summary"] == {
        "vehicle_count": 1,
        "engineer_count": 1,
        "consumed_quantity": 4,
        "work_order_count": 2,
        "replenish_count": 1,
        "return_count": 1,
        "balanced_count": 1,
        "recommended_replenish_quantity": 2,
        "recommended_return_quantity": 6,
    }
    assert payload["engineers"][0]["engineer_name"] == "Alice Engineer"
    assert payload["engineers"][0]["consumed_quantity"] == 4
    assert payload["engineers"][0]["work_order_count"] == 2
    assert sum(point["quantity"] for point in payload["engineers"][0]["trend"]) == 4

    recommendations = {
        row["part_number"]: row for row in payload["recommendations"]
    }
    assert set(recommendations) == {"PLAN-LOW", "PLAN-EXCESS"}
    low = recommendations["PLAN-LOW"]
    assert low["current_quantity"] == 1
    assert low["pending_inbound_quantity"] == 2
    assert low["projected_quantity"] == 3
    assert low["target_quantity"] == 5
    assert low["recommended_action"] == "replenish"
    assert low["recommended_quantity"] == 2
    assert low["suggested_warehouse_id"] == seeded["main_id"]
    assert low["suggested_warehouse_available_quantity"] == 97
    assert low["source_can_fulfill"] is True

    excess = recommendations["PLAN-EXCESS"]
    assert excess["current_quantity"] == 8
    assert excess["pending_outbound_quantity"] == 1
    assert excess["projected_quantity"] == 7
    assert excess["target_quantity"] == 1
    assert excess["recommended_action"] == "return"
    assert excess["recommended_quantity"] == 6


def test_van_planning_filters_bounds_and_tenant_isolation(client):
    seeded = _seed_planning(client)

    replenishments = client.get(
        "/api/inventory/van-planning?action=replenish&limit=1"
    )
    assert replenishments.status_code == 200, replenishments.text
    payload = replenishments.json()
    assert len(payload["recommendations"]) == 1
    assert payload["recommendations"][0]["recommended_action"] == "replenish"
    assert payload["truncated"] is False
    serialized = replenishments.text
    assert "HIDDEN-PLAN" not in serialized
    assert "cross-tenant-secret" not in serialized

    balanced = client.get(
        f"/api/inventory/van-planning?engineer_id={seeded['engineer_id']}"
        f"&part_id={seeded['balanced_part_id']}&action=balanced"
    )
    assert balanced.status_code == 200, balanced.text
    assert balanced.json()["recommendations"][0]["recommended_action"] == "balanced"

    assert client.get("/api/inventory/van-planning?lookback_days=0").status_code == 422
    assert client.get("/api/inventory/van-planning?coverage_days=91").status_code == 422
    assert client.get("/api/inventory/van-planning?action=unknown").status_code == 422
    assert client.get(
        f"/api/inventory/van-planning?engineer_id={seeded['hidden_engineer_id']}"
    ).status_code == 404
    assert client.get(
        f"/api/inventory/van-planning?part_id={seeded['hidden_part_id']}"
    ).status_code == 404


def test_van_planning_role_scope_and_second_tenant_view(client):
    seeded = _seed_planning(client)

    with _enforced_legacy_auth():
        for user_id in (seeded["manager_id"], seeded["warehouse_user_id"]):
            allowed = client.get(
                "/api/inventory/van-planning",
                headers={"X-User-Id": str(user_id)},
            )
            assert allowed.status_code == 200, allowed.text

        for user_id in (seeded["engineer_id"], seeded["assistant_id"]):
            denied = client.get(
                "/api/inventory/van-planning",
                headers={"X-User-Id": str(user_id)},
            )
            assert denied.status_code == 403

        hidden = client.get(
            "/api/inventory/van-planning?include_balanced=true",
            headers={"X-User-Id": str(seeded["hidden_manager_id"])},
        )
        assert hidden.status_code == 200, hidden.text
        hidden_payload = hidden.json()
        assert hidden_payload["summary"]["vehicle_count"] == 1
        assert hidden_payload["engineers"][0]["engineer_name"] == "Hidden Engineer"
        assert "PLAN-LOW" not in hidden.text
        assert "HIDDEN-PLAN" in hidden.text
