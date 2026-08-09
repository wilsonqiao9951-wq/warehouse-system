from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy

from sqlalchemy import select

from app.core.config import settings
from app.models import (
    AuditLog,
    IntegrationParityContract,
    Organization,
    User,
    UserRole,
)


def _create_user(client, name: str, role: str) -> dict:
    response = client.post(
        "/api/users",
        json={
            "name": name,
            "email": f"{name}@parity-contract.test",
            "role": role,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


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


def _integration(client, *, headers: dict[str, str] | None = None, name: str = "AppSheet parity") -> dict:
    response = client.post(
        "/api/integrations",
        headers=headers,
        json={
            "name": name,
            "provider": "appsheet",
            "field_mapping": {
                "ticket_number": "WO ID",
                "outlet_name": "Site",
                "problem_description": "Issue",
                "machine_type": "Model",
            },
            "webhook_url": "https://events.example.test/openpartsflow",
            "subscribed_events": [
                "work_order.status_changed",
                "work_order.completed",
                "work_order.part_used",
            ],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["integration"]


def _upsert_payload(contract: dict, *, source_revision: str, expected_version: int | None = None) -> dict:
    return {
        "expected_version": contract["version"] if expected_version is None else expected_version,
        "source_revision": source_revision,
        "required_capabilities": deepcopy(contract["required_capabilities"]),
        "tables": deepcopy(contract["tables"]),
        "automations": deepcopy(contract["automations"]),
    }


def test_parity_template_save_fingerprint_idempotency_and_revalidation(client):
    integration = _integration(client)
    endpoint = f"/api/integrations/{integration['id']}/parity-contract"

    template = client.get(endpoint)
    assert template.status_code == 200, template.text
    draft = template.json()
    assert draft["persisted"] is False
    assert draft["readiness_status"] == "draft"
    assert draft["readiness_score"] == 100
    assert set(draft["covered_capabilities"]) == set(draft["required_capabilities"])
    assert len(draft["source_fingerprint"]) == 64
    assert any(gap["code"] == "source_revision_missing" for gap in draft["gaps"])

    saved = client.put(
        endpoint,
        json=_upsert_payload(draft, source_revision="AppSheet 2026-08-08 export"),
    )
    assert saved.status_code == 200, saved.text
    contract = saved.json()
    assert contract["persisted"] is True
    assert contract["readiness_status"] == "ready"
    assert contract["readiness_score"] == 100
    assert contract["version"] == 0
    assert contract["source_revision"] == "AppSheet 2026-08-08 export"
    assert contract["gaps"] == []

    exact_retry = client.put(
        endpoint,
        json=_upsert_payload(contract, source_revision=contract["source_revision"]),
    )
    assert exact_retry.status_code == 200, exact_retry.text
    assert exact_retry.json()["id"] == contract["id"]
    assert exact_retry.json()["version"] == 0

    changed = client.put(
        endpoint,
        json=_upsert_payload(contract, source_revision="AppSheet 2026-08-09 export"),
    )
    assert changed.status_code == 200, changed.text
    changed_contract = changed.json()
    assert changed_contract["version"] == 1
    assert changed_contract["source_fingerprint"] != contract["source_fingerprint"]

    stale = client.put(
        endpoint,
        json=_upsert_payload(contract, source_revision="stale writer", expected_version=0),
    )
    assert stale.status_code == 409

    integration_update = client.patch(
        f"/api/integrations/{integration['id']}",
        json={
            "expected_version": integration["version"],
            "subscribed_events": [],
            "webhook_url": None,
        },
    )
    assert integration_update.status_code == 200, integration_update.text
    revalidated = client.get(endpoint).json()
    assert revalidated["version"] == 2
    assert revalidated["readiness_status"] == "blocked"
    assert revalidated["readiness_score"] == 57
    assert {
        gap["capability"]
        for gap in revalidated["gaps"]
        if gap["severity"] == "error"
    } == {"status_callback", "completion_callback", "part_usage_callback"}

    disabled = client.patch(
        f"/api/integrations/{integration['id']}",
        json={
            "expected_version": integration_update.json()["version"],
            "is_active": False,
        },
    )
    assert disabled.status_code == 200, disabled.text
    disabled_contract = client.get(endpoint).json()
    assert disabled_contract["version"] == 3
    assert disabled_contract["readiness_score"] == 0
    assert any(gap["code"] == "integration_inactive" for gap in disabled_contract["gaps"])

    with client.app.state.testing_session_local() as db:
        stored = db.scalar(select(IntegrationParityContract))
        assert stored.organization_id == 1
        assert stored.readiness_status == "blocked"
        assert stored.version == 3
        assert "WO ID" in stored.tables_json
        actions = [
            row.action
            for row in db.scalars(
                select(AuditLog).where(
                    AuditLog.action.in_(
                        {
                            "create_integration_parity_contract",
                            "update_integration_parity_contract",
                        }
                    )
                )
            ).all()
        ]
        assert actions.count("create_integration_parity_contract") == 1
        assert actions.count("update_integration_parity_contract") == 1


def test_parity_contract_rejects_unsafe_ambiguous_and_read_only_mappings(client):
    integration = _integration(client, name="Unsafe parity")
    endpoint = f"/api/integrations/{integration['id']}/parity-contract"
    draft = client.get(endpoint).json()

    unsafe = _upsert_payload(draft, source_revision="unsafe")
    unsafe["tables"][0]["columns"].append(
        {
            "external_name": "Technician Device",
            "canonical_field": "work_order.assigned_device_id",
            "data_type": "text",
            "direction": "inbound",
            "required": False,
        }
    )
    rejected = client.put(endpoint, json=unsafe)
    assert rejected.status_code == 422
    assert "Unsupported canonical field" in rejected.text

    read_only = _upsert_payload(draft, source_revision="read-only mutation")
    inventory_table = next(
        table for table in read_only["tables"] if table["canonical_object"] == "inventory"
    )
    inventory_table["columns"][0]["direction"] = "inbound"
    rejected = client.put(endpoint, json=read_only)
    assert rejected.status_code == 422
    assert "does not support inbound access" in rejected.text

    missing_key = _upsert_payload(draft, source_revision="missing key")
    missing_key["tables"][0]["key_column"] = "Unknown Key"
    rejected = client.put(endpoint, json=missing_key)
    assert rejected.status_code == 422
    assert "must exist in its columns" in rejected.text

    missing_automation = _upsert_payload(draft, source_revision="missing intake bot")
    missing_automation["automations"] = [
        automation
        for automation in missing_automation["automations"]
        if automation["capability"] != "work_order_intake"
    ]
    incomplete = client.put(endpoint, json=missing_automation)
    assert incomplete.status_code == 200, incomplete.text
    assert incomplete.json()["readiness_status"] == "blocked"
    assert any(
        gap["capability"] == "work_order_intake" for gap in incomplete.json()["gaps"]
    )

    documented_only = _upsert_payload(draft, source_revision="complete dictionary")
    documented_only["tables"][0]["columns"].append(
        {
            "external_name": "Legacy Dispatch Formula",
            "canonical_field": None,
            "data_type": "text",
            "direction": "read",
            "required": False,
            "notes": "Retained for discovery; not connected to OpenPartsFlow.",
        }
    )
    accepted = client.put(endpoint, json=documented_only)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["readiness_status"] == "ready"
    assert any(gap["code"] == "external_columns_unmapped" for gap in accepted.json()["gaps"])


def test_parity_contract_roles_and_tenant_isolation(client):
    admin = _create_user(client, "parity-admin", "admin")
    manager = _create_user(client, "parity-manager", "manager")
    engineer = _create_user(client, "parity-engineer", "engineer")
    with client.app.state.testing_session_local() as db:
        other_org = Organization(name="Parity tenant two", slug="parity-tenant-two")
        db.add(other_org)
        db.flush()
        other_admin = User(
            organization_id=other_org.id,
            name="parity-other-admin",
            email="parity-other-admin@parity-contract.test",
            role=UserRole.ADMIN,
        )
        db.add(other_admin)
        db.commit()
        other_admin_id = other_admin.id

    with _enforced_rbac():
        integration = _integration(
            client,
            headers={"X-User-Id": str(admin["id"])},
            name="Tenant one parity",
        )
        endpoint = f"/api/integrations/{integration['id']}/parity-contract"
        manager_read = client.get(
            endpoint,
            headers={"X-User-Id": str(manager["id"])},
        )
        assert manager_read.status_code == 200, manager_read.text
        manager_write = client.put(
            endpoint,
            headers={"X-User-Id": str(manager["id"])},
            json=_upsert_payload(manager_read.json(), source_revision="manager cannot save"),
        )
        assert manager_write.status_code == 403
        engineer_read = client.get(
            endpoint,
            headers={"X-User-Id": str(engineer["id"])},
        )
        assert engineer_read.status_code == 403
        hidden = client.get(
            endpoint,
            headers={"X-User-Id": str(other_admin_id)},
        )
        assert hidden.status_code == 404

        second = _integration(
            client,
            headers={"X-User-Id": str(other_admin_id)},
            name="Tenant two parity",
        )
        second_endpoint = f"/api/integrations/{second['id']}/parity-contract"
        second_template = client.get(
            second_endpoint,
            headers={"X-User-Id": str(other_admin_id)},
        ).json()
        saved = client.put(
            second_endpoint,
            headers={"X-User-Id": str(other_admin_id)},
            json=_upsert_payload(second_template, source_revision="tenant two export"),
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["organization_id"] == 2

    with client.app.state.testing_session_local() as db:
        rows = db.scalars(
            select(IntegrationParityContract).order_by(IntegrationParityContract.organization_id)
        ).all()
        assert [row.organization_id for row in rows] == [2]
