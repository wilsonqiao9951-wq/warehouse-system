from __future__ import annotations

from contextlib import contextmanager

from app.core.config import settings
from app.models import AuditLog, Organization, User, UserRole


PASSWORD = "offline-conflict-password"


def _create_user(client, name: str, role: str) -> dict:
    response = client.post(
        "/api/users",
        json={
            "name": name,
            "email": f"{name}@offline-conflicts.test",
            "role": role,
            "password": PASSWORD,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _login(
    client,
    user: dict,
    *,
    device_id: str | None = None,
    device_token: str | None = None,
) -> dict[str, str]:
    headers = {}
    if device_id and device_token:
        headers = {
            "X-Device-Id": device_id,
            "X-Device-Token": device_token,
            "X-Device-Name": device_id,
        }
    response = client.post(
        "/api/auth/login",
        data={"username": user["email"], "password": PASSWORD},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    result = {"Authorization": f"Bearer {response.json()['access_token']}"}
    if device_token:
        result["X-Device-Token"] = device_token
    return result


def _create_order_with_form(client, ticket: str) -> dict:
    template = client.post(
        "/api/work-order-form-templates",
        json={
            "name": f"{ticket} form",
            "fields": [
                {
                    "field_key": "reading",
                    "label": "Reading",
                    "field_type": "number",
                    "triggers_notification": True,
                    "sort_order": 0,
                },
                {
                    "field_key": "comment",
                    "label": "Comment",
                    "field_type": "text",
                    "sort_order": 1,
                },
            ],
        },
    )
    assert template.status_code == 200, template.text
    order = client.post(
        "/api/work-orders",
        json={
            "ticket_number": ticket,
            "form_template_id": template.json()["id"],
        },
    )
    assert order.status_code == 200, order.text
    return order.json()


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


def _claim(client, order_id: int, engineer_headers: dict[str, str]) -> dict[str, str]:
    claimed = client.post(
        f"/api/work-orders/{order_id}/claim",
        headers=engineer_headers,
    )
    assert claimed.status_code == 200, claimed.text
    return {
        **engineer_headers,
        "X-Claim-Version": str(claimed.json()["claim_version"]),
    }


def test_owner_registers_idempotent_conflict_and_admin_applies_local_values(client):
    admin = _create_user(client, "conflict-admin", "admin")
    engineer = _create_user(client, "conflict-owner", "engineer")
    manager = _create_user(client, "conflict-manager", "manager")
    other_engineer = _create_user(client, "conflict-other", "engineer")
    order = _create_order_with_form(client, "OFFLINE-CONFLICT-1")

    with _enforced_rbac():
        admin_headers = _login(client, admin)
        manager_headers = _login(client, manager)
        owner_headers = _login(
            client,
            engineer,
            device_id="conflict-owner-phone",
            device_token="a" * 64,
        )
        other_headers = _login(
            client,
            other_engineer,
            device_id="conflict-other-phone",
            device_token="b" * 64,
        )
        owner_write_headers = _claim(client, order["id"], owner_headers)
        claim_version = int(owner_write_headers["X-Claim-Version"])
        assert client.get(
            f"/api/work-orders/{order['id']}",
            headers=owner_headers,
        ).status_code == 200
        shared_read = client.get(
            f"/api/work-orders/{order['id']}",
            headers=other_headers,
        )
        assert shared_read.status_code == 200
        assert shared_read.json()["can_edit"] is False

        server_save = client.patch(
            f"/api/work-orders/{order['id']}/form",
            headers=owner_write_headers,
            json={
                "expected_version": 0,
                "values": {"reading": 10, "comment": "server"},
            },
        )
        assert server_save.status_code == 200, server_save.text

        payload = {
            "work_order_id": order["id"],
            "client_queue_id": "queue-conflict-0001",
            "claim_version": claim_version,
            "base_form_version": 0,
            "local_values": {"reading": 20, "comment": "offline"},
        }
        created = client.post(
            "/api/work-order-form-conflicts",
            headers=owner_write_headers,
            json=payload,
        )
        assert created.status_code == 200, created.text
        assert created.json()["status"] == "pending"

        replay = client.post(
            "/api/work-order-form-conflicts",
            headers=owner_write_headers,
            json=payload,
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["id"] == created.json()["id"]
        owner_status = client.get(
            f"/api/work-order-form-conflicts/{created.json()['id']}/status",
            headers=owner_headers,
        )
        assert owner_status.status_code == 200, owner_status.text
        assert owner_status.json()["status"] == "pending"
        assert client.get(
            f"/api/work-order-form-conflicts/{created.json()['id']}/status",
            headers=other_headers,
        ).status_code == 403

        changed_reuse = client.post(
            "/api/work-order-form-conflicts",
            headers=owner_write_headers,
            json={**payload, "local_values": {"reading": 99}},
        )
        assert changed_reuse.status_code == 409, changed_reuse.text

        assert client.get(
            "/api/work-order-form-conflicts",
            headers=manager_headers,
        ).status_code == 403
        assert client.get(
            "/api/work-order-form-conflicts",
            headers=other_headers,
        ).status_code == 403
        with client.app.state.testing_session_local() as db:
            other_org = Organization(
                id=2,
                name="Other conflict organization",
                slug="other-conflicts",
            )
            other_admin = User(
                organization_id=2,
                name="Other conflict administrator",
                email="other-admin@offline-conflicts.test",
                role=UserRole.ADMIN,
            )
            db.add_all([other_org, other_admin])
            db.commit()
            other_admin_id = other_admin.id
        cross_tenant_headers = {"X-User-Id": str(other_admin_id)}
        cross_tenant_list = client.get(
            "/api/work-order-form-conflicts",
            headers=cross_tenant_headers,
        )
        assert cross_tenant_list.status_code == 200
        assert cross_tenant_list.json() == []
        assert client.get(
            f"/api/work-order-form-conflicts/{created.json()['id']}/status",
            headers=cross_tenant_headers,
        ).status_code == 404
        assert client.get(
            f"/api/work-orders/{order['id']}",
            headers=cross_tenant_headers,
        ).status_code == 404

        listed = client.get(
            "/api/work-order-form-conflicts",
            headers=admin_headers,
        )
        assert listed.status_code == 200, listed.text
        conflict = listed.json()[0]
        assert conflict["local_values"] == payload["local_values"]
        assert conflict["server_values"] == {
            "reading": 10,
            "comment": "server",
        }
        assert conflict["current_server_form_version"] == 1
        assert conflict["created_by_name"] == engineer["name"]
        assert conflict["created_device_name"] == "conflict-owner-phone"

        resolved = client.patch(
            f"/api/work-order-form-conflicts/{conflict['id']}",
            headers=admin_headers,
            json={
                "expected_version": conflict["version"],
                "expected_server_form_version": conflict["current_server_form_version"],
                "action": "apply_local",
                "resolution_notes": "Verified field notes with the engineer.",
            },
        )
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["status"] == "applied_local"
        assert resolved.json()["resolved_values"] == payload["local_values"]
        assert resolved.json()["resolved_server_form_version"] == 2
        resolved_owner_status = client.get(
            f"/api/work-order-form-conflicts/{conflict['id']}/status",
            headers=owner_headers,
        )
        assert resolved_owner_status.status_code == 200
        assert resolved_owner_status.json()["status"] == "applied_local"

        form = client.get(
            f"/api/work-orders/{order['id']}/form",
            headers=admin_headers,
        )
        assert form.status_code == 200, form.text
        assert form.json()["values"] == payload["local_values"]
        assert form.json()["form_version"] == 2

        action_tasks = client.get(
            f"/api/work-orders/{order['id']}/form-actions",
            headers=admin_headers,
        )
        assert action_tasks.status_code == 200, action_tasks.text
        assert len(action_tasks.json()) == 2
        assert {task["triggered_form_version"] for task in action_tasks.json()} == {1, 2}

        repeated_resolution = client.patch(
            f"/api/work-order-form-conflicts/{conflict['id']}",
            headers=admin_headers,
            json={
                "expected_version": conflict["version"],
                "expected_server_form_version": 2,
                "action": "keep_server",
                "resolution_notes": "Duplicate attempt.",
            },
        )
        assert repeated_resolution.status_code == 409

    with client.app.state.testing_session_local() as db:
        actions = {
            row.action
            for row in db.query(AuditLog).filter(
                AuditLog.entity_type == "work_order_form_conflict"
            )
        }
        assert "create_work_order_form_conflict" in actions
        assert "resolve_work_order_form_conflict" in actions


def test_admin_refreshes_changed_server_and_merges_selected_values(client):
    admin = _create_user(client, "merge-admin", "admin")
    engineer = _create_user(client, "merge-owner", "engineer")
    order = _create_order_with_form(client, "OFFLINE-CONFLICT-2")

    with _enforced_rbac():
        admin_headers = _login(client, admin)
        owner_headers = _login(
            client,
            engineer,
            device_id="conflict-merge-phone",
            device_token="c" * 64,
        )
        owner_write_headers = _claim(client, order["id"], owner_headers)
        claim_version = int(owner_write_headers["X-Claim-Version"])
        first = client.patch(
            f"/api/work-orders/{order['id']}/form",
            headers=owner_write_headers,
            json={
                "expected_version": 0,
                "values": {"reading": 11, "comment": "server-one"},
            },
        )
        assert first.status_code == 200, first.text
        conflict_receipt = client.post(
            "/api/work-order-form-conflicts",
            headers=owner_write_headers,
            json={
                "work_order_id": order["id"],
                "client_queue_id": "queue-conflict-0002",
                "claim_version": claim_version,
                "base_form_version": 0,
                "local_values": {"reading": 22, "comment": "offline-two"},
            },
        )
        assert conflict_receipt.status_code == 200, conflict_receipt.text

        second = client.patch(
            f"/api/work-orders/{order['id']}/form",
            headers=admin_headers,
            json={
                "expected_version": 1,
                "values": {"comment": "server-two"},
            },
        )
        assert second.status_code == 200, second.text

        conflict = client.get(
            "/api/work-order-form-conflicts",
            headers=admin_headers,
        ).json()[0]
        assert conflict["server_form_version"] == 1
        assert conflict["current_server_form_version"] == 2
        assert conflict["current_server_values"]["comment"] == "server-two"

        stale_resolution = client.patch(
            f"/api/work-order-form-conflicts/{conflict['id']}",
            headers=admin_headers,
            json={
                "expected_version": conflict["version"],
                "expected_server_form_version": 1,
                "action": "merge",
                "values": {"reading": 22},
                "resolution_notes": "Use the field reading only.",
            },
        )
        assert stale_resolution.status_code == 409, stale_resolution.text

        merged = client.patch(
            f"/api/work-order-form-conflicts/{conflict['id']}",
            headers=admin_headers,
            json={
                "expected_version": conflict["version"],
                "expected_server_form_version": 2,
                "action": "merge",
                "values": {"reading": 22},
                "resolution_notes": "Keep the current server comment and use the field reading.",
            },
        )
        assert merged.status_code == 200, merged.text
        assert merged.json()["status"] == "merged"
        assert merged.json()["current_server_values"] == {
            "reading": 22,
            "comment": "server-two",
        }
        assert merged.json()["resolved_server_form_version"] == 3
