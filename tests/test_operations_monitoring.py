from datetime import datetime, timedelta
import json

from sqlalchemy import select

from app.core.config import settings
from app.core.operations import OperationsMonitor, operations_monitor
from app.models import (
    AuditLog,
    ExternalIntegration,
    ExternalSyncLog,
    Organization,
    SubscriptionNotice,
    User,
    WorkerLease,
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

    monitor.worker_standby(
        "integration_delivery",
        at=base + timedelta(seconds=64),
    )
    standby = monitor.snapshot(window_seconds=30, now=base + timedelta(seconds=65))
    delivery = next(row for row in standby["workers"] if row["name"] == "integration_delivery")
    assert delivery["status"] == "standby"
    assert delivery["last_standby_at"].endswith("Z")


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
        db.add(
            WorkerLease(
                name="integration_delivery",
                owner_id="private-host:1234:secret-instance",
                generation=3,
                acquired_at=now,
                heartbeat_at=now,
                lease_expires_at=now + timedelta(seconds=90),
                next_run_at=now + timedelta(seconds=30),
            )
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
    delivery_worker = next(
        row for row in payload["workers"]
        if row["name"] == "integration_delivery"
    )
    assert delivery_worker["lease_generation"] == 3
    assert delivery_worker["lease_expires_at"]
    assert delivery_worker["next_run_at"]
    assert "private-host" not in summary.text
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
        recovery_denied = client.post(
            "/api/platform/operations/recover-stale-deliveries",
            headers={"X-User-Id": str(created.json()["id"])},
            json={
                "account_password": "customer-operations-password",
                "reason": "Attempted customer recovery",
            },
        )
        assert recovery_denied.status_code == 403
    finally:
        settings.rbac_enforce = original_rbac
        settings.legacy_header_auth = original_legacy


def test_platform_requeues_only_stale_processing_deliveries_with_tenant_audits(client):
    now = datetime.utcnow()
    stale_at = now - timedelta(
        minutes=max(1, settings.operations_stale_processing_minutes) + 5
    )
    with client.app.state.testing_session_local() as db:
        second = Organization(name="Recovery Tenant", slug="recovery-tenant")
        db.add(second)
        db.flush()
        integrations = [
            ExternalIntegration(
                organization_id=organization_id,
                name=f"Recovery ERP {organization_id}",
                provider="erp",
                key_prefix=f"opf_recovery_{organization_id}",
                api_key_hash=str(organization_id) * 64,
            )
            for organization_id in (1, second.id)
        ]
        db.add_all(integrations)
        db.flush()
        rows = [
            ExternalSyncLog(
                organization_id=1,
                integration_id=integrations[0].id,
                direction="outbound",
                event_type="work_order.updated",
                external_id="RECOVER-ONE",
                idempotency_key="recover-one",
                request_hash="1" * 64,
                status="processing",
                attempt_count=2,
                updated_at=stale_at,
            ),
            ExternalSyncLog(
                organization_id=second.id,
                integration_id=integrations[1].id,
                direction="outbound",
                event_type="work_order.updated",
                external_id="RECOVER-TWO",
                idempotency_key="recover-two",
                request_hash="2" * 64,
                status="processing",
                attempt_count=4,
                updated_at=stale_at,
            ),
            ExternalSyncLog(
                organization_id=second.id,
                integration_id=integrations[1].id,
                direction="outbound",
                event_type="work_order.updated",
                external_id="STILL-ACTIVE",
                idempotency_key="still-active",
                request_hash="3" * 64,
                status="processing",
                attempt_count=1,
                updated_at=now,
            ),
            ExternalSyncLog(
                organization_id=second.id,
                integration_id=integrations[1].id,
                direction="inbound",
                event_type="work_order.updated",
                external_id="INBOUND-NOT-RECOVERED",
                idempotency_key="inbound-not-recovered",
                request_hash="4" * 64,
                status="processing",
                attempt_count=1,
                updated_at=stale_at,
            ),
        ]
        db.add_all(rows)
        db.commit()
        stale_ids = {rows[0].id, rows[1].id}
        active_id = rows[2].id
        inbound_id = rows[3].id

    recovered = client.post(
        "/api/platform/operations/recover-stale-deliveries",
        json={
            "account_password": "test-only",
            "reason": "Worker host restarted during delivery",
            "max_items": 100,
        },
    )
    assert recovered.status_code == 200, recovered.text
    payload = recovered.json()
    assert payload["recovered_count"] == 2
    assert payload["organization_count"] == 2
    assert set(payload["recovered_delivery_ids"]) == stale_ids

    with client.app.state.testing_session_local() as db:
        recovered_rows = [db.get(ExternalSyncLog, row_id) for row_id in stale_ids]
        assert all(row.status == "pending" for row in recovered_rows)
        assert all(row.next_retry_at is not None for row in recovered_rows)
        assert {row.attempt_count for row in recovered_rows} == {2, 4}
        assert all(
            row.error_message == "Recovered from an interrupted processing lease"
            for row in recovered_rows
        )
        assert db.get(ExternalSyncLog, active_id).status == "processing"
        assert db.get(ExternalSyncLog, inbound_id).status == "processing"
        audits = db.scalars(
            select(AuditLog).where(
                AuditLog.action == "recover_stale_outbound_deliveries"
            )
        ).all()
        assert {row.organization_id for row in audits} == {1, 2}
        assert sum(json.loads(row.metadata_json)["recovered_count"] for row in audits) == 2
        assert all(
            json.loads(row.metadata_json)["reason"]
            == "Worker host restarted during delivery"
            for row in audits
        )

    repeated = client.post(
        "/api/platform/operations/recover-stale-deliveries",
        json={
            "account_password": "test-only",
            "reason": "Confirm recovery is idempotent",
        },
    )
    assert repeated.status_code == 200
    assert repeated.json()["recovered_count"] == 0
    assert repeated.json()["organization_count"] == 0


def test_stale_delivery_recovery_requires_platform_password(client):
    original_rbac = settings.rbac_enforce
    original_legacy = settings.legacy_header_auth
    try:
        settings.rbac_enforce = False
        created = client.post(
            "/api/users",
            json={
                "name": "Recovery Operator",
                "email": "recovery-operator@example.com",
                "role": "admin",
                "password": "recovery-operator-password",
            },
        )
        assert created.status_code == 200
        with client.app.state.testing_session_local() as db:
            operator = db.get(User, created.json()["id"])
            operator.is_platform_admin = True
            db.commit()
        settings.rbac_enforce = True
        settings.legacy_header_auth = False
        login = client.post(
            "/api/auth/login",
            data={
                "username": "recovery-operator@example.com",
                "password": "recovery-operator-password",
            },
        )
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        invalid_reason = client.post(
            "/api/platform/operations/recover-stale-deliveries",
            headers=headers,
            json={
                "account_password": "recovery-operator-password",
                "reason": "   ",
            },
        )
        assert invalid_reason.status_code == 422

        denied = client.post(
            "/api/platform/operations/recover-stale-deliveries",
            headers=headers,
            json={
                "account_password": "wrong-password",
                "reason": "Recover interrupted worker",
            },
        )
        assert denied.status_code == 401
        allowed = client.post(
            "/api/platform/operations/recover-stale-deliveries",
            headers=headers,
            json={
                "account_password": "recovery-operator-password",
                "reason": "Recover interrupted worker",
            },
        )
        assert allowed.status_code == 200
        assert allowed.json()["recovered_count"] == 0
    finally:
        settings.rbac_enforce = original_rbac
        settings.legacy_header_auth = original_legacy
