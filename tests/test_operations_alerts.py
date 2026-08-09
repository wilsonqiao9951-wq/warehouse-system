from datetime import datetime, timedelta
from hashlib import sha256
import hmac
import json

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import AuditLog, OperationsAlertDelivery, OperationsAlertIncident
from app.services.operations_alerts import (
    _pinned_webhook_sender,
    deliver_operations_alert,
    enqueue_operations_alert_test,
    reconcile_operations_alerts,
)


@pytest.fixture
def configured_alert_delivery():
    original = {
        "enabled": settings.operations_alert_delivery_enabled,
        "url": settings.operations_alert_webhook_url,
        "secret": settings.operations_alert_webhook_secret,
        "severity": settings.operations_alert_min_severity,
        "reminder": settings.operations_alert_reminder_minutes,
    }
    settings.operations_alert_delivery_enabled = True
    settings.operations_alert_webhook_url = "https://alerts.example.test/openpartsflow"
    settings.operations_alert_webhook_secret = "test-operations-alert-secret-with-32-characters"
    settings.operations_alert_min_severity = "critical"
    settings.operations_alert_reminder_minutes = 5
    try:
        yield
    finally:
        settings.operations_alert_delivery_enabled = original["enabled"]
        settings.operations_alert_webhook_url = original["url"]
        settings.operations_alert_webhook_secret = original["secret"]
        settings.operations_alert_min_severity = original["severity"]
        settings.operations_alert_reminder_minutes = original["reminder"]


def test_alert_incident_transitions_escalate_remind_and_resolve(
    client,
    configured_alert_delivery,
):
    opened_at = datetime(2026, 8, 8, 12, 0, 0)
    with client.app.state.testing_session_local() as db:
        transitions, queued = reconcile_operations_alerts(
            db,
            [
                {
                    "code": "request_latency",
                    "severity": "warning",
                    "message": "Latency is elevated.",
                    "count": 1,
                }
            ],
            now=opened_at,
        )
        db.commit()
        assert (transitions, queued) == (1, 0)

        transitions, queued = reconcile_operations_alerts(
            db,
            [
                {
                    "code": "request_latency",
                    "severity": "critical",
                    "message": "Latency is critically elevated.",
                    "count": 3,
                }
            ],
            now=opened_at + timedelta(minutes=1),
        )
        db.commit()
        assert (transitions, queued) == (1, 1)
        incident = db.scalar(select(OperationsAlertIncident))
        assert incident.status == "open"
        assert incident.current_count == 3
        assert incident.peak_count == 3
        assert incident.observation_count == 2
        escalated_delivery = db.scalar(select(OperationsAlertDelivery))
        assert escalated_delivery.event_type == "escalated"
        escalated_delivery.status = "sent"
        escalated_delivery.sent_at = opened_at + timedelta(minutes=1)
        db.add(escalated_delivery)
        db.commit()

        transitions, queued = reconcile_operations_alerts(
            db,
            [
                {
                    "code": "request_latency",
                    "severity": "critical",
                    "message": "Latency is critically elevated.",
                    "count": 2,
                }
            ],
            now=opened_at + timedelta(minutes=7),
        )
        db.commit()
        assert (transitions, queued) == (0, 1)
        events = db.scalars(
            select(OperationsAlertDelivery).order_by(OperationsAlertDelivery.id)
        ).all()
        assert [row.event_type for row in events] == ["escalated", "reminder"]

        transitions, queued = reconcile_operations_alerts(
            db,
            [],
            now=opened_at + timedelta(minutes=8),
        )
        db.commit()
        assert (transitions, queued) == (1, 1)
        db.refresh(incident)
        assert incident.status == "resolved"
        assert incident.current_count == 0
        assert incident.resolved_at == opened_at + timedelta(minutes=8)
        events = db.scalars(
            select(OperationsAlertDelivery).order_by(OperationsAlertDelivery.id)
        ).all()
        assert [row.event_type for row in events] == [
            "escalated",
            "reminder",
            "resolved",
        ]


