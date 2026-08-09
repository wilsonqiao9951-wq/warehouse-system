from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta

from sqlalchemy import func, select

from app.core.config import settings
from app.core.security import hash_password
from app.models import (
    AuditLog,
    ExternalWorkOrderLink,
    IntegrationParallelReconciliation,
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


PASSWORD = "parallel-reconciliation-admin-password"


def _create_user(client, name: str, role: str) -> dict:
    response = client.post(
        "/api/users",
        json={
            "name": name,
            "email": f"{name}@parallel-reconciliation.test",
            "role": role,
            "password": PASSWORD,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _login_headers(client, email: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        data={"username": email, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


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


def _ready_integration(client, *, headers: dict[str, str] | None = None, name: str = "Pilot AppSheet"):
    created = client.post(
        "/api/integrations",
        headers=headers,
        json={
            "name": name,
            "provider": "appsheet",
            "field_mapping": {"ticket_number": "WO ID"},
            "webhook_url": "https://events.example.test/openpartsflow",
            "subscribed_events": [
                "work_order.status_changed",
                "work_order.completed",
                "work_order.part_used",
            ],
        },
    )
    assert created.status_code == 200, created.text
    integration = created.json()["integration"]
    endpoint = f"/api/integrations/{integration['id']}/parity-contract"
    template = client.get(endpoint, headers=headers)
    assert template.status_code == 200, template.text
    contract = template.json()
    payload = {
        "expected_version": contract["version"],
        "source_revision": "AppSheet pilot export 2026-08-08",
        "required_capabilities": deepcopy(contract["required_capabilities"]),
        "tables": deepcopy(contract["tables"]),
        "automations": deepcopy(contract["automations"]),
    }
    saved = client.put(endpoint, headers=headers, json=payload)
    assert saved.status_code == 200, saved.text
    assert saved.json()["readiness_status"] == "ready"
    return integration, saved.json()


def _seed_matching_state(client, integration_id: int):
    now = datetime.utcnow()
    with client.app.state.testing_session_local() as db:
        work_order = WorkOrder(
            organization_id=1,
            ticket_number="PARALLEL-001",
            status="in_progress",
            created_at=now,
            updated_at=now,
        )
        part = Part(
            organization_id=1,
            part_number="FILTER-1",
            name="Pilot filter",
        )
        warehouse = Warehouse(
            organization_id=1,
            code="MAIN",
            name="Main parallel warehouse",
        )
        db.add_all([work_order, part, warehouse])
        db.flush()
        db.add_all(
            [
                ExternalWorkOrderLink(
                    organization_id=1,
                    integration_id=integration_id,
                    external_id="appsheet-row-1",
                    work_order_id=work_order.id,
                ),
                WorkOrderPart(
                    organization_id=1,
                    work_order_id=work_order.id,
                    part_id=part.id,
                    warehouse_id=warehouse.id,
                    quantity=2,
                    created_at=now,
                    updated_at=now,
                ),
                InventoryTransaction(
                    organization_id=1,
                    part_id=part.id,
                    transaction_type=TransactionType.INBOUND,
                    quantity=5,
                    to_warehouse_id=warehouse.id,
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        db.commit()
    return now


def _snapshot(revision: str, now: datetime) -> dict:
    return {
        "source_revision": revision,
        "observed_from": (now - timedelta(minutes=1)).isoformat() + "Z",
        "observed_to": (now + timedelta(minutes=1)).isoformat() + "Z",
        "work_orders": [{"external_id": "appsheet-row-1", "status": "IN_PROGRESS"}],
        "part_usage": [
            {
                "external_work_order_id": "appsheet-row-1",
                "part_number": "filter-1",
                "quantity": 2,
            }
        ],
        "inventory": [
            {"warehouse_code": "main", "part_number": "filter-1", "quantity": 5}
        ],
        "reason": "First controlled parallel-run comparison",
    }


def test_parallel_reconciliation_matched_difference_idempotency_and_safe_storage(client):
    integration, contract = _ready_integration(client)
    now = _seed_matching_state(client, integration["id"])
    endpoint = f"/api/integrations/{integration['id']}/parallel-reconciliations"
    payload = _snapshot(contract["source_revision"], now)

    matched = client.post(endpoint, json=payload)
    assert matched.status_code == 200, matched.text
    evidence = matched.json()
    assert evidence["status"] == "matched"
    assert evidence["input_record_count"] == 3
    assert evidence["matched_record_count"] == 3
    assert evidence["discrepancy_count"] == 0
    assert evidence["discrepancies"] == []
    assert all(len(evidence[name]) == 64 for name in (
        "contract_fingerprint",
        "snapshot_fingerprint",
        "evidence_fingerprint",
    ))

    exact_retry = client.post(endpoint, json=payload)
    assert exact_retry.status_code == 200, exact_retry.text
    assert exact_retry.json()["id"] == evidence["id"]

    difference_payload = deepcopy(payload)
    difference_payload["reason"] = "Investigate controlled parallel-run differences"
    difference_payload["work_orders"][0]["status"] = "completed"
    difference_payload["part_usage"][0]["quantity"] = 1
    difference_payload["inventory"][0]["quantity"] = 4
    difference_payload["inventory"].append(
        {"warehouse_code": "main", "part_number": "ghost-part", "quantity": 1}
    )
    differences = client.post(endpoint, json=difference_payload)
    assert differences.status_code == 200, differences.text
    changed = differences.json()
    assert changed["status"] == "differences"
    assert changed["discrepancy_count"] == 4
    assert {item["object_type"] for item in changed["discrepancies"]} == {
        "work_order",
        "part_usage",
        "inventory",
    }
    assert any(item["reason"] == "missing_openpartsflow" for item in changed["discrepancies"])

    listed = client.get(endpoint)
    assert listed.status_code == 200, listed.text
    assert [row["id"] for row in listed.json()] == [changed["id"], evidence["id"]]
    detail = client.get(f"{endpoint}/{changed['id']}")
    assert detail.status_code == 200
    assert detail.json() == changed

    with client.app.state.testing_session_local() as db:
        rows = db.scalars(select(IntegrationParallelReconciliation)).all()
        assert len(rows) == 2
        assert rows[0].discrepancies_json == "[]"
        stored_text = rows[0].object_counts_json + rows[0].discrepancies_json
        assert "appsheet-row-1" not in stored_text
        assert "FILTER-1" not in stored_text
        assert db.scalar(
            select(func.count(AuditLog.id)).where(
                AuditLog.action == "create_integration_parallel_reconciliation"
            )
        ) == 2


def test_parallel_reconciliation_validates_contract_revision_keys_and_window(client):
    integration, contract = _ready_integration(client, name="Validation AppSheet")
    now = _seed_matching_state(client, integration["id"])
    endpoint = f"/api/integrations/{integration['id']}/parallel-reconciliations"
    payload = _snapshot(contract["source_revision"], now)

    stale = deepcopy(payload)
    stale["source_revision"] = "another export"
    assert client.post(endpoint, json=stale).status_code == 409

    duplicate = deepcopy(payload)
    duplicate["inventory"].append(deepcopy(duplicate["inventory"][0]))
    response = client.post(endpoint, json=duplicate)
    assert response.status_code == 422
    assert "duplicate key" in response.text

    zero = deepcopy(payload)
    zero["inventory"][0]["quantity"] = 0
    response = client.post(endpoint, json=zero)
    assert response.status_code == 422
    assert "omit zero balances" in response.text

    oversized_window = deepcopy(payload)
    oversized_window["observed_from"] = (now - timedelta(days=367)).isoformat()
    response = client.post(endpoint, json=oversized_window)
    assert response.status_code == 422
    assert "cannot exceed 366 days" in response.text


def test_parallel_reconciliation_roles_tenant_isolation_and_pilot_counts(client):
    admin = _create_user(client, "parallel-admin", "admin")
    manager = _create_user(client, "parallel-manager", "manager")
    engineer = _create_user(client, "parallel-engineer", "engineer")
    with client.app.state.testing_session_local() as db:
        other_org = Organization(name="Parallel tenant two", slug="parallel-tenant-two")
        db.add(other_org)
        db.flush()
        other_admin = User(
            organization_id=other_org.id,
            name="parallel-other-admin",
            email="parallel-other-admin@parallel-reconciliation.test",
            role=UserRole.ADMIN,
            password_hash=hash_password(PASSWORD),
        )
        other_part = Part(
            organization_id=other_org.id,
            part_number="OTHER-PART",
            name="Other tenant part",
        )
        other_work_order = WorkOrder(
            organization_id=other_org.id,
            ticket_number="OTHER-PARALLEL-001",
            status="open",
        )
        db.add_all([other_admin, other_part, other_work_order])
        db.commit()
        other_admin_id = other_admin.id

    headers = _login_headers(client, admin["email"])
    with _enforced_rbac():
        integration, contract = _ready_integration(
            client,
            headers=headers,
            name="Tenant one AppSheet",
        )
        now = _seed_matching_state(client, integration["id"])
        endpoint = f"/api/integrations/{integration['id']}/parallel-reconciliations"
        payload = _snapshot(contract["source_revision"], now)
        payload["account_password"] = PASSWORD
        created = client.post(endpoint, headers=headers, json=payload)
        assert created.status_code == 200, created.text

        manager_headers = {"X-User-Id": str(manager["id"])}
        assert client.get(endpoint, headers=manager_headers).status_code == 200
        assert client.post(endpoint, headers=manager_headers, json=payload).status_code == 403
        assert client.get(
            endpoint,
            headers={"X-User-Id": str(engineer["id"])},
        ).status_code == 403
        assert client.get(
            endpoint,
            headers={"X-User-Id": str(other_admin_id)},
        ).status_code == 404

        checklist = client.get("/api/pilot/checklist", headers=headers)
        assert checklist.status_code == 200, checklist.text
        pilot = checklist.json()
        assert pilot["total_users"] == 3
        assert pilot["total_work_orders"] == 1
        assert pilot["total_parts"] == 1
        assert pilot["active_integration_count"] == 1
        assert pilot["ready_parity_contract_count"] == 1
        assert pilot["integration_parallel_readiness"] == "matched"
        assert pilot["latest_reconciliation_id"] == created.json()["id"]
