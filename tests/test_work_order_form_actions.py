from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import select

from app.core.config import settings
from app.models import (
    AuditLog,
    Organization,
    User,
    UserRole,
    WorkOrderFormAction,
)


def _create_user(client, name: str, role: str) -> dict:
    response = client.post(
        "/api/users",
        json={
            "name": name,
            "email": f"{name}@form-actions.test",
            "role": role,
            "password": "form-action-password",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_triggered_order(client, ticket: str) -> tuple[dict, dict]:
    template_response = client.post(
        "/api/work-order-form-templates",
        json={
            "name": f"{ticket} action form",
            "fields": [
                {
                    "field_key": "stock_decision",
                    "label": "Stock decision",
                    "field_type": "text",
                    "triggers_notification": True,
                    "affects_inventory": True,
                    "include_in_ai_learning": True,
                    "sort_order": 0,
                },
                {
                    "field_key": "ordinary_note",
                    "label": "Ordinary note",
                    "field_type": "text",
                    "sort_order": 1,
                },
            ],
        },
    )
    assert template_response.status_code == 200, template_response.text
    template = template_response.json()
    order_response = client.post(
        "/api/work-orders",
        json={
            "ticket_number": ticket,
            "form_template_id": template["id"],
        },
    )
    assert order_response.status_code == 200, order_response.text
    return template, order_response.json()


def _trigger(client, work_order_id: int, value: str, expected_version: int = 0):
    return client.patch(
        f"/api/work-orders/{work_order_id}/form",
        json={
            "expected_version": expected_version,
            "values": {
                "stock_decision": value,
                "ordinary_note": "No workflow action",
            },
        },
    )


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


def test_changed_configured_fields_create_durable_idempotent_action_tasks(client):
    _, order = _create_triggered_order(client, "FORM-ACTION-1")
    triggered = _trigger(client, order["id"], "Replace from stock")
    assert triggered.status_code == 200, triggered.text
    assert triggered.json()["form_version"] == 1

    listed = client.get("/api/work-order-form-actions")
    assert listed.status_code == 200, listed.text
    assert len(listed.json()) == 2
    assert {task["action_type"] for task in listed.json()} == {
        "notification",
        "inventory_review",
    }
    assert {task["field_key"] for task in listed.json()} == {"stock_decision"}
    assert {task["triggered_form_version"] for task in listed.json()} == {1}
    assert all(task["status"] == "pending" for task in listed.json())
    assert "value" not in listed.json()[0]

    no_op = _trigger(client, order["id"], "Replace from stock", expected_version=1)
    assert no_op.status_code == 200, no_op.text
    assert no_op.json()["form_version"] == 1
    assert len(client.get("/api/work-order-form-actions").json()) == 2

    changed_again = _trigger(
        client,
        order["id"],
        "Return damaged stock",
        expected_version=1,
    )
    assert changed_again.status_code == 200, changed_again.text
    assert changed_again.json()["form_version"] == 2
    all_tasks = client.get("/api/work-order-form-actions").json()
    assert len(all_tasks) == 4
    assert {task["triggered_form_version"] for task in all_tasks} == {1, 2}

    with client.app.state.testing_session_local() as db:
        audit = db.scalar(
            select(AuditLog)
            .where(AuditLog.action == "work_order_form_actions_created")
            .order_by(AuditLog.id.desc())
        )
        assert audit is not None
        assert "inventory_review" in (audit.metadata_json or "")
        assert "Return damaged stock" not in (audit.metadata_json or "")


def test_action_roles_transitions_versions_and_inventory_resolution_notes(client):
    admin = _create_user(client, "form-action-admin", "admin")
    manager = _create_user(client, "form-action-manager", "manager")
    warehouse = _create_user(client, "form-action-warehouse", "warehouse")
    _, order = _create_triggered_order(client, "FORM-ACTION-ROLES")
    assert _trigger(client, order["id"], "Review stock").status_code == 200
    tasks = client.get("/api/work-order-form-actions").json()
    notification = next(task for task in tasks if task["action_type"] == "notification")
    inventory = next(task for task in tasks if task["action_type"] == "inventory_review")

    with _enforced_rbac():
        admin_headers = {"X-User-Id": str(admin["id"])}
        manager_headers = {"X-User-Id": str(manager["id"])}
        warehouse_headers = {"X-User-Id": str(warehouse["id"])}

        manager_rows = client.get(
            "/api/work-order-form-actions",
            headers=manager_headers,
        )
        assert manager_rows.status_code == 200
        assert len(manager_rows.json()) == 2
        warehouse_rows = client.get(
            "/api/work-order-form-actions",
            headers=warehouse_headers,
        )
        assert warehouse_rows.status_code == 200
        assert [row["action_type"] for row in warehouse_rows.json()] == [
            "inventory_review"
        ]

        manager_inventory = client.patch(
            f"/api/work-order-form-actions/{inventory['id']}",
            headers=manager_headers,
            json={"expected_version": 0, "action": "acknowledge"},
        )
        assert manager_inventory.status_code == 403, manager_inventory.text
        warehouse_notification = client.patch(
            f"/api/work-order-form-actions/{notification['id']}",
            headers=warehouse_headers,
            json={"expected_version": 0, "action": "acknowledge"},
        )
        assert warehouse_notification.status_code == 403, warehouse_notification.text

        acknowledged_notice = client.patch(
            f"/api/work-order-form-actions/{notification['id']}",
            headers=manager_headers,
            json={"expected_version": 0, "action": "acknowledge"},
        )
        assert acknowledged_notice.status_code == 200, acknowledged_notice.text
        assert acknowledged_notice.json()["status"] == "acknowledged"
        assert acknowledged_notice.json()["acknowledged_by"] == manager["id"]

        stale_notice = client.patch(
            f"/api/work-order-form-actions/{notification['id']}",
            headers=manager_headers,
            json={"expected_version": 0, "action": "resolve"},
        )
        assert stale_notice.status_code == 409, stale_notice.text
        resolved_notice = client.patch(
            f"/api/work-order-form-actions/{notification['id']}",
            headers=manager_headers,
            json={
                "expected_version": 1,
                "action": "resolve",
                "resolution_notes": "Dispatch was informed.",
            },
        )
        assert resolved_notice.status_code == 200, resolved_notice.text
        assert resolved_notice.json()["status"] == "resolved"

        missing_inventory_notes = client.patch(
            f"/api/work-order-form-actions/{inventory['id']}",
            headers=warehouse_headers,
            json={"expected_version": 0, "action": "resolve"},
        )
        assert missing_inventory_notes.status_code == 422, missing_inventory_notes.text
        acknowledged_inventory = client.patch(
            f"/api/work-order-form-actions/{inventory['id']}",
            headers=warehouse_headers,
            json={"expected_version": 0, "action": "acknowledge"},
        )
        assert acknowledged_inventory.status_code == 200
        resolved_inventory = client.patch(
            f"/api/work-order-form-actions/{inventory['id']}",
            headers=warehouse_headers,
            json={
                "expected_version": 1,
                "action": "resolve",
                "resolution_notes": "Reviewed; replenishment request opened separately.",
            },
        )
        assert resolved_inventory.status_code == 200, resolved_inventory.text
        assert resolved_inventory.json()["resolved_by"] == warehouse["id"]

        already_resolved = client.patch(
            f"/api/work-order-form-actions/{inventory['id']}",
            headers=admin_headers,
            json={
                "expected_version": 2,
                "action": "resolve",
                "resolution_notes": "Attempt duplicate resolution.",
            },
        )
        assert already_resolved.status_code == 403, already_resolved.text


def test_engineers_see_work_order_action_progress_without_global_or_mutation_access(client):
    engineer = _create_user(client, "form-action-engineer", "engineer")
    _, order = _create_triggered_order(client, "FORM-ACTION-SHARED")
    assert _trigger(client, order["id"], "Notify operations").status_code == 200
    task = client.get("/api/work-order-form-actions").json()[0]

    with client.app.state.testing_session_local() as db:
        second_org = Organization(
            id=2,
            name="Other form-action organization",
            slug="other-form-actions",
        )
        other_manager = User(
            organization_id=2,
            name="Other manager",
            email="other-manager@form-actions.test",
            role=UserRole.MANAGER,
        )
        db.add_all([second_org, other_manager])
        db.commit()
        other_manager_id = other_manager.id

    with _enforced_rbac():
        engineer_headers = {"X-User-Id": str(engineer["id"])}
        other_headers = {"X-User-Id": str(other_manager_id)}

        progress = client.get(
            f"/api/work-orders/{order['id']}/form-actions",
            headers=engineer_headers,
        )
        assert progress.status_code == 200, progress.text
        assert len(progress.json()) == 2
        assert all(row["can_acknowledge"] is False for row in progress.json())
        assert all(row["can_resolve"] is False for row in progress.json())

        engineer_global = client.get(
            "/api/work-order-form-actions",
            headers=engineer_headers,
        )
        assert engineer_global.status_code == 403, engineer_global.text
        engineer_mutation = client.patch(
            f"/api/work-order-form-actions/{task['id']}",
            headers=engineer_headers,
            json={"expected_version": 0, "action": "acknowledge"},
        )
        assert engineer_mutation.status_code == 403, engineer_mutation.text

        other_global = client.get(
            "/api/work-order-form-actions",
            headers=other_headers,
        )
        assert other_global.status_code == 200
        assert other_global.json() == []
        other_work_order = client.get(
            f"/api/work-orders/{order['id']}/form-actions",
            headers=other_headers,
        )
        assert other_work_order.status_code == 404, other_work_order.text
        other_mutation = client.patch(
            f"/api/work-order-form-actions/{task['id']}",
            headers=other_headers,
            json={"expected_version": 0, "action": "acknowledge"},
        )
        assert other_mutation.status_code == 404, other_mutation.text