def test_signed_delivery_retains_only_safe_result_evidence(
    client,
    configured_alert_delivery,
):
    captured = {}
    with client.app.state.testing_session_local() as db:
        delivery = enqueue_operations_alert_test(
            db,
            now=datetime(2026, 8, 8, 13, 0, 0),
        )
        db.commit()
        delivery_id = delivery.id

        def sender(url: str, body: bytes, headers: dict[str, str]) -> int:
            captured.update(url=url, body=body, headers=headers)
            return 204

        result = deliver_operations_alert(db, delivery_id, sender=sender)
        assert result.status == "sent"
        assert result.response_status_code == 204
        assert result.attempt_count == 1
        assert result.failure_code is None
        assert result.sent_at is not None

        timestamp = captured["headers"]["X-OpenPartsFlow-Timestamp"]
        expected = hmac.new(
            settings.operations_alert_webhook_secret.encode("utf-8"),
            timestamp.encode("ascii") + b"." + captured["body"],
            sha256,
        ).hexdigest()
        assert captured["headers"]["X-OpenPartsFlow-Operations-Signature"] == f"sha256={expected}"
        assert captured["headers"]["Idempotency-Key"] == result.idempotency_key
        assert settings.operations_alert_webhook_secret not in result.payload_json
        assert "response" not in result.payload_json


def test_delivery_fails_after_five_safe_retries_and_admin_can_requeue(
    client,
    configured_alert_delivery,
):
    with client.app.state.testing_session_local() as db:
        delivery = enqueue_operations_alert_test(db)
        db.commit()
        delivery_id = delivery.id
        for _ in range(5):
            delivery = deliver_operations_alert(
                db,
                delivery_id,
                sender=lambda _url, _body, _headers: 503,
            )
        assert delivery.status == "failed"
        assert delivery.attempt_count == 5
        assert delivery.failure_code == "http_status"
        failed_version = delivery.version

    stale = client.post(
        f"/api/platform/operations/alerting/deliveries/{delivery_id}/retry",
        json={
            "account_password": "test-only",
            "reason": "Retry after receiver recovery",
            "expected_version": failed_version - 1,
        },
    )
    assert stale.status_code == 409
    retried = client.post(
        f"/api/platform/operations/alerting/deliveries/{delivery_id}/retry",
        json={
            "account_password": "test-only",
            "reason": "Retry after receiver recovery",
            "expected_version": failed_version,
        },
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "pending"
    assert retried.json()["attempt_count"] == 0
    assert retried.json()["idempotency_key"] == delivery.idempotency_key
    with client.app.state.testing_session_local() as db:
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.action == "retry_operations_alert_delivery"
            )
        )
        metadata = json.loads(audit.metadata_json)
        assert metadata["previous_attempt_count"] == 5
        assert metadata["reason"] == "Retry after receiver recovery"


def test_alerting_api_is_platform_only_and_test_queue_is_password_confirmed(
    client,
    configured_alert_delivery,
):
    state = client.get("/api/platform/operations/alerting")
    assert state.status_code == 200
    assert state.json()["configured"] is True
    assert state.json()["destination_host"] == "alerts.example.test"
    assert settings.operations_alert_webhook_url not in state.text
    assert settings.operations_alert_webhook_secret not in state.text

    queued = client.post(
        "/api/platform/operations/alerting/test",
        json={
            "account_password": "test-only",
            "reason": "Validate on-call receiver",
        },
    )
    assert queued.status_code == 200, queued.text
    assert queued.json()["event_type"] == "test"
    assert queued.json()["status"] == "pending"


def test_pinned_sender_rejects_private_dns_results(monkeypatch, configured_alert_delivery):
    monkeypatch.setattr(
        "app.services.operations_alerts.socket.getaddrinfo",
        lambda *_args, **_kwargs: [
            (2, 1, 6, "", ("127.0.0.1", 443))
        ],
    )
    with pytest.raises(RuntimeError, match="blocked_address"):
        _pinned_webhook_sender(
            settings.operations_alert_webhook_url,
            b"{}",
            {"Content-Type": "application/json"},
        )
