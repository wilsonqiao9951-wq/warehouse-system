from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import hmac
import json
from contextlib import contextmanager

from sqlalchemy import select

from app.core.config import settings
from app.models import (
    ExternalSyncLog,
    Organization,
    User,
    UserRole,
    WorkOrderPartMemory,
)
from app.services.integration_delivery import deliver_outbound_event


def _integration(client, *, name: str = "Delivery integration") -> dict:
    response = client.post(
        "/api/integrations",
        json={
            "name": name,
            "provider": "generic",
            "field_mapping": {},
            "webhook_url": "https://events.example.test/openpartsflow",
            "subscribed_events": [
                "work_order.status_changed",
                "work_order.completed",
                "work_order.part_used",
            ],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _external_headers(secret: dict, idempotency_key: str | None = None) -> dict:
    headers = {"X-API-Key": secret["api_key"]}
    if idempotency_key:
        headers["X-Idempotency-Key"] = idempotency_key
    return headers


@contextmanager
def _enforced_rbac():
    original_rbac = settings.rbac_enforce
    original_legacy = settings.legacy_header_auth
    settings.rbac_enforce = True
    settings.legacy_header_auth = True
    try:
        yield
    finally:
        settings.rbac_enforce = original_rbac
        settings.legacy_header_auth = original_legacy


def _external_work_order(client, secret: dict, external_id: str = "delivery-row-1") -> dict:
    response = client.post(
        "/api/external/v1/work-orders",
        headers=_external_headers(secret, f"create-{external_id}"),
        json={
            "external_id": external_id,
            "data": {
                "ticket_number": f"EXT-{external_id}",
                "machine_type": "ACME-9000",
                "job_type": "no-cooling",
                "problem_description": "Unit is warm",
            },
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _stock(client, seed_inventory_ledger) -> tuple[dict, dict]:
    warehouse_response = client.post(
        "/api/warehouses",
        json={
            "code": "MAIN",
            "name": "Main warehouse",
            "warehouse_type": "main",
        },
    )
    assert warehouse_response.status_code == 200, warehouse_response.text
    part_response = client.post(
        "/api/parts",
        json={
            "part_number": "ACME-FILTER",
            "name": "ACME primary filter",
            "machine_type": "ACME-9000",
            "unit": "pcs",
            "safety_stock": 2,
            "min_stock": 2,
        },
    )
    assert part_response.status_code == 200, part_response.text
    warehouse = warehouse_response.json()
    part = part_response.json()
    seed_inventory_ledger(
        part_id=part["id"],
        quantity=12,
        to_warehouse_id=warehouse["id"],
    )
    return warehouse, part


def test_external_inventory_work_order_status_and_recommendation_queries(
    client,
    seed_inventory_ledger,
):
    secret = _integration(client)
    created = _external_work_order(client, secret)
    warehouse, part = _stock(client, seed_inventory_ledger)
    with client.app.state.testing_session_local() as db:
        db.add(
            WorkOrderPartMemory(
                organization_id=1,
                machine_type="ACME-9000",
                job_type="no-cooling",
                part_id=part["id"],
                usage_count=3,
                total_quantity=4,
            )
        )
        db.commit()

    inventory = client.get(
        "/api/external/v1/inventory",
        headers=_external_headers(secret),
        params={"part_number": part["part_number"], "warehouse_code": warehouse["code"]},
    )
    assert inventory.status_code == 200, inventory.text
    assert inventory.json() == [
        {
            "part_number": "ACME-FILTER",
            "part_name": "ACME primary filter",
            "warehouse_code": "MAIN",
            "warehouse_name": "Main warehouse",
            "quantity": 12,
            "available_quantity": 12,
            "unit": "pcs",
            "is_low_stock": False,
        }
    ]
    assert "default_cost" not in inventory.text
    assert "supplier" not in inventory.text

    status = client.get(
        "/api/external/v1/work-orders/delivery-row-1",
        headers=_external_headers(secret),
    )
    assert status.status_code == 200, status.text
    assert status.json()["work_order_id"] == created["work_order_id"]
    assert status.json()["status"] == "open"
    assert status.json()["claimed"] is False

    recommendations = client.get(
        "/api/external/v1/work-orders/delivery-row-1/recommendations",
        headers=_external_headers(secret),
    )
    assert recommendations.status_code == 200, recommendations.text
    assert recommendations.json()[0]["part_number"] == "ACME-FILTER"
    assert recommendations.json()[0]["available_quantity"] == 12
    assert "default_cost" not in recommendations.text

    unknown = client.get(
        "/api/external/v1/work-orders/not-linked",
        headers=_external_headers(secret),
    )
    assert unknown.status_code == 404


def test_business_changes_enqueue_status_completion_and_part_usage_events(
    client,
    seed_inventory_ledger,
):
    secret = _integration(client)
    created = _external_work_order(client, secret)
    warehouse, part = _stock(client, seed_inventory_ledger)
    work_order_id = created["work_order_id"]

    started = client.post(f"/api/work-orders/{work_order_id}/start", json={})
    assert started.status_code == 200, started.text
    used = client.post(
        f"/api/work-orders/{work_order_id}/use-part",
        json={
            "work_order_id": work_order_id,
            "part_id": part["id"],
            "warehouse_id": warehouse["id"],
            "quantity": 2,
        },
    )
    assert used.status_code == 200, used.text
    completed = client.post(
        f"/api/work-orders/{work_order_id}/complete",
        json={"repair_result": "Filter replaced", "first_time_fix": True},
    )
    assert completed.status_code == 200, completed.text

    with client.app.state.testing_session_local() as db:
        rows = db.scalars(
            select(ExternalSyncLog)
            .where(ExternalSyncLog.direction == "outbound")
            .order_by(ExternalSyncLog.id)
        ).all()
        assert [row.event_type for row in rows] == [
            "work_order.status_changed",
            "work_order.part_used",
            "work_order.status_changed",
            "work_order.completed",
        ]
        assert all(row.status == "pending" for row in rows)
        assert all(row.attempt_count == 0 for row in rows)
        part_payload = json.loads(rows[1].payload_json)
        assert part_payload["external_id"] == "delivery-row-1"
        assert part_payload["data"]["part_number"] == "ACME-FILTER"
        assert part_payload["data"]["quantity"] == 2
        completion_payload = json.loads(rows[-1].payload_json)
        assert completion_payload["data"]["completed_by_id"] is None
        assert completion_payload["work_order"]["status"] == "COMPLETED"


def test_signed_delivery_success_and_failure_retry_lifecycle(
    client,
    seed_inventory_ledger,
):
    secret = _integration(client)
    created = _external_work_order(client, secret)
    client.post(f"/api/work-orders/{created['work_order_id']}/start", json={})
    captured: dict = {}

    def success_sender(url: str, body: bytes, headers: dict[str, str]):
        captured.update({"url": url, "body": body, "headers": headers})
        return 204, ""

    with client.app.state.testing_session_local() as db:
        db.info["organization_id"] = 1
        log = db.scalar(
            select(ExternalSyncLog).where(
                ExternalSyncLog.direction == "outbound",
                ExternalSyncLog.status == "pending",
            )
        )
        delivered = deliver_outbound_event(db, log.id, sender=success_sender)
        assert delivered.status == "processed"
        assert delivered.attempt_count == 1
        assert delivered.response_status_code == 204

    timestamp = captured["headers"]["X-OpenPartsFlow-Timestamp"]
    signing_key = sha256(secret["api_key"].encode("utf-8")).digest()
    expected = hmac.new(
        signing_key,
        timestamp.encode("utf-8") + b"." + captured["body"],
        sha256,
    ).hexdigest()
    assert captured["headers"]["X-OpenPartsFlow-Signature"] == f"sha256={expected}"
    assert captured["headers"]["X-OpenPartsFlow-Event"] == "work_order.status_changed"
    assert captured["headers"]["Idempotency-Key"].startswith("work-order:")
    assert captured["url"].startswith("https://")

    client.post(f"/api/work-orders/{created['work_order_id']}/pause", json={})

    def failing_sender(_url: str, _body: bytes, _headers: dict[str, str]):
        return 503, "temporarily unavailable"

    with client.app.state.testing_session_local() as db:
        db.info["organization_id"] = 1
        failed_log = db.scalar(
            select(ExternalSyncLog).where(
                ExternalSyncLog.direction == "outbound",
                ExternalSyncLog.status == "pending",
            )
        )
        for attempt in range(1, 6):
            failed_log.status = "pending"
            failed_log.next_retry_at = datetime.utcnow()
            db.commit()
            failed_log = deliver_outbound_event(
                db,
                failed_log.id,
                sender=failing_sender,
            )
            assert failed_log.attempt_count == attempt
        assert failed_log.status == "failed"
        assert failed_log.next_retry_at is None
        assert failed_log.response_status_code == 503
        failed_log_id = failed_log.id

    retried = client.post(
        f"/api/integrations/{secret['integration']['id']}/sync-logs/{failed_log_id}/retry",
        json={},
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "pending"
    assert retried.json()["attempt_count"] == 5
    assert retried.json()["next_retry_at"] is not None
    with client.app.state.testing_session_local() as db:
        db.info["organization_id"] = 1
        next_cycle = deliver_outbound_event(
            db,
            failed_log_id,
            sender=failing_sender,
        )
        assert next_cycle.status == "pending"
        assert next_cycle.attempt_count == 6
        retry_delay = (next_cycle.next_retry_at - datetime.utcnow()).total_seconds()
        assert 45 <= retry_delay <= 65


def test_webhook_configuration_rejects_unsafe_targets_and_requires_url(client):
    missing_url = client.post(
        "/api/integrations",
        json={
            "name": "Missing webhook URL",
            "provider": "generic",
            "subscribed_events": ["work_order.completed"],
        },
    )
    assert missing_url.status_code == 422

    local_target = client.post(
        "/api/integrations",
        json={
            "name": "Unsafe local target",
            "provider": "generic",
            "webhook_url": "https://127.0.0.1/internal",
            "subscribed_events": ["work_order.completed"],
        },
    )
    assert local_target.status_code == 422
    assert "private or reserved" in local_target.text

    insecure = client.post(
        "/api/integrations",
        json={
            "name": "Insecure target",
            "provider": "generic",
            "webhook_url": "http://events.example.com/callback",
            "subscribed_events": ["work_order.completed"],
        },
    )
    assert insecure.status_code == 422
    assert "HTTPS" in insecure.text


def test_external_inventory_reads_are_tenant_isolated(client, seed_inventory_ledger):
    org_one_secret = _integration(client, name="Tenant one delivery")
    warehouse_one, part_one = _stock(client, seed_inventory_ledger)

    with client.app.state.testing_session_local() as db:
        other_org = Organization(name="Delivery tenant two", slug="delivery-tenant-two")
        db.add(other_org)
        db.flush()
        other_admin = User(
            organization_id=other_org.id,
            name="delivery-tenant-two-admin",
            email="delivery-tenant-two-admin@example.test",
            role=UserRole.ADMIN,
        )
        db.add(other_admin)
        db.commit()
        other_org_id = other_org.id
        other_admin_id = other_admin.id

    actor_headers = {"X-User-Id": str(other_admin_id)}
    with _enforced_rbac():
        secret_response = client.post(
            "/api/integrations",
            headers=actor_headers,
            json={
                "name": "Tenant two delivery",
                "provider": "generic",
                "field_mapping": {},
            },
        )
        assert secret_response.status_code == 200, secret_response.text
        org_two_secret = secret_response.json()
        warehouse_response = client.post(
            "/api/warehouses",
            headers=actor_headers,
            json={
                "code": "MAIN",
                "name": "Tenant two main",
                "warehouse_type": "main",
            },
        )
        assert warehouse_response.status_code == 200, warehouse_response.text
        part_response = client.post(
            "/api/parts",
            headers=actor_headers,
            json={
                "part_number": part_one["part_number"],
                "name": "Tenant two private filter",
                "unit": "pcs",
            },
        )
        assert part_response.status_code == 200, part_response.text

    warehouse_two = warehouse_response.json()
    part_two = part_response.json()
    seed_inventory_ledger(
        organization_id=other_org_id,
        part_id=part_two["id"],
        quantity=9,
        to_warehouse_id=warehouse_two["id"],
    )

    org_one_rows = client.get(
        "/api/external/v1/inventory",
        headers=_external_headers(org_one_secret),
        params={
            "part_number": part_one["part_number"],
            "warehouse_code": warehouse_one["code"],
        },
    )
    org_two_rows = client.get(
        "/api/external/v1/inventory",
        headers=_external_headers(org_two_secret),
        params={
            "part_number": part_two["part_number"],
            "warehouse_code": warehouse_two["code"],
        },
    )
    assert org_one_rows.status_code == 200, org_one_rows.text
    assert org_two_rows.status_code == 200, org_two_rows.text
    assert org_one_rows.json()[0]["part_name"] == "ACME primary filter"
    assert org_one_rows.json()[0]["quantity"] == 12
    assert org_two_rows.json()[0]["part_name"] == "Tenant two private filter"
    assert org_two_rows.json()[0]["quantity"] == 9
