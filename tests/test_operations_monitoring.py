from datetime import datetime, timedelta

from app.core.config import settings
from app.core.operations import OperationsMonitor, operations_monitor
from app.models import (
    ExternalIntegration,
    ExternalSyncLog,
    Organization,
    SubscriptionNotice,
)


def test_operations_monitor_tracks_requests_worker_errors_and_staleness():
    base = datetime(2026, 8, 7, 12, 0, 0)
    monitor = OperationsMonitor(request_capacity=100)
    monitor.reset(
        delivery_enabled=True,
        delivery_interval_seconds=10,
        billing_enabled=False,
        started_at=base,
    )
    monitor.record_request(200, 10, occurred_at=base + timedelta(seconds=1))
    monitor.record_request(500, 80, occurred_at=base + timedelta(seconds=2))
    monitor.record_request(200, 20, occurred_at=base + timedelta(seconds=3))

    starting = monitor.snapshot(window_seconds=30, now=base + timedelta(seconds=10))
    assert starting["requests"] == {
        "window_seconds": 30,
        "total": 3,
        "server_errors": 1,
        "server_error_rate": 0.333333,
        "average_duration_ms": 36.667,
        "p95_duration_ms": 80,
    }
    delivery = next(row for row in starting["workers"] if row["name"] == "integration_delivery")
    assert delivery["status"] == "starting"
    billing = next(row for row in starting["workers"] if row["name"] == "billing_reconciliation")
    assert billing["status"] == "disabled"

    monitor.worker_started("integration_delivery", at=base + timedelta(seconds=11))
    monitor.worker_failed("integration_delivery", RuntimeError("secret detail"), at=base + timedelta(seconds=12))
    failed = monitor.snapshot(window_seconds=30, now=base + timedelta(seconds=13))
    delivery = next(row for row in failed["workers"] if row["name"] == "integration_delivery")
    assert delivery["status"] == "error"
    assert delivery["last_error_type"] == "RuntimeError"
    assert "secret detail" not in str(delivery)

    stale = monitor.snapshot(window_seconds=30, now=base + timedelta(seconds=61))
    delivery = next(row for row in stale["workers"] if row["name"] == "integration_delivery")
    assert delivery["status"] == "stale"

    monitor.worker_succeeded(
        "integration_delivery",
        result_count=4,
        at=base + timedelta(seconds=62),
    )
    recovered = monitor.snapshot(window_seconds=30, now=base + timedelta(seconds=63))
    delivery = next(row for row in recovered["workers"] if row["name"] == "integration_delivery")
    assert delivery["status"] == "ok"
    assert delivery["last_result_count"] == 4
    assert delivery["last_error_type"] is None


def test_health_probes_and_platform_summary_report_real_operational_risks(client):
    live = client.get("/health/live")
    assert live.status_code == 200, live.text
    assert live.json()["status"] == "alive"
    assert live.headers["cache-control"] == "no-store"
    assert live.headers["x-request-id"]

    ready = client.get("/health/ready")
    assert ready.status_code == 200, ready.text
    assert ready.json() == {
        "status": "ready",
        "checked_at": ready.json()["checked_at"],
        "database": "ok",
        "schema": "ok",
        "workers": "ok",
    }
    assert ready.headers["cache-control"] == "no-store"

    client.app.state.schema_ready = False
    not_ready = client.get("/health/ready")
    assert not_ready.status_code == 503
    assert not_ready.json()["status"] == "not_ready"
    client.app.state.schema_ready = True

    now = datetime.utcnow()
    with client.app.state.testing_session_local() as db:
        other = Organization(name="Operations Customer", slug="operations-customer")
        db.add(other)
        db.flush()
        integration = ExternalIntegration(
            organization_id=other.id,
            name="Operations ERP",
            provider="erp",
            key_prefix="opf_ops_test",
            api_key_hash="a" * 64,
        )
        db.add(integration)
        db.flush()
        db.add_all(
            [
                ExternalSyncLog(
                    organization_id=other.id,
                    integration_id=integration.id,
                    direction="outbound",
                    event_type="work_order.updated",
                    external_id="OPS-DUE",
                    idempotency_key="ops-due",
                    request_hash="b" * 64,
                    status="pending",
                    attempt_count=1,
                    next_retry_at=now - timedelta(minutes=1),
                ),
                ExternalSyncLog(
                    organization_id=other.id,
                    integration_id=integration.id,
                    direction="outbound",
                    event_type="work_order.updated",
                    external_id="OPS-FAILED",
                    idempotency_key="ops-failed",
                    request_hash="c" * 64,
                    status="failed",
                    attempt_count=5,
                    processed_at=now,
                ),
                ExternalSyncLog(
                    organization_id=other.id,
                    integration_id=integration.id,
                    direction="outbound",
                    event_type="work_order.updated",
                    external_id="OPS-STUCK",
                    idempotency_key="ops-stuck",
                    request_hash="d" * 64,
                    status="processing",
                    attempt_count=1,
                    updated_at=now - timedelta(hours=1),
                ),
                SubscriptionNotice(
                    organization_id=other.id,
                    notice_type="subscription_suspended",
                    status="open",
                    severity="critical",
                    message="Customer access is suspended.",
                    effective_at=now,
                ),
            ]
        )
        db.commit()

    for index in range(20):
        operations_monitor.record_request(
            500 if index < 2 else 200,
            1500 if index < 2 else 25,
        )
    summary = client.get("/api/platform/operations/summary")
    assert summary.status_code == 200, summary.text
    assert summary.headers["cache-control"] == "no-store"
    payload = summary.json()
    assert payload["status"] == "critical"
    assert payload["schema_revision"] == "test"
    assert payload["database_status"] == "ok"
    assert payload["integration_queue"] == {
        "outbound_pending": 1,
        "outbound_due": 1,
        "outbound_failed": 1,
        "stale_processing": 1,
    }
    assert payload["open_critical_billing_notices"] == 1
    assert payload["data_protection"]["active_organizations"] == 2
    assert payload["data_protection"]["organizations_without_recent_backup"] == 2
    assert payload["requests"]["server_errors"] >= 2
    alert_codes = {row["code"] for row in payload["alerts"]}
    assert {
        "outbound_delivery_due",
        "outbound_delivery_failed",
        "outbound_delivery_stale",
        "billing_notice_critical",
        "backup_overdue",
        "request_error_rate",
        "request_latency",
    }.issubset(alert_codes)
    assert "Customer access is suspended" not in summary.text


def test_platform_operations_rejects_customer_administrator(client):
    original_rbac = settings.rbac_enforce
    original_legacy = settings.legacy_header_auth
    try:
        settings.rbac_enforce = False
        created = client.post(
            "/api/users",
            json={
                "name": "Customer Operations Admin",
                "email": "customer-operations@example.com",
                "role": "admin",
                "password": "customer-operations-password",
            },
        )
        assert created.status_code == 200, created.text
        settings.rbac_enforce = True
        settings.legacy_header_auth = True
        denied = client.get(
            "/api/platform/operations/summary",
            headers={"X-User-Id": str(created.json()["id"])},
        )
        assert denied.status_code == 403
    finally:
        settings.rbac_enforce = original_rbac
        settings.legacy_header_auth = original_legacy
