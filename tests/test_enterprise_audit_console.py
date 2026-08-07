from datetime import datetime, timedelta
from hashlib import sha256

from sqlalchemy import select

from app.core.config import settings
from app.models import AuditLog, Organization


ADMIN_PASSWORD = "audit-admin-password"
MANAGER_PASSWORD = "audit-manager-password"


def _create_user(client, *, name: str, email: str, role: str, password: str) -> dict:
    response = client.post(
        "/api/users",
        json={"name": name, "email": email, "role": role, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _login(client, *, email: str, password: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        data={"username": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_audit_search_is_tenant_scoped_filterable_and_cursor_paginated(client):
    now = datetime.utcnow()
    with client.app.state.testing_session_local() as db:
        other = Organization(name="Other Tenant", slug="other-audit-tenant")
        db.add(other)
        db.flush()
        db.add_all(
            [
                AuditLog(
                    organization_id=1,
                    action="work_order_updated",
                    entity_type="work_order",
                    entity_id=100,
                    metadata_json='{"field":"status"}',
                    timestamp=now - timedelta(minutes=2),
                ),
                AuditLog(
                    organization_id=1,
                    action="work_order_updated",
                    entity_type="work_order",
                    entity_id=101,
                    metadata_json="legacy-not-json",
                    timestamp=now - timedelta(minutes=1),
                ),
                AuditLog(
                    organization_id=1,
                    action="part_created",
                    entity_type="part",
                    entity_id=50,
                    metadata_json="{}",
                    timestamp=now,
                ),
                AuditLog(
                    organization_id=other.id,
                    action="work_order_updated",
                    entity_type="work_order",
                    entity_id=999,
                    metadata_json="{}",
                    timestamp=now,
                ),
            ]
        )
        db.commit()

    first = client.get(
        "/api/audit-logs/search",
        params={"action": "work_order_updated", "limit": 1},
    )
    assert first.status_code == 200, first.text
    assert first.headers["cache-control"] == "no-store"
    payload = first.json()
    assert payload["total"] == 2
    assert len(payload["items"]) == 1
    assert payload["items"][0]["entity_id"] == 101
    assert payload["items"][0]["metadata_valid"] is False
    assert payload["items"][0]["metadata"] == {"legacy_raw": "legacy-not-json"}
    assert payload["items"][0]["timestamp"].endswith("Z")
    assert payload["next_before_id"] is not None

    second = client.get(
        "/api/audit-logs/search",
        params={
            "action": "work_order_updated",
            "limit": 1,
            "before_id": payload["next_before_id"],
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["total"] == 2
    assert [row["entity_id"] for row in second.json()["items"]] == [100]
    assert second.json()["next_before_id"] is None

    summary = client.get("/api/audit-logs/summary?days=30")
    assert summary.status_code == 200, summary.text
    assert summary.headers["cache-control"] == "no-store"
    summary_payload = summary.json()
    assert summary_payload["total_events"] == 3
    assert {item["value"] for item in summary_payload["by_action"]} == {
        "part_created",
        "work_order_updated",
    }

    compatibility = client.get("/api/audit-logs?limit=10")
    assert compatibility.status_code == 200, compatibility.text
    assert len(compatibility.json()) == 3
    assert isinstance(compatibility.json()[0]["metadata"], str)

    invalid_range = client.get(
        "/api/audit-logs/search",
        params={"from_at": now.isoformat(), "to_at": (now - timedelta(days=1)).isoformat()},
    )
    assert invalid_range.status_code == 422


def test_audit_export_requires_admin_password_and_records_verified_evidence(client):
    original_rbac = settings.rbac_enforce
    original_legacy = settings.legacy_header_auth
    try:
        settings.rbac_enforce = False
        admin = _create_user(
            client,
            name="Audit Admin",
            email="audit-admin@example.com",
            role="admin",
            password=ADMIN_PASSWORD,
        )
        _create_user(
            client,
            name="Audit Manager",
            email="audit-manager@example.com",
            role="manager",
            password=MANAGER_PASSWORD,
        )
        with client.app.state.testing_session_local() as db:
            db.add(
                AuditLog(
                    organization_id=1,
                    user_id=admin["id"],
                    action="=spreadsheet_formula",
                    entity_type="work_order",
                    entity_id=77,
                    metadata_json='{"safe":true}',
                    timestamp=datetime.utcnow(),
                )
            )
            db.commit()

        settings.rbac_enforce = True
        settings.legacy_header_auth = False
        admin_headers = _login(
            client,
            email="audit-admin@example.com",
            password=ADMIN_PASSWORD,
        )
        manager_headers = _login(
            client,
            email="audit-manager@example.com",
            password=MANAGER_PASSWORD,
        )

        manager_search = client.get("/api/audit-logs/search", headers=manager_headers)
        assert manager_search.status_code == 200, manager_search.text
        manager_export = client.post(
            "/api/audit-logs/export",
            headers=manager_headers,
            json={"account_password": MANAGER_PASSWORD},
        )
        assert manager_export.status_code == 403

        wrong_password = client.post(
            "/api/audit-logs/export",
            headers=admin_headers,
            json={"account_password": "incorrect-password"},
        )
        assert wrong_password.status_code == 401

        exported = client.post(
            "/api/audit-logs/export",
            headers=admin_headers,
            json={
                "action": "=spreadsheet_formula",
                "account_password": ADMIN_PASSWORD,
            },
        )
        assert exported.status_code == 200, exported.text
        assert exported.headers["content-type"].startswith("text/csv")
        assert exported.content.startswith(b"\xef\xbb\xbf")
        assert exported.headers["x-record-count"] == "1"
        assert exported.headers["x-content-sha256"] == sha256(exported.content).hexdigest()
        csv_text = exported.content.decode("utf-8-sig")
        assert "'=spreadsheet_formula" in csv_text
        assert "Z," in csv_text

        with client.app.state.testing_session_local() as db:
            audit = db.scalar(
                select(AuditLog).where(AuditLog.action == "audit_log_exported")
            )
            assert audit is not None
            assert audit.user_id == admin["id"]
            assert '"row_count":1' in (audit.metadata_json or "")
            assert exported.headers["x-content-sha256"] in (audit.metadata_json or "")
            assert "account_password" not in (audit.metadata_json or "")
            assert ADMIN_PASSWORD not in (audit.metadata_json or "")
    finally:
        settings.rbac_enforce = original_rbac
        settings.legacy_header_auth = original_legacy
