from datetime import datetime, timedelta, timezone
import json
import time

from sqlalchemy import select

from app.core.config import settings
from app.models import AuditLog, BillingLifecycleEvent, OrganizationBillingAccount, StripeBillingOperation
from app.services.stripe_billing import StripeAPIResult, stripe_signature


def _configure_stripe(monkeypatch) -> None:
    monkeypatch.setattr(settings, "stripe_billing_enabled", True)
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_openpartsflow_secure_test_key")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_openpartsflow_secure_test_secret")
    monkeypatch.setattr(settings, "stripe_price_starter", "price_starter_server")
    monkeypatch.setattr(settings, "stripe_price_professional", "price_professional_server")
    monkeypatch.setattr(settings, "stripe_price_enterprise", "")
    monkeypatch.setattr(settings, "frontend_public_url", "https://app.openpartsflow.test")


def _stripe_body(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def _stripe_headers(body: bytes, timestamp: int | None = None) -> dict[str, str]:
    signed_at = int(time.time()) if timestamp is None else timestamp
    return {
        "Content-Type": "application/json",
        "Stripe-Signature": stripe_signature(
            body, signed_at, settings.stripe_webhook_secret
        ),
    }


def _post_stripe_event(client, payload: dict, timestamp: int | None = None):
    body = _stripe_body(payload)
    return client.post(
        "/api/billing/webhooks/stripe",
        content=body,
        headers=_stripe_headers(body, timestamp),
    )


def test_checkout_uses_server_contract_and_durable_idempotency(client, monkeypatch):
    _configure_stripe(monkeypatch)
    calls: list[tuple[str, dict[str, str], str]] = []

    def fake_post(path: str, form: dict[str, str], *, idempotency_key: str):
        calls.append((path, form, idempotency_key))
        return StripeAPIResult(
            {
                "id": "cs_test_checkout_1",
                "url": "https://checkout.stripe.com/c/pay/cs_test_checkout_1",
                "expires_at": int(time.time()) + 1800,
            },
            "req_checkout_1",
        )

    monkeypatch.setattr("app.api.billing.stripe_api_post", fake_post)
    request = {
        "target_plan_code": "professional",
        "client_request_id": "checkout-request-001",
    }
    response = client.post("/api/organization/billing/stripe/checkout", json=request)
    assert response.status_code == 200, response.text
    assert response.json()["url"].startswith("https://checkout.stripe.com/")
    assert len(calls) == 1
    path, form, idempotency_key = calls[0]
    assert path == "/v1/checkout/sessions"
    assert form["line_items[0][price]"] == "price_professional_server"
    assert form["success_url"] == "https://app.openpartsflow.test/settings?checkout=success"
    assert form["cancel_url"] == "https://app.openpartsflow.test/settings?checkout=cancelled"
    assert form["client_reference_id"] == "1"
    assert idempotency_key == "opf-checkout-1-checkout-request-001"

    replay = client.post("/api/organization/billing/stripe/checkout", json=request)
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert replay.json()["url"] is None
    assert len(calls) == 1

    collision = client.post(
        "/api/organization/billing/stripe/checkout",
        json={**request, "target_plan_code": "starter"},
    )
    assert collision.status_code == 409
    injected = client.post(
        "/api/organization/billing/stripe/checkout",
        json={**request, "success_url": "https://attacker.example/steal"},
    )
    assert injected.status_code == 422

    with client.app.state.testing_session_local() as db:
        operation = db.scalar(select(StripeBillingOperation))
        assert operation.status == "succeeded"
        assert operation.request_sha256 and len(operation.request_sha256) == 64
        assert operation.external_request_id == "req_checkout_1"
        audit = db.scalar(
            select(AuditLog).where(AuditLog.action == "stripe_checkout_succeeded")
        )
        assert audit is not None
        assert "checkout.stripe.com" not in audit.metadata_json
        assert "sk_test" not in audit.metadata_json


def test_stripe_webhook_signature_binding_lifecycle_and_replay(client, monkeypatch):
    _configure_stripe(monkeypatch)
    client.put(
        "/api/platform/billing/accounts/1",
        json={"expected_version": 0, "provider": "stripe"},
    )
    now = datetime.now(timezone.utc).replace(microsecond=0)
    completed = {
        "id": "evt_checkout_completed_1",
        "type": "checkout.session.completed",
        "created": int(now.timestamp()),
        "data": {
            "object": {
                "id": "cs_test_bound_1",
                "client_reference_id": "1",
                "customer": "cus_tenant_1",
                "subscription": "sub_tenant_1",
                "metadata": {"openpartsflow_organization_id": "1"},
            }
        },
    }
    unsigned = client.post(
        "/api/billing/webhooks/stripe",
        content=_stripe_body(completed),
        headers={"Content-Type": "application/json"},
    )
    assert unsigned.status_code == 401
    expired = _post_stripe_event(
        client,
        completed,
        int(time.time()) - settings.billing_webhook_tolerance_seconds - 5,
    )
    assert expired.status_code == 401
    bound = _post_stripe_event(client, completed)
    assert bound.status_code == 200, bound.text
    assert bound.json()["processing_status"] == "bound"
    rebound = _post_stripe_event(client, completed)
    assert rebound.status_code == 200
    assert rebound.json()["duplicate"] is True
    checkout_collision = json.loads(json.dumps(completed))
    checkout_collision["data"]["object"]["metadata"]["unexpected"] = "changed"
    assert _post_stripe_event(client, checkout_collision).status_code == 409

    activated = {
        "id": "evt_subscription_created_1",
        "type": "customer.subscription.created",
        "created": int(now.timestamp()),
        "data": {
            "object": {
                "id": "sub_tenant_1",
                "customer": "cus_tenant_1",
                "status": "active",
                "cancel_at_period_end": False,
                "items": {
                    "data": [{
                        "current_period_start": int((now - timedelta(minutes=1)).timestamp()),
                        "current_period_end": int((now + timedelta(days=30)).timestamp()),
                        "price": {"id": "price_professional_server"},
                    }]
                },
            }
        },
    }
    applied = _post_stripe_event(client, activated)
    assert applied.status_code == 200, applied.text
    assert applied.json()["subscription_status"] == "active"
    assert applied.json()["plan_code"] == "professional"
    duplicate = _post_stripe_event(client, activated)
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True

    changed = json.loads(json.dumps(activated))
    changed["data"]["object"]["cancel_at_period_end"] = True
    conflict = _post_stripe_event(client, changed)
    assert conflict.status_code == 409
    with client.app.state.testing_session_local() as db:
        events = db.scalars(select(BillingLifecycleEvent)).all()
        assert len(events) == 1
        assert events[0].provider == "stripe"
        assert events[0].external_event_id == "evt_subscription_created_1"


def test_refund_rejects_cross_tenant_payment_and_is_idempotent(client, monkeypatch):
    _configure_stripe(monkeypatch)
    bound = client.put(
        "/api/platform/billing/accounts/1",
        json={
            "expected_version": 0,
            "provider": "stripe",
            "external_customer_id": "cus_tenant_1",
            "external_subscription_id": "sub_tenant_1",
        },
    )
    assert bound.status_code == 200, bound.text
    monkeypatch.setattr(
        "app.api.billing.stripe_api_get",
        lambda path: StripeAPIResult({"id": "pi_cross", "customer": "cus_other"}, "req_get_1"),
    )
    post_calls: list[dict[str, str]] = []

    def fake_post(path: str, form: dict[str, str], *, idempotency_key: str):
        post_calls.append(form)
        return StripeAPIResult({"id": "re_tenant_1"}, "req_refund_1")

    monkeypatch.setattr("app.api.billing.stripe_api_post", fake_post)
    request = {
        "organization_id": 1,
        "payment_intent_id": "pi_payment_1",
        "amount_minor": 1250,
        "reason": "requested_by_customer",
        "business_reason": "Customer approved cancellation before service delivery.",
        "client_request_id": "refund-request-001",
    }
    denied = client.post("/api/platform/billing/stripe/refunds", json=request)
    assert denied.status_code == 403
    assert post_calls == []

    monkeypatch.setattr(
        "app.api.billing.stripe_api_get",
        lambda path: StripeAPIResult({"id": "pi_payment_1", "customer": "cus_tenant_1"}, "req_get_2"),
    )
    refunded = client.post("/api/platform/billing/stripe/refunds", json=request)
    assert refunded.status_code == 200, refunded.text
    assert refunded.json()["external_object_id"] == "re_tenant_1"
    assert post_calls[0]["payment_intent"] == "pi_payment_1"
    assert post_calls[0]["amount"] == "1250"
    replay = client.post("/api/platform/billing/stripe/refunds", json=request)
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert len(post_calls) == 1


def test_stripe_redirect_host_is_rejected(client, monkeypatch):
    _configure_stripe(monkeypatch)
    monkeypatch.setattr(
        "app.api.billing.stripe_api_post",
        lambda *args, **kwargs: StripeAPIResult(
            {"id": "cs_test_bad", "url": "https://attacker.example/checkout"},
            "req_bad_redirect",
        ),
    )
    response = client.post(
        "/api/organization/billing/stripe/checkout",
        json={"target_plan_code": "starter", "client_request_id": "bad-redirect-001"},
    )
    assert response.status_code == 502
    with client.app.state.testing_session_local() as db:
        operation = db.scalar(select(StripeBillingOperation))
        assert operation.status == "failed"
        assert operation.failure_code == "stripe_invalid_redirect"
