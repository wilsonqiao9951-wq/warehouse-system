from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import select

from app.core.config import settings
from app.models import (
    AuditLog,
    ExternalIntegration,
    ExternalSyncLog,
    ExternalWorkOrderLink,
    Organization,
    User,
    UserRole,
    WorkOrder,
)


def _create_user(client, name: str, role: str) -> dict:
    response = client.post(
        "/api/users",
        json={
            "name": name,
            "email": f"{name}@external-integration.test",
            "role": role,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_integration(
    client,
    *,
    name: str = "AppSheet field service",
    headers: dict[str, str] | None = None,
    mapping: dict[str, str] | None = None,
) -> dict:
    response = client.post(
        "/api/integrations",
        headers=headers,
        json={
            "name": name,
            "provider": "appsheet",
            "field_mapping": mapping
            or {
                "ticket_number": "WO ID",
                "outlet_name": "Site",
                "problem_description": "Issue",
                "machine_type": "Model",
            },
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _webhook_headers(api_key: str, idempotency_key: str) -> dict[str, str]:
    return {
        "X-API-Key": api_key,
        "X-Idempotency-Key": idempotency_key,
    }


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


def test_api_key_mapping_idempotent_work_order_upsert_and_sync_log(client):
    secret = _create_integration(client)
    integration = secret["integration"]
    api_key = secret["api_key"]
    assert api_key.startswith(f"opf_{integration['key_prefix']}_")
    assert integration["masked_api_key"].endswith("_...")
    assert "api_key_hash" not in integration

    payload = {
        "external_id": "appsheet-row-100",
        "data": {
            "WO ID": "APP-100",
            "Site": "Downtown Market",
            "Issue": "Cabinet is warm",
            "Model": "ACME-9000",
            "Ignored AppSheet Column": "remains external",
        },
    }
    created = client.post(
        "/api/external/v1/work-orders",
        headers=_webhook_headers(api_key, "appsheet-create-100"),
        json=payload,
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["result"] == "created"
    assert body["replayed"] is False
    assert body["ticket_number"] == "APP-100"
    assert {
        "ticket_number",
        "wo_number",
        "outlet_name",
        "store_name",
        "description",
        "problem_description",
        "machine_type",
        "status",
    }.issubset(body["changed_fields"])

    replay = client.post(
        "/api/external/v1/work-orders",
        headers=_webhook_headers(api_key, "appsheet-create-100"),
        json=payload,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["replayed"] is True
    assert replay.json()["work_order_id"] == body["work_order_id"]
    changed_replay = client.post(
        "/api/external/v1/work-orders",
        headers=_webhook_headers(api_key, "appsheet-create-100"),
        json={
            **payload,
            "data": {**payload["data"], "Issue": "Different request body"},
        },
    )
    assert changed_replay.status_code == 409
    assert "different data" in changed_replay.text

    updated = client.post(
        "/api/external/v1/work-orders",
        headers=_webhook_headers(api_key, "appsheet-update-100"),
        json={
            "external_id": "appsheet-row-100",
            "data": {
                "WO ID": "APP-100",
                "Site": "Downtown Market",
                "Issue": "Cabinet is warm and fan is noisy",
                "Model": "ACME-9000",
            },
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["result"] == "updated"
    assert updated.json()["changed_fields"] == [
        "description",
        "problem_description",
    ]

    integrations = client.get("/api/integrations")
    assert integrations.status_code == 200
    assert integrations.json()[0]["id"] == integration["id"]
    assert "api_key" not in integrations.json()[0]
    assert "api_key_hash" not in integrations.json()[0]
    logs = client.get(f"/api/integrations/{integration['id']}/sync-logs")
    assert logs.status_code == 200, logs.text
    assert [row["idempotency_key"] for row in logs.json()] == [
        "appsheet-update-100",
        "appsheet-create-100",
    ]
    assert all(row["status"] == "processed" for row in logs.json())
    assert logs.json()[1]["attempt_count"] == 1

    with client.app.state.testing_session_local() as db:
        stored_integration = db.get(ExternalIntegration, integration["id"])
        assert stored_integration.api_key_hash != api_key
        assert api_key not in stored_integration.field_mapping_json
        work_orders = db.scalars(select(WorkOrder)).all()
        links = db.scalars(select(ExternalWorkOrderLink)).all()
        assert len(work_orders) == 1
        assert len(links) == 1
        assert work_orders[0].outlet_name == "Downtown Market"
        assert work_orders[0].problem_description == "Cabinet is warm and fan is noisy"
        assert links[0].external_id == "appsheet-row-100"
        actions = {row.action for row in db.scalars(select(AuditLog)).all()}
        assert {
            "create_external_integration",
            "external_work_order_created",
            "external_work_order_updated",
        }.issubset(actions)


def test_webhook_blocks_claimed_job_and_retries_same_failed_idempotency_key(client):
    secret = _create_integration(client, name="Retry integration")
    api_key = secret["api_key"]
    created = client.post(
        "/api/external/v1/work-orders",
        headers=_webhook_headers(api_key, "retry-create-1"),
        json={
            "external_id": "retry-row-1",
            "data": {"WO ID": "RETRY-1", "Issue": "Original problem"},
        },
    )
    assert created.status_code == 200, created.text
    work_order_id = created.json()["work_order_id"]
    engineer = _create_user(client, "external-claim-owner", "engineer")
    with client.app.state.testing_session_local() as db:
        work_order = db.get(WorkOrder, work_order_id)
        work_order.claimed_by_id = engineer["id"]
        work_order.assigned_user_id = engineer["id"]
        work_order.engineer_id = engineer["id"]
        work_order.claim_version = 1
        db.commit()

    update_payload = {
        "external_id": "retry-row-1",
        "data": {"WO ID": "RETRY-1", "Issue": "Updated after dispatch"},
    }
    blocked = client.post(
        "/api/external/v1/work-orders",
        headers=_webhook_headers(api_key, "retry-update-1"),
        json=update_payload,
    )
    assert blocked.status_code == 409
    assert "claimed or frozen" in blocked.text

    with client.app.state.testing_session_local() as db:
        failed = db.scalar(
            select(ExternalSyncLog).where(
                ExternalSyncLog.idempotency_key == "retry-update-1"
            )
        )
        assert failed.status == "failed"
        assert failed.attempt_count == 1
        work_order = db.get(WorkOrder, work_order_id)
        work_order.claimed_by_id = None
        work_order.assigned_user_id = None
        work_order.engineer_id = None
        work_order.claim_version += 1
        db.commit()

    retried = client.post(
        "/api/external/v1/work-orders",
        headers=_webhook_headers(api_key, "retry-update-1"),
        json=update_payload,
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["result"] == "updated"
    assert retried.json()["replayed"] is False

    with client.app.state.testing_session_local() as db:
        completed_retry = db.scalar(
            select(ExternalSyncLog).where(
                ExternalSyncLog.idempotency_key == "retry-update-1"
            )
        )
        assert completed_retry.status == "processed"
        assert completed_retry.attempt_count == 2
        assert db.get(WorkOrder, work_order_id).problem_description == (
            "Updated after dispatch"
        )


def test_integration_roles_key_rotation_mapping_validation_and_deactivation(client):
    admin = _create_user(client, "external-admin", "admin")
    manager = _create_user(client, "external-manager", "manager")
    with _enforced_rbac():
        manager_denied = client.post(
            "/api/integrations",
            headers={"X-User-Id": str(manager["id"])},
            json={"name": "Manager cannot create", "provider": "generic"},
        )
        assert manager_denied.status_code == 403

        invalid_mapping = client.post(
            "/api/integrations",
            headers={"X-User-Id": str(admin["id"])},
            json={
                "name": "Unsafe mapping",
                "provider": "generic",
                "field_mapping": {"completed_by_id": "Technician"},
            },
        )
        assert invalid_mapping.status_code == 422

        secret = _create_integration(
            client,
            name="Rotating AppSheet",
            headers={"X-User-Id": str(admin["id"])},
        )
        integration = secret["integration"]
        old_key = secret["api_key"]
        manager_list = client.get(
            "/api/integrations",
            headers={"X-User-Id": str(manager["id"])},
        )
        assert manager_list.status_code == 200
        assert manager_list.json()[0]["id"] == integration["id"]

        stale_rotate = client.post(
            f"/api/integrations/{integration['id']}/rotate-key",
            headers={"X-User-Id": str(admin["id"])},
            json={"expected_version": integration["version"] + 1},
        )
        assert stale_rotate.status_code == 409
        rotated = client.post(
            f"/api/integrations/{integration['id']}/rotate-key",
            headers={"X-User-Id": str(admin["id"])},
            json={"expected_version": integration["version"]},
        )
        assert rotated.status_code == 200, rotated.text
        new_key = rotated.json()["api_key"]
        integration = rotated.json()["integration"]
        assert new_key != old_key

        old_denied = client.post(
            "/api/external/v1/work-orders",
            headers=_webhook_headers(old_key, "old-key-request"),
            json={"external_id": "old-key", "data": {}},
        )
        assert old_denied.status_code == 401
        new_accepted = client.post(
            "/api/external/v1/work-orders",
            headers=_webhook_headers(new_key, "new-key-request"),
            json={"external_id": "new-key", "data": {}},
        )
        assert new_accepted.status_code == 200, new_accepted.text

        deactivated = client.patch(
            f"/api/integrations/{integration['id']}",
            headers={"X-User-Id": str(admin["id"])},
            json={
                "expected_version": integration["version"],
                "is_active": False,
            },
        )
        assert deactivated.status_code == 200, deactivated.text
        inactive_denied = client.post(
            "/api/external/v1/work-orders",
            headers=_webhook_headers(new_key, "inactive-key-request"),
            json={"external_id": "inactive-key", "data": {}},
        )
        assert inactive_denied.status_code == 401


def test_external_integrations_and_generated_work_orders_are_tenant_scoped(client):
    org_one_admin = _create_user(client, "external-org-one", "admin")
    with client.app.state.testing_session_local() as db:
        other_org = Organization(
            name="External Tenant Two",
            slug="external-tenant-two",
        )
        db.add(other_org)
        db.flush()
        other_admin = User(
            organization_id=other_org.id,
            name="external-org-two",
            email="external-org-two@external-integration.test",
            role=UserRole.ADMIN,
        )
        db.add(other_admin)
        db.commit()
        other_admin_id = other_admin.id

    with _enforced_rbac():
        org_one_secret = _create_integration(
            client,
            name="Org one AppSheet",
            headers={"X-User-Id": str(org_one_admin["id"])},
            mapping={},
        )
        org_two_secret = _create_integration(
            client,
            name="Org two AppSheet",
            headers={"X-User-Id": str(other_admin_id)},
            mapping={},
        )
        org_one_created = client.post(
            "/api/external/v1/work-orders",
            headers=_webhook_headers(
                org_one_secret["api_key"],
                "tenant-one-create",
            ),
            json={"external_id": "same-external-id", "data": {}},
        )
        org_two_created = client.post(
            "/api/external/v1/work-orders",
            headers=_webhook_headers(
                org_two_secret["api_key"],
                "tenant-two-create",
            ),
            json={"external_id": "same-external-id", "data": {}},
        )
        assert org_one_created.status_code == 200, org_one_created.text
        assert org_two_created.status_code == 200, org_two_created.text
        assert org_one_created.json()["ticket_number"] != (
            org_two_created.json()["ticket_number"]
        )

        org_one_list = client.get(
            "/api/integrations",
            headers={"X-User-Id": str(org_one_admin["id"])},
        )
        assert [row["name"] for row in org_one_list.json()] == ["Org one AppSheet"]
        hidden_logs = client.get(
            f"/api/integrations/{org_two_secret['integration']['id']}/sync-logs",
            headers={"X-User-Id": str(org_one_admin["id"])},
        )
        assert hidden_logs.status_code == 404

    with client.app.state.testing_session_local() as db:
        rows = db.scalars(select(WorkOrder).order_by(WorkOrder.organization_id)).all()
        assert [row.organization_id for row in rows] == [1, 2]
