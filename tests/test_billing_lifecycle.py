from datetime import datetime, timedelta, timezone
import json
import time

from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.models import (
    AuditLog,
    BillingLifecycleEvent,
    Organization,
    OrganizationBillingAccount,
    SubscriptionNotice,
    User,
    UserRole,
)
from app.services.billing import billing_webhook_signature


def _json_body(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _signed_headers(body: bytes, *, timestamp: int | None = None) -> dict[str, str]:
    signed_at = int(time.time()) if timestamp is None else timestamp
    return {
        "Content-Type": "application/json",
        "X-OpenPartsFlow-Timestamp": str(signed_at),
        "X-OpenPartsFlow-Signature": billing_webhook_signature(
            body,
            signed_at,
            settings.billing_webhook_secret,
        ),
    }


def _post_event(client, payload: dict):
    body = _json_body(payload)
    return client.post(
        "/api/billing/webhooks/generic",
        content=body,
        headers=_signed_headers(body),
    )


def _login(client, email: str, password: str) -> str:
    response = client.post(
        "/api/auth/login",
        data={"username": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_billing_cannot_downgrade_a_residency_pinned_enterprise(client):
    original_secret = settings.billing_webhook_secret
    original_region = settings.deployment_region
    try:
        settings.billing_webhook_secret = (
            "billing-residency-secret-with-at-least-32-characters"
        )
        settings.deployment_region = "us-east-1"
        with client.app.state.testing_session_local() as db:
            organization = db.get(Organization, 1)
            assert organization is not None
            organization.plan_code = "enterprise"
            organization.data_residency_region = "us-east-1"
            organization.data_residency_enforced_at = datetime.utcnow()
            db.commit()

        bound = client.put(
            "/api/platform/billing/accounts/1",
            json={
                "expected_version": 0,
                "provider": "generic",
                "external_customer_id": "customer_residency_1",
                "external_subscription_id": "subscription_residency_1",
            },
        )
        assert bound.status_code == 200, bound.text

        occurred = datetime.now(timezone.utc).replace(microsecond=0)
        downgrade = _post_event(
            client,
            {
                "event_id": "event-residency-downgrade",
                "event_type": "subscription.renewed",
                "occurred_at": occurred.isoformat(),
                "external_customer_id": "customer_residency_1",
                "external_subscription_id": "subscription_residency_1",
                "plan_code": "professional",
                "current_period_start": occurred.isoformat(),
                "current_period_end": (occurred + timedelta(days=30)).isoformat(),
            },
        )
        assert downgrade.status_code == 422
        assert "Clear the organization's data residency" in downgrade.json()["detail"]

        with client.app.state.testing_session_local() as db:
            organization = db.get(Organization, 1)
            assert organization is not None
            assert organization.plan_code == "enterprise"
            assert organization.data_residency_region == "us-east-1"
            assert db.scalar(
                select(BillingLifecycleEvent.id).where(
                    BillingLifecycleEvent.external_event_id
                    == "event-residency-downgrade"
                )
            ) is None
    finally:
        settings.billing_webhook_secret = original_secret
        settings.deployment_region = original_region


def test_signed_billing_events_are_idempotent_ordered_and_audited(client):
    original_secret = settings.billing_webhook_secret
    original_max_bytes = settings.billing_webhook_max_bytes
    try:
        settings.billing_webhook_secret = "billing-test-secret-with-at-least-32-characters"
        settings.billing_webhook_max_bytes = 1024
        oversized = client.post(
            "/api/billing/webhooks/generic",
            content=b"x" * 1025,
            headers={"Content-Type": "application/json"},
        )
        assert oversized.status_code == 413
        settings.billing_webhook_max_bytes = original_max_bytes
        bound = client.put(
            "/api/platform/billing/accounts/1",
            json={
                "expected_version": 0,
                "provider": "generic",
                "external_customer_id": "customer_test_1",
                "external_subscription_id": "subscription_test_1",
            },
        )
        assert bound.status_code == 200, bound.text
        assert bound.json()["provider"] == "generic"

        occurred = datetime.now(timezone.utc).replace(microsecond=0)
        activated_payload = {
            "event_id": "event-activated-1",
            "event_type": "subscription.activated",
            "occurred_at": occurred.isoformat(),
            "external_customer_id": "customer_test_1",
            "external_subscription_id": "subscription_test_1",
            "plan_code": "professional",
            "current_period_start": occurred.isoformat(),
            "current_period_end": (occurred + timedelta(days=30)).isoformat(),
        }
        unsigned = client.post(
            "/api/billing/webhooks/generic",
            content=_json_body(activated_payload),
            headers={"Content-Type": "application/json"},
        )
        assert unsigned.status_code == 401
        activated_body = _json_body(activated_payload)
        expired_timestamp = int(time.time()) - settings.billing_webhook_tolerance_seconds - 10
        expired_signature = client.post(
            "/api/billing/webhooks/generic",
            content=activated_body,
            headers=_signed_headers(activated_body, timestamp=expired_timestamp),
        )
        assert expired_signature.status_code == 401

        unexpected_field_payload = {
            **activated_payload,
            "event_id": "event-with-extra-field",
            "unsupported_field": "must-not-be-retained",
        }
        unexpected_field = _post_event(client, unexpected_field_payload)
        assert unexpected_field.status_code == 422

        future_payload = {
            **activated_payload,
            "event_id": "event-impossibly-future",
            "occurred_at": (occurred + timedelta(hours=1)).isoformat(),
            "current_period_start": (occurred + timedelta(hours=1)).isoformat(),
            "current_period_end": (occurred + timedelta(days=31)).isoformat(),
        }
        future = _post_event(client, future_payload)
        assert future.status_code == 422

        activated = _post_event(client, activated_payload)
        assert activated.status_code == 200, activated.text
        assert activated.json()["processing_status"] == "applied"
        assert activated.json()["duplicate"] is False

        duplicate = _post_event(client, activated_payload)
        assert duplicate.status_code == 200, duplicate.text
        assert duplicate.json()["event_id"] == activated.json()["event_id"]
        assert duplicate.json()["duplicate"] is True

        collision_payload = {
            **activated_payload,
            "event_type": "subscription.renewed",
        }
        collision = _post_event(client, collision_payload)
        assert collision.status_code == 409

        stale_payload = {
            "event_id": "event-stale-failure",
            "event_type": "payment.failed",
            "occurred_at": (occurred - timedelta(minutes=5)).isoformat(),
            "external_customer_id": "customer_test_1",
            "external_subscription_id": "subscription_test_1",
        }
        stale = _post_event(client, stale_payload)
        assert stale.status_code == 200, stale.text
        assert stale.json()["processing_status"] == "ignored_stale"
        assert stale.json()["subscription_status"] == "active"

        failed_at = occurred + timedelta(seconds=1)
        failed_payload = {
            "event_id": "event-payment-failed-1",
            "event_type": "payment.failed",
            "occurred_at": failed_at.isoformat(),
            "external_customer_id": "customer_test_1",
            "external_subscription_id": "subscription_test_1",
            "grace_ends_at": (failed_at + timedelta(days=3)).isoformat(),
        }
        failed = _post_event(client, failed_payload)
        assert failed.status_code == 200, failed.text
        assert failed.json()["subscription_status"] == "past_due"

        renewed_at = occurred + timedelta(seconds=2)
        renewed_payload = {
            "event_id": "event-renewed-1",
            "event_type": "subscription.renewed",
            "occurred_at": renewed_at.isoformat(),
            "external_customer_id": "customer_test_1",
            "external_subscription_id": "subscription_test_1",
            "current_period_start": renewed_at.isoformat(),
            "current_period_end": (renewed_at + timedelta(days=30)).isoformat(),
        }
        renewed = _post_event(client, renewed_payload)
        assert renewed.status_code == 200, renewed.text
        assert renewed.json()["subscription_status"] == "active"

        with client.app.state.testing_session_local() as db:
            organization = db.get(Organization, 1)
            assert organization is not None
            organization.subscription_status = "suspended"
            organization.plan_code = "enterprise"
            db.commit()
        historical_duplicate = _post_event(client, activated_payload)
        assert historical_duplicate.status_code == 200, historical_duplicate.text
        assert historical_duplicate.json()["duplicate"] is True
        assert historical_duplicate.json()["subscription_status"] == "active"
        assert historical_duplicate.json()["plan_code"] == "professional"

        with client.app.state.testing_session_local() as db:
            events = db.scalars(
                select(BillingLifecycleEvent).order_by(BillingLifecycleEvent.id)
            ).all()
            assert len(events) == 4
            assert [row.processing_status for row in events] == [
                "applied",
                "ignored_stale",
                "applied",
                "applied",
            ]
            assert all(len(row.payload_sha256) == 64 for row in events)
            account = db.scalar(select(OrganizationBillingAccount))
            assert account is not None
            assert account.last_event_id == "event-renewed-1"
            assert account.grace_ends_at is None
            notices = db.scalars(select(SubscriptionNotice)).all()
            past_due = next(row for row in notices if row.notice_type == "payment_past_due")
            assert past_due.status == "resolved"
            audits = db.scalars(
                select(AuditLog).where(AuditLog.entity_type == "billing_lifecycle_event")
            ).all()
            assert len(audits) == 4
            assert all("external_customer_id" not in (row.metadata_json or "") for row in audits)
            assert all("external_subscription_id" not in (row.metadata_json or "") for row in audits)
    finally:
        settings.billing_webhook_secret = original_secret
        settings.billing_webhook_max_bytes = original_max_bytes


def test_trial_and_renewal_notices_acknowledge_and_resolve(client):
    now = datetime.utcnow()
    with client.app.state.testing_session_local() as db:
        organization = db.get(Organization, 1)
        assert organization is not None
        organization.subscription_status = "trialing"
        organization.trial_ends_at = now + timedelta(days=3)
        db.commit()

    overview = client.get("/api/organization/billing")
    assert overview.status_code == 200, overview.text
    trial_notice = next(
        row for row in overview.json()["notices"] if row["notice_type"] == "trial_ending"
    )
    assert trial_notice["status"] == "open"

    acknowledged = client.post(
        f"/api/organization/billing/notices/{trial_notice['id']}/acknowledge",
        json={"expected_version": trial_notice["version"]},
    )
    assert acknowledged.status_code == 200, acknowledged.text
    assert acknowledged.json()["status"] == "acknowledged"
    assert acknowledged.json()["version"] == trial_notice["version"] + 1

    stale_acknowledgement = client.post(
        f"/api/organization/billing/notices/{trial_notice['id']}/acknowledge",
        json={"expected_version": trial_notice["version"]},
    )
    assert stale_acknowledgement.status_code == 409

    with client.app.state.testing_session_local() as db:
        organization = db.get(Organization, 1)
        assert organization is not None
        organization.trial_ends_at = now + timedelta(days=30)
        db.commit()
    reconciliation = client.post("/api/platform/billing/reconcile")
    assert reconciliation.status_code == 200, reconciliation.text
    assert reconciliation.json()["organizations_checked"] == 1
    assert reconciliation.json()["notices_resolved"] == 1

    with client.app.state.testing_session_local() as db:
        row = db.get(SubscriptionNotice, trial_notice["id"])
        assert row is not None
        assert row.status == "resolved"
        assert row.resolved_at is not None
        organization = db.get(Organization, 1)
        assert organization is not None
        organization.subscription_status = "active"
        organization.trial_ends_at = None
        db.add(
            OrganizationBillingAccount(
                organization_id=1,
                provider="manual",
                current_period_start=now - timedelta(days=31),
                current_period_end=now - timedelta(days=1),
            )
        )
        db.commit()

    overdue_reconciliation = client.post("/api/platform/billing/reconcile")
    assert overdue_reconciliation.status_code == 200, overdue_reconciliation.text
    with client.app.state.testing_session_local() as db:
        overdue = db.scalar(
            select(SubscriptionNotice).where(
                SubscriptionNotice.notice_type == "renewal_overdue"
            )
        )
        assert overdue is not None
        assert overdue.status == "open"
        assert overdue.severity == "critical"


def test_platform_billing_binding_requires_reauthentication_and_unique_refs(client):
    original_rbac = settings.rbac_enforce
    original_legacy = settings.legacy_header_auth
    try:
        settings.rbac_enforce = False
        platform_user = client.post(
            "/api/users",
            json={
                "name": "Billing Platform Admin",
                "email": "billing-platform@example.test",
                "role": "admin",
                "password": "billing-platform-password",
            },
        )
        assert platform_user.status_code == 200, platform_user.text
        with client.app.state.testing_session_local() as db:
            user = db.get(User, platform_user.json()["id"])
            assert user is not None
            user.is_platform_admin = True
            second = Organization(
                name="Billing Tenant Two",
                slug="billing-tenant-two",
            )
            db.add(second)
            db.flush()
            second_id = second.id
            db.add(
                SubscriptionNotice(
                    organization_id=second_id,
                    notice_type="subscription_suspended",
                    status="open",
                    severity="critical",
                    message="Second tenant billing evidence",
                    effective_at=datetime.utcnow(),
                )
            )
            db.commit()

        settings.rbac_enforce = True
        settings.legacy_header_auth = False
        token = _login(
            client,
            "billing-platform@example.test",
            "billing-platform-password",
        )
        payload = {
            "expected_version": 0,
            "provider": "generic",
            "external_customer_id": "unique-customer-ref",
            "external_subscription_id": "unique-subscription-ref",
        }
        missing_password = client.put(
            "/api/platform/billing/accounts/1",
            headers=_bearer(token),
            json=payload,
        )
        assert missing_password.status_code == 401
        wrong_password = client.put(
            "/api/platform/billing/accounts/1",
            headers=_bearer(token),
            json={**payload, "account_password": "incorrect-password"},
        )
        assert wrong_password.status_code == 401
        configured = client.put(
            "/api/platform/billing/accounts/1",
            headers=_bearer(token),
            json={**payload, "account_password": "billing-platform-password"},
        )
        assert configured.status_code == 200, configured.text

        collision = client.put(
            f"/api/platform/billing/accounts/{second_id}",
            headers=_bearer(token),
            json={**payload, "account_password": "billing-platform-password"},
        )
        assert collision.status_code == 409
        listed = client.get(
            "/api/platform/billing/accounts",
            headers=_bearer(token),
        )
        assert listed.status_code == 200, listed.text
        assert len(listed.json()) == 1
        assert listed.json()[0]["organization_id"] == 1

        tenant_billing = client.get(
            "/api/organization/billing",
            headers=_bearer(token),
        )
        assert tenant_billing.status_code == 200, tenant_billing.text
        assert all(row["organization_id"] == 1 for row in tenant_billing.json()["notices"])
        platform_notices = client.get(
            "/api/platform/billing/notices",
            headers=_bearer(token),
        )
        assert platform_notices.status_code == 200, platform_notices.text
        assert any(row["organization_id"] == second_id for row in platform_notices.json())
    finally:
        settings.rbac_enforce = original_rbac
        settings.legacy_header_auth = original_legacy
