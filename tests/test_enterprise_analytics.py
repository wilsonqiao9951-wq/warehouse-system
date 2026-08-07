from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json

from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.models import (
    AuditLog,
    InventoryTransaction,
    Organization,
    Part,
    TransactionType,
    User,
    UserRole,
    Warehouse,
    WorkOrder,
    WorkOrderPart,
)


PASSWORD = "enterprise-analytics-password"


def _create_user(client, name: str, role: str = "engineer", headers=None) -> dict:
    response = client.post(
        "/api/users",
        headers=headers or {},
        json={
            "name": name,
            "email": f"{name.strip('=-+@').lower()}@analytics.test",
            "role": role,
            "password": PASSWORD,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _headers(user_id: int) -> dict[str, str]:
    return {"X-User-Id": str(user_id)}


def _seed_analytics_data(client) -> dict:
    engineer_one = _create_user(client, "Analytics Engineer One")
    engineer_two = _create_user(client, "Analytics Engineer Two")
    warehouse = client.post("/api/warehouses", json={"name": "Analytics Main"}).json()
    part = client.post(
        "/api/parts",
        json={
            "part_number": "ANALYTICS-PART",
            "name": "Analytics part",
            "default_cost": 10,
            "safety_stock": 1,
        },
    ).json()
    with client.app.state.testing_session_local() as db:
        prior = WorkOrder(
            organization_id=1,
            ticket_number="AN-PRIOR",
            engineer_id=engineer_one["id"],
            completed_by_id=engineer_one["id"],
            job_type="Repair",
            status="COMPLETED",
            is_locked=True,
            first_time_fix=True,
            is_rework=False,
            repair_duration_minutes=60,
            revenue=100,
            labor_cost=10,
            created_at=datetime(2026, 7, 1, 9),
            completed_at=datetime(2026, 7, 15, 12),
        )
        repair = WorkOrder(
            organization_id=1,
            ticket_number="AN-REPAIR",
            engineer_id=engineer_one["id"],
            completed_by_id=engineer_one["id"],
            job_type="Repair",
            status="COMPLETED",
            is_locked=True,
            first_time_fix=True,
            is_rework=False,
            repair_duration_minutes=60,
            revenue=200,
            labor_cost=20,
            created_at=datetime(2026, 8, 1, 9),
            completed_at=datetime(2026, 8, 10, 12),
        )
        inspection = WorkOrder(
            organization_id=1,
            ticket_number="AN-INSPECTION",
            engineer_id=engineer_two["id"],
            completed_by_id=engineer_two["id"],
            job_type="Inspection",
            status="COMPLETED",
            is_locked=True,
            first_time_fix=False,
            is_rework=True,
            repair_duration_minutes=120,
            revenue=100,
            labor_cost=30,
            created_at=datetime(2026, 7, 30, 9),
            completed_at=datetime(2026, 8, 20, 12),
        )
        backlog = WorkOrder(
            organization_id=1,
            ticket_number="AN-BACKLOG",
            engineer_id=engineer_two["id"],
            job_type="Repair",
            status="OPEN",
            is_rework=False,
            created_at=datetime(2026, 8, 5, 9),
        )
        cancelled = WorkOrder(
            organization_id=1,
            ticket_number="AN-CANCELLED",
            engineer_id=engineer_two["id"],
            job_type="Repair",
            status="CANCELLED",
            is_rework=False,
            created_at=datetime(2026, 8, 6, 9),
        )
        db.add_all([prior, repair, inspection, backlog, cancelled])
        db.flush()
        db.add_all(
            [
                WorkOrderPart(
                    organization_id=1,
                    work_order_id=repair.id,
                    part_id=part["id"],
                    warehouse_id=warehouse["id"],
                    user_id=engineer_one["id"],
                    quantity=2,
                    unit_cost=15,
                    total_cost=30,
                ),
                WorkOrderPart(
                    organization_id=1,
                    work_order_id=inspection.id,
                    part_id=part["id"],
                    warehouse_id=warehouse["id"],
                    user_id=engineer_two["id"],
                    quantity=1,
                    unit_cost=20,
                    total_cost=20,
                ),
                InventoryTransaction(
                    organization_id=1,
                    part_id=part["id"],
                    transaction_type=TransactionType.INBOUND,
                    quantity=20,
                    to_warehouse_id=warehouse["id"],
                ),
                InventoryTransaction(
                    organization_id=1,
                    part_id=part["id"],
                    transaction_type=TransactionType.WORK_ORDER_USED,
                    quantity=2,
                    from_warehouse_id=warehouse["id"],
                    work_order_id=repair.id,
                    user_id=engineer_one["id"],
                ),
                InventoryTransaction(
                    organization_id=1,
                    part_id=part["id"],
                    transaction_type=TransactionType.WORK_ORDER_USED,
                    quantity=1,
                    from_warehouse_id=warehouse["id"],
                    work_order_id=inspection.id,
                    user_id=engineer_two["id"],
                ),
            ]
        )
        db.commit()
    return {
        "engineer_one": engineer_one,
        "engineer_two": engineer_two,
        "warehouse": warehouse,
        "part": part,
    }


def _analytics(client, suffix: str = ""):
    response = client.get(
        "/api/analytics/operations?from_date=2026-08-01&to_date=2026-08-31" + suffix
    )
    assert response.status_code == 200, response.text
    return response


def test_enterprise_analytics_metrics_reconcile_to_source_records(client):
    seeded = _seed_analytics_data(client)
    response = _analytics(client)
    payload = response.json()
    assert response.headers["cache-control"] == "no-store"
    assert payload["period"] == {
        "from_date": "2026-08-01",
        "to_date": "2026-08-31",
        "previous_from_date": "2026-07-01",
        "previous_to_date": "2026-07-31",
        "days": 31,
        "grain": "day",
        "timezone": "UTC",
    }
    kpis = {row["code"]: row for row in payload["kpis"]}
    assert kpis["work_orders_created"]["value"] == 3
    assert kpis["work_orders_created"]["previous_value"] == 2
    assert kpis["completed_work_orders"]["value"] == 2
    assert kpis["period_end_backlog"]["value"] == 1
    assert kpis["period_end_backlog"]["previous_value"] == 1
    assert kpis["first_time_fix_rate"]["value"] == 50
    assert kpis["rework_rate"]["value"] == 50
    assert kpis["average_repair_hours"]["value"] == 1.5
    assert kpis["gross_contribution"]["value"] == 200
    assert kpis["gross_contribution"]["previous_value"] == 90

    by_bucket = {row["bucket_start"]: row for row in payload["trend"]}
    assert by_bucket["2026-08-01"]["created_count"] == 1
    assert by_bucket["2026-08-10"]["completed_count"] == 1
    assert by_bucket["2026-08-20"]["rework_rate"] == 1
    engineers = {row["engineer_id"]: row for row in payload["engineers"]}
    assert engineers[seeded["engineer_one"]["id"]]["contribution"] == 150
    assert engineers[seeded["engineer_two"]["id"]]["contribution"] == 50
    job_types = {row["job_type"]: row for row in payload["job_types"]}
    assert job_types["Repair"]["first_time_fix_rate"] == 1
    assert job_types["Inspection"]["rework_rate"] == 1
    region = payload["regions"][0]
    assert region["stock_quantity"] == 17
    assert region["stock_value"] == 170
    assert region["low_stock_sku_count"] == 0
    assert region["completed_work_orders_with_usage"] == 2
    assert region["consumed_quantity"] == 3
    assert region["consumed_parts_cost"] == 50
    assert payload["data_quality"]["first_time_fix_coverage"] == 1
    assert payload["data_quality"]["repair_duration_coverage"] == 1
    assert payload["data_quality"]["engineer_attribution_coverage"] == 1


def test_analytics_filters_ranges_and_tenant_isolation(client):
    seeded = _seed_analytics_data(client)
    engineer_filtered = _analytics(
        client,
        f"&engineer_id={seeded['engineer_one']['id']}",
    ).json()
    kpis = {row["code"]: row for row in engineer_filtered["kpis"]}
    assert kpis["completed_work_orders"]["value"] == 1
    assert kpis["first_time_fix_rate"]["value"] == 100
    assert len(engineer_filtered["engineers"]) == 1

    job_filtered = _analytics(client, "&job_type=Inspection").json()
    kpis = {row["code"]: row for row in job_filtered["kpis"]}
    assert kpis["completed_work_orders"]["value"] == 1
    assert kpis["rework_rate"]["value"] == 100

    assert client.get(
        "/api/analytics/operations?from_date=2026-08-31&to_date=2026-08-01"
    ).status_code == 422
    assert client.get(
        "/api/analytics/operations?from_date=2025-01-01&to_date=2026-08-01"
    ).status_code == 422
    missing_engineer = client.get(
        "/api/analytics/operations?from_date=2026-08-01&to_date=2026-08-31&engineer_id=99999"
    )
    assert missing_engineer.status_code == 404

    with client.app.state.testing_session_local() as db:
        second = Organization(name="Analytics Tenant Two", slug="analytics-tenant-two")
        db.add(second)
        db.flush()
        db.add(
            WorkOrder(
                organization_id=second.id,
                ticket_number="AN-TENANT-TWO",
                status="COMPLETED",
                is_locked=True,
                first_time_fix=True,
                is_rework=False,
                created_at=datetime(2026, 8, 1),
                completed_at=datetime(2026, 8, 2),
            )
        )
        db.commit()
    tenant_one = _analytics(client).json()
    completed = next(row for row in tenant_one["kpis"] if row["code"] == "completed_work_orders")
    assert completed["value"] == 2


def test_analytics_permission_overrides_export_reauthentication_and_audit(client):
    original_rbac = settings.rbac_enforce
    original_legacy = settings.legacy_header_auth
    try:
        settings.rbac_enforce = False
        admin = _create_user(client, "Analytics Admin", "admin")
        export_engineer = _create_user(client, "=Formula Engineer", "engineer")
        settings.rbac_enforce = True
        settings.legacy_header_auth = True
        warehouse_user = _create_user(
            client,
            "Analytics Warehouse",
            "warehouse",
            _headers(admin["id"]),
        )
        with client.app.state.testing_session_local() as db:
            db.add(
                WorkOrder(
                    organization_id=1,
                    ticket_number="=FORMULA-TICKET",
                    engineer_id=export_engineer["id"],
                    completed_by_id=export_engineer["id"],
                    job_type="@Formula Job",
                    status="COMPLETED",
                    is_locked=True,
                    first_time_fix=True,
                    is_rework=False,
                    repair_duration_minutes=45,
                    revenue=100,
                    labor_cost=25,
                    created_at=datetime(2026, 8, 1),
                    completed_at=datetime(2026, 8, 2),
                )
            )
            db.commit()

        denied = client.get(
            "/api/analytics/operations?from_date=2026-08-01&to_date=2026-08-31",
            headers=_headers(warehouse_user["id"]),
        )
        assert denied.status_code == 403
        for permission in ("reports.read", "reports.export"):
            granted = client.put(
                f"/api/users/{warehouse_user['id']}/permissions/{permission}",
                headers=_headers(admin["id"]),
                json={"effect": "allow", "reason": "Delegated analytics responsibility"},
            )
            assert granted.status_code == 200, granted.text

        login = client.post(
            "/api/auth/login",
            data={"username": warehouse_user["email"], "password": PASSWORD},
        )
        assert login.status_code == 200, login.text
        bearer = {"Authorization": f"Bearer {login.json()['access_token']}"}
        allowed = client.get(
            "/api/analytics/operations?from_date=2026-08-01&to_date=2026-08-31",
            headers=bearer,
        )
        assert allowed.status_code == 200
        wrong_password = client.post(
            "/api/analytics/operations/export",
            headers=bearer,
            json={
                "from_date": "2026-08-01",
                "to_date": "2026-08-31",
                "account_password": "wrong-password-value",
            },
        )
        assert wrong_password.status_code == 401
        exported = client.post(
            "/api/analytics/operations/export",
            headers=bearer,
            json={
                "from_date": "2026-08-01",
                "to_date": "2026-08-31",
                "account_password": PASSWORD,
            },
        )
        assert exported.status_code == 200, exported.text
        assert exported.headers["cache-control"] == "no-store"
        assert exported.headers["x-record-count"] == "1"
        assert exported.headers["x-content-sha256"] == sha256(exported.content).hexdigest()
        csv_text = exported.content.decode("utf-8-sig")
        assert "'=FORMULA-TICKET" in csv_text
        assert "'=Formula Engineer" in csv_text
        assert "'@Formula Job" in csv_text
        assert PASSWORD not in csv_text
        with client.app.state.testing_session_local() as db:
            audit = db.scalar(
                select(AuditLog).where(AuditLog.action == "enterprise_analytics_exported")
            )
            assert audit is not None
            metadata = json.loads(audit.metadata_json)
            assert metadata["row_count"] == 1
            assert metadata["sha256"] == exported.headers["x-content-sha256"]
            assert "password" not in audit.metadata_json.lower()
    finally:
        settings.rbac_enforce = original_rbac
        settings.legacy_header_auth = original_legacy


def test_analytics_export_row_limit_is_fail_closed(client):
    _seed_analytics_data(client)
    original_limit = settings.max_analytics_export_rows
    try:
        settings.max_analytics_export_rows = 1
        response = client.post(
            "/api/analytics/operations/export",
            json={
                "from_date": "2026-08-01",
                "to_date": "2026-08-31",
                "account_password": None,
            },
        )
        assert response.status_code == 413
        assert "narrow the filters" in response.json()["detail"]
    finally:
        settings.max_analytics_export_rows = original_limit
