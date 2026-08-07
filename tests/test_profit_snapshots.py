from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.models import (
    AuditLog,
    InventoryRegion,
    Organization,
    Part,
    User,
    UserRole,
    Warehouse,
    WorkOrder,
    WorkOrderPart,
    WorkOrderProfitSnapshot,
)
from app.services.profit_snapshots import capture_profit_snapshot


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


def _seed_profit_history(client) -> dict[str, int]:
    sessions = client.app.state.testing_session_local
    with sessions() as db:
        manager = User(organization_id=1, name="Profit Manager", email="profit-manager@example.test", role=UserRole.MANAGER)
        warehouse_user = User(organization_id=1, name="Profit Warehouse", email="profit-warehouse@example.test", role=UserRole.WAREHOUSE)
        engineer_one = User(organization_id=1, name="Profit Alice", email="profit-alice@example.test", role=UserRole.ENGINEER)
        engineer_two = User(organization_id=1, name="Profit Bob", email="profit-bob@example.test", role=UserRole.ENGINEER)
        assistant = User(organization_id=1, name="Profit Assistant", email="profit-assistant@example.test", role=UserRole.ASSISTANT)
        east = InventoryRegion(organization_id=1, code="EAST-P", name="Profit East", is_default=True)
        west = InventoryRegion(organization_id=1, code="WEST-P", name="Profit West")
        db.add_all([manager, warehouse_user, engineer_one, engineer_two, assistant, east, west])
        db.flush()
        east_van = Warehouse(organization_id=1, code="P-EAST-VAN", name="East profit van", warehouse_type="van", assigned_user_id=engineer_one.id, region_id=east.id)
        west_van = Warehouse(organization_id=1, code="P-WEST-VAN", name="West profit van", warehouse_type="van", assigned_user_id=engineer_two.id, region_id=west.id)
        part = Part(organization_id=1, part_number="PROFIT-PART", name="Profit part")
        db.add_all([east_van, west_van, part])
        db.flush()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        orders = [
            WorkOrder(organization_id=1, ticket_number="PROFIT-1", status="COMPLETED", completed_at=now - timedelta(days=2), completed_by_id=engineer_one.id, machine_type="AC", revenue=200, labor_cost=40, is_locked=True),
            WorkOrder(organization_id=1, ticket_number="PROFIT-2", status="COMPLETED", completed_at=now - timedelta(days=1), completed_by_id=engineer_two.id, machine_type="AC", revenue=100, labor_cost=20, is_locked=True),
            WorkOrder(organization_id=1, ticket_number="PROFIT-3", status="COMPLETED", completed_at=now, completed_by_id=engineer_two.id, machine_type="HVAC", revenue=150, labor_cost=50, is_locked=True),
        ]
        db.add_all(orders)
        db.flush()
        db.add_all([
            WorkOrderPart(organization_id=1, work_order_id=orders[0].id, part_id=part.id, warehouse_id=east_van.id, user_id=engineer_one.id, quantity=1, unit_cost=30, total_cost=30),
            WorkOrderPart(organization_id=1, work_order_id=orders[1].id, part_id=part.id, warehouse_id=west_van.id, user_id=engineer_two.id, quantity=1, unit_cost=10, total_cost=10),
        ])
        db.flush()
        first_snapshot, created = capture_profit_snapshot(db, orders[0])
        assert created is True

        hidden_org = Organization(name="Hidden profit tenant", slug="hidden-profit")
        db.add(hidden_org)
        db.flush()
        hidden_manager = User(organization_id=hidden_org.id, name="Hidden Profit Manager", email="hidden-profit@example.test", role=UserRole.MANAGER)
        hidden_order = WorkOrder(organization_id=hidden_org.id, ticket_number="HIDDEN-PROFIT", status="COMPLETED", completed_at=now, revenue=999, labor_cost=1, is_locked=True)
        db.add_all([hidden_manager, hidden_order])
        db.commit()
        return {
            "manager_id": manager.id,
            "warehouse_user_id": warehouse_user.id,
            "engineer_id": engineer_one.id,
            "assistant_id": assistant.id,
            "first_order_id": orders[0].id,
            "second_order_id": orders[1].id,
            "third_order_id": orders[2].id,
            "first_snapshot_id": first_snapshot.id,
            "hidden_manager_id": hidden_manager.id,
        }


