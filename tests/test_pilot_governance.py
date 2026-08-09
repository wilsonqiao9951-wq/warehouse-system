from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta

from sqlalchemy import func, select

from app.core.config import settings
from app.core.security import hash_password
from app.models import (
    AuditLog,
    ExternalIntegration,
    IntegrationParallelReconciliation,
    IntegrationParityContract,
    Organization,
    PilotAttestation,
    PilotCampaign,
    PilotIssue,
    User,
    UserRole,
)
from app.services.pilot_governance import PILOT_REQUIRED_ITEMS


PASSWORD = "governed-pilot-account-password"


def _create_user(client, name: str, role: str) -> dict:
    response = client.post(
        "/api/users",
        json={
            "name": name,
            "email": f"{name}@pilot-governance.test",
            "role": role,
            "password": PASSWORD,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _login_headers(client, email: str, password: str = PASSWORD) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        data={"username": email, "password": password},
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


def _seed_matched_reconciliation(client, admin_id: int) -> int:
    now = datetime.utcnow()
    with client.app.state.testing_session_local() as db:
        integration = ExternalIntegration(
            organization_id=1,
            name="Pilot acceptance AppSheet",
            provider="appsheet",
            key_prefix="opf_pilot_governance",
            api_key_hash="a" * 64,
            field_mapping_json="{}",
            subscribed_events_json="[]",
            is_active=True,
            created_by=admin_id,
            updated_by=admin_id,
        )
        db.add(integration)
        db.flush()
        contract = IntegrationParityContract(
            organization_id=1,
            integration_id=integration.id,
            source_revision="pilot-governance-revision",
            required_capabilities_json="[]",
            covered_capabilities_json="[]",
            tables_json="[]",
            automations_json="[]",
            gaps_json="[]",
            readiness_status="ready",
            readiness_score=100,
            source_fingerprint="b" * 64,
            created_by=admin_id,
            updated_by=admin_id,
            validated_at=now,
        )
        db.add(contract)
        db.flush()
        evidence = IntegrationParallelReconciliation(
            organization_id=1,
            integration_id=integration.id,
            contract_id=contract.id,
            source_revision=contract.source_revision,
            contract_fingerprint="b" * 64,
            snapshot_fingerprint="c" * 64,
            evidence_fingerprint="d" * 64,
            observed_from=now - timedelta(hours=1),
            observed_to=now,
            status="matched",
            input_record_count=0,
            matched_record_count=0,
            discrepancy_count=0,
            object_counts_json="{}",
            discrepancies_json="[]",
            truncated=False,
            reason="Controlled test reconciliation",
            created_by=admin_id,
            created_at=now,
        )
        db.add(evidence)
        db.commit()
        return evidence.id


def _pass_attestation(client, headers: dict[str, str], campaign_id: int, role: str, kind: str):
    payload = {
        "attestation_type": kind,
        "result": "passed",
        "completed_items": PILOT_REQUIRED_ITEMS[role][kind],
        "note": f"Completed controlled {role} {kind}",
        "account_password": PASSWORD,
    }
    response = client.post(
        f"/api/pilot/campaigns/{campaign_id}/attestations",
        headers=headers,
        json=payload,
    )
    assert response.status_code == 200, response.text
    return response, payload


def test_pilot_campaign_requires_role_attestations_issue_closure_and_matched_reconciliation(client):
    users = {
        role: _create_user(client, f"pilot-{role}", role)
        for role in ("admin", "manager", "warehouse", "engineer")
    }
    headers = {role: _login_headers(client, user["email"]) for role, user in users.items()}

    with _enforced_rbac():
        created = client.post(
            "/api/pilot/campaigns",
            headers=headers["manager"],
            json={
                "name": "Three day controlled pilot",
                "planned_start": date.today().isoformat(),
                "planned_end": (date.today() + timedelta(days=2)).isoformat(),
            },
        )
        assert created.status_code == 200, created.text
        campaign = created.json()
        campaign_id = campaign["id"]
        assert campaign["status"] == "draft"
        assert client.post(
            "/api/pilot/campaigns",
            headers=headers["engineer"],
            json={
                "name": "Unauthorized pilot",
                "planned_start": date.today().isoformat(),
                "planned_end": date.today().isoformat(),
            },
        ).status_code == 403

        active = client.post(
            f"/api/pilot/campaigns/{campaign_id}/transitions",
            headers=headers["manager"],
            json={
                "expected_version": 0,
                "target_status": "active",
                "account_password": PASSWORD,
                "reason": "Begin the controlled pilot window",
            },
        )
        assert active.status_code == 200, active.text
        assert active.json()["version"] == 1

        issue = client.post(
            f"/api/pilot/campaigns/{campaign_id}/issues",
            headers=headers["engineer"],
            json={
                "severity": "sev1",
                "title": "Completion blocked on registered phone",
                "detail": "The controlled test could not complete until the device was rebound.",
            },
        )
        assert issue.status_code == 200, issue.text
        own_issue = issue.json()["issues"][0]
        assert own_issue["reported_by"] == users["engineer"]["id"]

        for role in ("admin", "manager", "warehouse", "engineer"):
            for kind in ("training", "uat"):
                response, payload = _pass_attestation(
                    client, headers[role], campaign_id, role, kind
                )
                if role == "engineer" and kind == "uat":
                    exact_retry = client.post(
                        f"/api/pilot/campaigns/{campaign_id}/attestations",
                        headers=headers[role],
                        json=payload,
                    )
                    assert exact_retry.status_code == 200
                    assert len(exact_retry.json()["latest_attestations"]) == 2

        admin_view = client.get(
            f"/api/pilot/campaigns/{campaign_id}", headers=headers["admin"]
        )
        assert admin_view.status_code == 200
        assert len(admin_view.json()["latest_attestations"]) == 8
        assert admin_view.json()["gates"]["no_open_sev1"] is False

        stale_resolution = client.post(
            f"/api/pilot/campaigns/{campaign_id}/issues/{own_issue['id']}/resolve",
            headers=headers["manager"],
            json={
                "expected_version": 1,
                "resolution_reason": "Device registration corrected and retested",
                "account_password": PASSWORD,
            },
        )
        assert stale_resolution.status_code == 409
        resolved = client.post(
            f"/api/pilot/campaigns/{campaign_id}/issues/{own_issue['id']}/resolve",
            headers=headers["manager"],
            json={
                "expected_version": 0,
                "resolution_reason": "Device registration corrected and retested",
                "account_password": PASSWORD,
            },
        )
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["gates"]["no_open_sev1"] is True

        pending = client.post(
            f"/api/pilot/campaigns/{campaign_id}/transitions",
            headers=headers["manager"],
            json={
                "expected_version": 1,
                "target_status": "decision_pending",
                "account_password": PASSWORD,
                "reason": "All role scripts and issue review are complete",
            },
        )
        assert pending.status_code == 200, pending.text
        assert pending.json()["version"] == 2

        blocked_go = client.post(
            f"/api/pilot/campaigns/{campaign_id}/decision",
            headers=headers["admin"],
            json={
                "expected_version": 2,
                "decision": "go",
                "reason": "Expand the internal technical pilot",
                "account_password": PASSWORD,
            },
        )
        assert blocked_go.status_code == 409
        assert "parallel reconciliation" in blocked_go.text

        reconciliation_id = _seed_matched_reconciliation(client, users["admin"]["id"])
        with client.app.state.testing_session_local() as db:
            contract = db.scalar(select(IntegrationParityContract))
            assert contract is not None
            contract.source_fingerprint = "e" * 64
            db.commit()
        stale_contract_go = client.post(
            f"/api/pilot/campaigns/{campaign_id}/decision",
            headers=headers["admin"],
            json={
                "expected_version": 2,
                "decision": "go",
                "reason": "Stale reconciliation must not authorize expansion",
                "account_password": PASSWORD,
            },
        )
        assert stale_contract_go.status_code == 409
        assert "current ready contract" in stale_contract_go.text
        with client.app.state.testing_session_local() as db:
            contract = db.scalar(select(IntegrationParityContract))
            assert contract is not None
            contract.source_fingerprint = "b" * 64
            db.commit()
        decided = client.post(
            f"/api/pilot/campaigns/{campaign_id}/decision",
            headers=headers["admin"],
            json={
                "expected_version": 2,
                "decision": "go",
                "reason": "Expand the internal technical pilot",
                "account_password": PASSWORD,
            },
        )
        assert decided.status_code == 200, decided.text
        final = decided.json()
        assert final["status"] == "go"
        assert final["gates"]["go_ready"] is True
        assert final["latest_reconciliation_id"] == reconciliation_id
        assert len(final["decision_fingerprint"]) == 64

        exact_retry = client.post(
            f"/api/pilot/campaigns/{campaign_id}/decision",
            headers=headers["admin"],
            json={
                "expected_version": 2,
                "decision": "go",
                "reason": "Expand the internal technical pilot",
                "account_password": PASSWORD,
            },
        )
        assert exact_retry.status_code == 200
        assert exact_retry.json()["decision_fingerprint"] == final["decision_fingerprint"]
        assert client.post(
            f"/api/pilot/campaigns/{campaign_id}/issues",
            headers=headers["engineer"],
            json={"severity": "sev3", "title": "Late note", "detail": "Terminal campaign"},
        ).status_code == 409

    with client.app.state.testing_session_local() as db:
        assert db.scalar(select(func.count(PilotAttestation.id))) == 8
        assert db.scalar(select(func.count(PilotIssue.id))) == 1
        stored = db.get(PilotCampaign, campaign_id)
        assert stored.status == "go"
        snapshot = stored.decision_snapshot_json
        assert "account_password" not in snapshot
        assert "Completion blocked" not in snapshot
        assert db.scalar(
            select(func.count(AuditLog.id)).where(AuditLog.entity_type == "pilot_campaign")
        ) >= 13


def test_pilot_governance_password_roles_single_live_campaign_and_tenant_isolation(client):
    admin = _create_user(client, "pilot-security-admin", "admin")
    manager = _create_user(client, "pilot-security-manager", "manager")
    warehouse = _create_user(client, "pilot-security-warehouse", "warehouse")
    engineer = _create_user(client, "pilot-security-engineer", "engineer")
    headers = {
        "admin": _login_headers(client, admin["email"]),
        "manager": _login_headers(client, manager["email"]),
        "warehouse": _login_headers(client, warehouse["email"]),
        "engineer": _login_headers(client, engineer["email"]),
    }
    with client.app.state.testing_session_local() as db:
        other_org = Organization(name="Other pilot tenant", slug="other-pilot-tenant")
        db.add(other_org)
        db.flush()
        other_admin = User(
            organization_id=other_org.id,
            name="Other pilot admin",
            email="other-admin@pilot-governance.test",
            role=UserRole.ADMIN,
            password_hash=hash_password(PASSWORD),
        )
        db.add(other_admin)
        db.flush()
        other_campaign = PilotCampaign(
            organization_id=other_org.id,
            name="Other tenant campaign",
            planned_start=date.today(),
            planned_end=date.today(),
            status="draft",
            created_by=other_admin.id,
            updated_by=other_admin.id,
        )
        db.add(other_campaign)
        db.commit()
        other_campaign_id = other_campaign.id

    with _enforced_rbac():
        first = client.post(
            "/api/pilot/campaigns",
            headers=headers["manager"],
            json={"name": "First campaign", "planned_start": date.today().isoformat(), "planned_end": date.today().isoformat()},
        ).json()
        second = client.post(
            "/api/pilot/campaigns",
            headers=headers["manager"],
            json={"name": "Second campaign", "planned_start": date.today().isoformat(), "planned_end": date.today().isoformat()},
        ).json()
        wrong_password = client.post(
            f"/api/pilot/campaigns/{first['id']}/transitions",
            headers=headers["manager"],
            json={
                "expected_version": 0,
                "target_status": "active",
                "account_password": "wrong-password",
                "reason": "Must not authenticate",
            },
        )
        assert wrong_password.status_code == 401
        assert client.post(
            f"/api/pilot/campaigns/{first['id']}/transitions",
            headers=headers["manager"],
            json={
                "expected_version": 0,
                "target_status": "active",
                "account_password": PASSWORD,
                "reason": "Start first campaign",
            },
        ).status_code == 200
        competing = client.post(
            f"/api/pilot/campaigns/{second['id']}/transitions",
            headers=headers["manager"],
            json={
                "expected_version": 0,
                "target_status": "active",
                "account_password": PASSWORD,
                "reason": "Must conflict with the live campaign",
            },
        )
        assert competing.status_code == 409

        failed = client.post(
            f"/api/pilot/campaigns/{first['id']}/attestations",
            headers=headers["engineer"],
            json={
                "attestation_type": "uat",
                "result": "failed",
                "completed_items": ["shared_visibility_read_only"],
                "note": "One script completed before a controlled failure",
                "account_password": PASSWORD,
            },
        )
        assert failed.status_code == 200, failed.text
        unknown = client.post(
            f"/api/pilot/campaigns/{first['id']}/attestations",
            headers=headers["engineer"],
            json={
                "attestation_type": "uat",
                "result": "passed",
                "completed_items": ["manager_only_step"],
                "note": "Attempted role substitution",
                "account_password": PASSWORD,
            },
        )
        assert unknown.status_code == 422
        engineer_view = client.get(
            f"/api/pilot/campaigns/{first['id']}", headers=headers["engineer"]
        ).json()
        assert len(engineer_view["latest_attestations"]) == 1
        assert engineer_view["latest_attestations"][0]["role"] == "engineer"
        assert client.get(
            f"/api/pilot/campaigns/{other_campaign_id}", headers=headers["admin"]
        ).status_code == 404
        assert client.post(
            f"/api/pilot/campaigns/{first['id']}/decision",
            headers=headers["manager"],
            json={
                "expected_version": 1,
                "decision": "no_go",
                "reason": "Managers cannot make the final decision",
                "account_password": PASSWORD,
            },
        ).status_code == 403
        assert client.post(
            f"/api/pilot/campaigns/{first['id']}/issues/999/resolve",
            headers=headers["warehouse"],
            json={
                "expected_version": 0,
                "resolution_reason": "Warehouse cannot close governance issues",
                "account_password": PASSWORD,
            },
        ).status_code == 403
