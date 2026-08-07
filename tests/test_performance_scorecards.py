from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime

from app.core.config import settings
from app.models import Organization, Part, User, UserRole, Warehouse, WorkOrder, WorkOrderPart


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


def _seed_performance(client) -> dict[str, int]:
    sessions = client.app.state.testing_session_local
    with sessions() as db:
        manager = User(organization_id=1, name="Score Manager", email="score-manager@example.test", role=UserRole.MANAGER)
        warehouse_user = User(organization_id=1, name="Score Warehouse", email="score-warehouse@example.test", role=UserRole.WAREHOUSE)
        assistant = User(organization_id=1, name="Score Assistant", email="score-assistant@example.test", role=UserRole.ASSISTANT)
        alice = User(organization_id=1, name="Alice Score", email="score-alice@example.test", role=UserRole.ENGINEER)
        bob = User(organization_id=1, name="Bob Score", email="score-bob@example.test", role=UserRole.ENGINEER)
        db.add_all([manager, warehouse_user, assistant, alice, bob])
        db.flush()
        warehouse = Warehouse(organization_id=1, code="SCORE-WH", name="Score Warehouse")
        part = Part(organization_id=1, part_number="SCORE-PART", name="Score part")
        db.add_all([warehouse, part])
        db.flush()

        orders = [
            WorkOrder(
                organization_id=1,
                ticket_number="SCORE-A1",
                assigned_user_id=alice.id,
                engineer_id=alice.id,
                completed_by_id=alice.id,
                status="COMPLETED",
                created_at=datetime(2026, 8, 1, 8),
                completed_at=datetime(2026, 8, 2, 12),
                first_time_fix=True,
                is_rework=False,
                repair_duration_minutes=60,
                revenue=200,
                labor_cost=50,
                is_locked=True,
            ),
            WorkOrder(
                organization_id=1,
                ticket_number="SCORE-A2",
                assigned_user_id=alice.id,
                engineer_id=alice.id,
                status="open",
                created_at=datetime(2026, 8, 3, 8),
            ),
            WorkOrder(
                organization_id=1,
                ticket_number="SCORE-A3",
                assigned_user_id=alice.id,
                engineer_id=alice.id,
                completed_by_id=alice.id,
                status="COMPLETED",
                created_at=datetime(2026, 7, 20, 8),
                completed_at=datetime(2026, 8, 4, 12),
                first_time_fix=False,
                is_rework=True,
                repair_duration_minutes=120,
                revenue=100,
                labor_cost=20,
                is_locked=True,
            ),
            WorkOrder(
                organization_id=1,
                ticket_number="SCORE-B1",
                assigned_user_id=bob.id,
                engineer_id=bob.id,
                completed_by_id=bob.id,
                status="COMPLETED",
                created_at=datetime(2026, 8, 1, 9),
                completed_at=datetime(2026, 8, 5, 12),
                first_time_fix=None,
                is_rework=False,
                revenue=0,
                labor_cost=10,
                is_locked=True,
            ),
            WorkOrder(
                organization_id=1,
                ticket_number="SCORE-B2",
                assigned_user_id=bob.id,
                engineer_id=bob.id,
                completed_by_id=bob.id,
                status="COMPLETED",
                created_at=datetime(2026, 8, 6, 9),
                completed_at=datetime(2026, 8, 20, 12),
                first_time_fix=True,
                is_rework=False,
                revenue=80,
                labor_cost=10,
                is_locked=True,
            ),
        ]
        db.add_all(orders)
        db.flush()
        db.add_all(
            [
                WorkOrderPart(
                    organization_id=1,
                    work_order_id=orders[0].id,
                    part_id=part.id,
                    warehouse_id=warehouse.id,
                    user_id=alice.id,
                    quantity=2,
                    unit_cost=20,
                    total_cost=40,
                ),
                WorkOrderPart(
                    organization_id=1,
                    work_order_id=orders[2].id,
                    part_id=part.id,
                    warehouse_id=warehouse.id,
                    user_id=alice.id,
                    quantity=1,
                    unit_cost=10,
                    total_cost=10,
                ),
            ]
        )

        hidden_org = Organization(name="Hidden score tenant", slug="hidden-score")
        db.add(hidden_org)
        db.flush()
        hidden_manager = User(organization_id=hidden_org.id, name="Hidden Manager", email="hidden-score-manager@example.test", role=UserRole.MANAGER)
        hidden_engineer = User(organization_id=hidden_org.id, name="Hidden Engineer", email="hidden-score-engineer@example.test", role=UserRole.ENGINEER)
        db.add_all([hidden_manager, hidden_engineer])
        db.flush()
        db.add(
            WorkOrder(
                organization_id=hidden_org.id,
                ticket_number="HIDDEN-SCORE",
                assigned_user_id=hidden_engineer.id,
                engineer_id=hidden_engineer.id,
                completed_by_id=hidden_engineer.id,
                status="COMPLETED",
                created_at=datetime(2026, 8, 1),
                completed_at=datetime(2026, 8, 2),
                is_locked=True,
            )
        )
        db.commit()
        return {
            "manager_id": manager.id,
            "warehouse_id": warehouse_user.id,
            "assistant_id": assistant.id,
            "alice_id": alice.id,
            "bob_id": bob.id,
            "hidden_manager_id": hidden_manager.id,
        }