def test_profit_snapshot_backfill_is_idempotent_and_rankings_are_persisted(client):
    seeded = _seed_profit_history(client)

    before = client.get("/api/analytics/profit-snapshots")
    assert before.status_code == 200, before.text
    assert before.headers["cache-control"] == "no-store"
    assert before.json()["summary"]["completed_work_orders"] == 3
    assert before.json()["summary"]["snapshot_count"] == 1
    assert before.json()["summary"]["missing_snapshot_count"] == 2

    backfill = client.post("/api/analytics/profit-snapshots/backfill", json={"limit": 100})
    assert backfill.status_code == 200, backfill.text
    assert backfill.json() == {
        "scanned": 3,
        "created": 2,
        "existing": 1,
        "conflicts": 0,
        "next_after_work_order_id": None,
    }
    repeated = client.post("/api/analytics/profit-snapshots/backfill", json={"limit": 100})
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["created"] == 0
    assert repeated.json()["existing"] == 3

    dashboard = client.get("/api/analytics/profit-snapshots?ranking_limit=10")
    assert dashboard.status_code == 200, dashboard.text
    payload = dashboard.json()
    assert payload["summary"] == {
        "completed_work_orders": 3,
        "snapshot_count": 3,
        "missing_snapshot_count": 0,
        "coverage_rate": 1.0,
        "revenue": 450.0,
        "labor_cost": 110.0,
        "parts_cost": 40.0,
        "profit": 300.0,
        "margin_rate": 0.6667,
    }
    engineers = {row["label"]: row for row in payload["engineers"]}
    assert engineers["Profit Bob"]["profit"] == 170
    assert engineers["Profit Alice"]["profit"] == 130
    regions = {row["label"]: row for row in payload["regions"]}
    assert regions["Profit West"]["profit"] == 170
    assert regions["Profit East"]["profit"] == 130
    machines = {row["label"]: row for row in payload["machine_types"]}
    assert machines["AC"]["profit"] == 200
    assert machines["HVAC"]["profit"] == 100
    assert sum(row["completed_count"] for row in payload["daily"]) == 3
    assert "HIDDEN-PROFIT" not in dashboard.text

    sessions = client.app.state.testing_session_local
    with sessions() as db:
        audits = db.query(AuditLog).filter(AuditLog.action == "profit_snapshots_backfilled").all()
        assert len(audits) == 2
        assert all("account_password" not in (row.metadata_json or "") for row in audits)


def test_profit_snapshot_conflict_is_disclosed_without_overwriting_evidence(client):
    seeded = _seed_profit_history(client)
    sessions = client.app.state.testing_session_local
    with sessions() as db:
        work_order = db.get(WorkOrder, seeded["first_order_id"])
        work_order.revenue = 999
        db.commit()

    result = client.post("/api/analytics/profit-snapshots/backfill", json={"limit": 100})
    assert result.status_code == 200, result.text
    assert result.json()["conflicts"] == 1
    assert result.json()["created"] == 2
    with sessions() as db:
        snapshot = db.get(WorkOrderProfitSnapshot, seeded["first_snapshot_id"])
        assert snapshot.revenue == 200
        assert snapshot.profit == 130


def test_profit_snapshot_routes_enforce_report_permissions_and_tenant_scope(client):
    seeded = _seed_profit_history(client)
    with _enforced_legacy_auth():
        manager = client.get(
            "/api/analytics/profit-snapshots",
            headers={"X-User-Id": str(seeded["manager_id"])},
        )
        assert manager.status_code == 200, manager.text
        hidden = client.get(
            "/api/analytics/profit-snapshots",
            headers={"X-User-Id": str(seeded["hidden_manager_id"])},
        )
        assert hidden.status_code == 200, hidden.text
        assert hidden.json()["summary"]["completed_work_orders"] == 1
        assert hidden.json()["summary"]["snapshot_count"] == 0
        for user_id in (seeded["warehouse_user_id"], seeded["engineer_id"], seeded["assistant_id"]):
            denied = client.get(
                "/api/analytics/profit-snapshots",
                headers={"X-User-Id": str(user_id)},
            )
            assert denied.status_code == 403

    assert client.get("/api/analytics/profit-snapshots?from_date=2026-08-02&to_date=2026-08-01").status_code == 422
    assert client.get("/api/analytics/profit-snapshots?from_date=2024-01-01&to_date=2026-08-01").status_code == 422
    assert client.post(
        "/api/analytics/profit-snapshots/backfill",
        json={"from_date": "2010-01-01", "to_date": "2026-08-01"},
    ).status_code == 422


def test_completed_workflow_captures_profit_snapshot_in_same_commit(client):
    _seed_profit_history(client)
    created = client.post(
        "/api/work-orders",
        json={
            "ticket_number": "PROFIT-LIVE",
            "store_name": "Profit live customer",
            "machine_type": "Chiller",
            "revenue": 80,
            "labor_cost": 30,
        },
    )
    assert created.status_code == 200, created.text
    work_order_id = created.json()["id"]
    completed = client.post(
        f"/api/work-orders/{work_order_id}/complete",
        json={
            "repair_result": "Restored service",
            "final_outcome": "resolved",
            "first_time_fix": True,
            "is_rework": False,
        },
    )
    assert completed.status_code == 200, completed.text
    sessions = client.app.state.testing_session_local
    with sessions() as db:
        snapshot = db.query(WorkOrderProfitSnapshot).filter_by(work_order_id=work_order_id).one()
        assert snapshot.ticket_number == "PROFIT-LIVE"
        assert snapshot.machine_type == "Chiller"
        assert snapshot.profit == 50
        assert len(snapshot.source_fingerprint) == 64