def test_manager_performance_scorecards_reconcile_multi_metric_evidence(client):
    seeded = _seed_performance(client)
    with _enforced_legacy_auth():
        response = client.get(
            "/api/performance/scorecards?from_date=2026-08-01&to_date=2026-08-10",
            headers={"X-User-Id": str(seeded["manager_id"])},
        )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload["viewer_scope"] == "team"
    assert payload["can_view_team"] is True
    assert payload["can_view_financials"] is True
    rows = {row["engineer_name"]: row for row in payload["scorecards"]}
    assert set(rows) == {"Alice Score", "Bob Score"}

    alice = rows["Alice Score"]
    assert alice["cohort_received"] == 2
    assert alice["cohort_completed"] == 1
    assert alice["completion_rate"] == 0.5
    assert alice["completed_in_period"] == 2
    assert alice["throughput_per_30_days"] == 6
    assert alice["first_time_fix_rate"] == 0.5
    assert alice["first_time_fix_coverage"] == 1
    assert alice["rework_rate"] == 0.5
    assert alice["average_repair_minutes"] == 90
    assert alice["repair_duration_coverage"] == 1
    assert alice["parts_usage_coverage"] == 1
    assert alice["parts_quantity"] == 3
    assert alice["parts_quantity_per_completed"] == 1.5
    assert alice["parts_cost"] == 50
    assert alice["parts_cost_per_completed"] == 25
    assert alice["parts_cost_to_revenue_rate"] == 0.1667
    assert alice["contribution"] == 180

    bob = rows["Bob Score"]
    assert bob["cohort_received"] == 2
    assert bob["cohort_completed"] == 1
    assert bob["completed_in_period"] == 1
    assert bob["first_time_fix_rate"] is None
    assert bob["first_time_fix_coverage"] == 0
    assert bob["parts_cost_to_revenue_rate"] is None
    assert payload["team"]["completed_in_period"] == 3
    assert payload["team"]["cohort_received"] == 4
    assert payload["team"]["cohort_completed"] == 2
    assert payload["team"]["completion_rate"] == 0.5
    assert "Lower use is not automatically better" in payload["definitions"]["parts_efficiency"]


def test_engineer_dashboard_is_self_only_and_redacts_financials(client):
    seeded = _seed_performance(client)
    url = "/api/performance/scorecards?from_date=2026-08-01&to_date=2026-08-10"
    with _enforced_legacy_auth():
        own = client.get(url, headers={"X-User-Id": str(seeded["alice_id"])})
        denied = client.get(
            f"{url}&engineer_id={seeded['bob_id']}",
            headers={"X-User-Id": str(seeded["alice_id"])},
        )
    assert own.status_code == 200, own.text
    payload = own.json()
    assert payload["viewer_scope"] == "self"
    assert payload["can_view_team"] is False
    assert payload["can_view_financials"] is False
    assert payload["engineer_options"] == []
    assert len(payload["scorecards"]) == 1
    row = payload["scorecards"][0]
    assert row["engineer_id"] == seeded["alice_id"]
    assert row["parts_quantity"] == 3
    for key in (
        "parts_cost",
        "parts_cost_per_completed",
        "parts_cost_to_revenue_rate",
        "revenue",
        "labor_cost",
        "contribution",
    ):
        assert row[key] is None
    assert payload["team"]["parts_cost_per_completed"] is None
    assert denied.status_code == 403


def test_performance_permissions_filters_bounds_and_tenant_scope(client):
    seeded = _seed_performance(client)
    base = "/api/performance/scorecards?from_date=2026-08-01&to_date=2026-08-10"
    with _enforced_legacy_auth():
        selected = client.get(
            f"{base}&engineer_id={seeded['bob_id']}",
            headers={"X-User-Id": str(seeded["manager_id"])},
        )
        hidden = client.get(
            base,
            headers={"X-User-Id": str(seeded["hidden_manager_id"])},
        )
        denied_roles = [
            client.get(base, headers={"X-User-Id": str(user_id)}).status_code
            for user_id in (seeded["warehouse_id"], seeded["assistant_id"])
        ]
    assert selected.status_code == 200, selected.text
    assert [row["engineer_name"] for row in selected.json()["scorecards"]] == ["Bob Score"]
    assert hidden.status_code == 200, hidden.text
    assert [row["engineer_name"] for row in hidden.json()["scorecards"]] == ["Hidden Engineer"]
    assert "Alice Score" not in hidden.text
    assert denied_roles == [403, 403]
    assert client.get(
        "/api/performance/scorecards?from_date=2026-08-11&to_date=2026-08-10"
    ).status_code == 422
    assert client.get(
        "/api/performance/scorecards?from_date=2024-01-01&to_date=2026-08-10"
    ).status_code == 422
