from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.database import DatabaseSchemaError, ensure_data_residency_ready
from app.core.data_residency import (
    normalize_region_code,
    residency_block_reason,
    residency_status,
)
from app.models import AuditLog, Organization, User


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _login(client, email: str, password: str) -> str:
    response = client.post(
        "/api/auth/login",
        data={"username": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def test_region_codes_and_runtime_status_are_deterministic():
    assert normalize_region_code(" US-EAST-1 ") == "us-east-1"
    assert residency_status(None, "us-east-1") == "unrestricted"
    assert residency_status("us-east-1", "us-east-1") == "compliant"
    assert residency_status("eu-west-1", "us-east-1") == "blocked"
    assert residency_block_reason("eu-west-1", "us-east-1") == (
        "Organization data residency requires eu-west-1; "
        "this deployment is us-east-1"
    )


def test_enterprise_residency_is_reauthenticated_audited_and_enforced(client):
    original_rbac = settings.rbac_enforce
    original_legacy = settings.legacy_header_auth
    original_region = settings.deployment_region
    original_environment = settings.app_env
    try:
        settings.deployment_region = "us-east-1"
        settings.rbac_enforce = False
        platform_user = client.post(
            "/api/users",
            json={
                "name": "Residency Platform Owner",
                "email": "residency-platform@example.test",
                "role": "admin",
                "password": "residency-platform-password",
            },
        ).json()
        with client.app.state.testing_session_local() as db:
            stored = db.get(User, platform_user["id"])
            assert stored is not None
            stored.is_platform_admin = True
            db.commit()

        settings.rbac_enforce = True
        settings.legacy_header_auth = False
        platform_token = _login(
            client,
            "residency-platform@example.test",
            "residency-platform-password",
        )

        non_enterprise = client.post(
            "/api/platform/organizations",
            headers=_bearer(platform_token),
            json={
                "name": "Professional Residency Rejected",
                "slug": "professional-residency-rejected",
                "admin_name": "Rejected Admin",
                "admin_email": "residency-rejected@example.test",
                "admin_password": "residency-rejected-password",
                "plan_code": "professional",
                "trial_days": 0,
                "data_residency_region": "us-east-1",
            },
        )
        assert non_enterprise.status_code == 422

        created = client.post(
            "/api/platform/organizations",
            headers=_bearer(platform_token),
            json={
                "name": "Residency Customer",
                "slug": "residency-customer",
                "admin_name": "Residency Customer Admin",
                "admin_email": "residency-customer@example.test",
                "admin_password": "residency-customer-password",
                "plan_code": "enterprise",
                "trial_days": 0,
            },
        )
        assert created.status_code == 200, created.text
        organization = created.json()
        assert organization["data_residency_status"] == "unrestricted"
        assert organization["deployment_region"] == "us-east-1"

        customer_token = _login(
            client,
            "residency-customer@example.test",
            "residency-customer-password",
        )
        integration = client.post(
            "/api/integrations",
            headers=_bearer(customer_token),
            json={
                "name": "Residency API",
                "provider": "generic",
                "field_mapping": {},
            },
        )
        assert integration.status_code == 200, integration.text
        api_key = integration.json()["api_key"]

        missing_password = client.patch(
            f"/api/platform/organizations/{organization['id']}",
            headers=_bearer(platform_token),
            json={
                "expected_version": organization["settings_version"],
                "data_residency_region": "us-east-1",
            },
        )
        assert missing_password.status_code == 401

        wrong_region = client.patch(
            f"/api/platform/organizations/{organization['id']}",
            headers=_bearer(platform_token),
            json={
                "expected_version": organization["settings_version"],
                "data_residency_region": "eu-west-1",
                "account_password": "residency-platform-password",
            },
        )
        assert wrong_region.status_code == 422
        assert "this deployment's region" in wrong_region.json()["detail"]

        enforced = client.patch(
            f"/api/platform/organizations/{organization['id']}",
            headers=_bearer(platform_token),
            json={
                "expected_version": organization["settings_version"],
                "data_residency_region": "US-EAST-1",
                "account_password": "residency-platform-password",
            },
        )
        assert enforced.status_code == 200, enforced.text
        enforced_payload = enforced.json()
        assert enforced_payload["data_residency_region"] == "us-east-1"
        assert enforced_payload["data_residency_enforced_at"] is not None
        assert enforced_payload["data_residency_status"] == "compliant"

        settings.app_env = "production"
        with client.app.state.testing_session_local() as db:
            ensure_data_residency_ready(db.get_bind())

        with client.app.state.testing_session_local() as db:
            audit = db.scalar(
                select(AuditLog)
                .where(
                    AuditLog.organization_id == organization["id"],
                    AuditLog.action == "organization_data_residency_updated",
                )
                .order_by(AuditLog.id.desc())
            )
            assert audit is not None
            metadata = json.loads(audit.metadata_json)
            assert metadata["after"]["data_residency_region"] == "us-east-1"
            assert "account_password" not in audit.metadata_json

        settings.deployment_region = "eu-west-1"
        with client.app.state.testing_session_local() as db:
            with pytest.raises(DatabaseSchemaError, match="data-residency"):
                ensure_data_residency_ready(db.get_bind())
        existing_session = client.get(
            "/api/auth/me",
            headers=_bearer(customer_token),
        )
        assert existing_session.status_code == 403
        assert "data residency requires us-east-1" in existing_session.json()["detail"]

        blocked_login = client.post(
            "/api/auth/login",
            data={
                "username": "residency-customer@example.test",
                "password": "residency-customer-password",
            },
        )
        assert blocked_login.status_code == 403

        blocked_external = client.get(
            "/api/external/v1/inventory",
            headers={"X-API-Key": api_key},
        )
        assert blocked_external.status_code == 403

        hidden_branding = client.get(
            "/api/auth/organization-branding/residency-customer"
        )
        assert hidden_branding.status_code == 404

        platform_view = client.get(
            "/api/platform/organizations",
            headers=_bearer(platform_token),
        )
        assert platform_view.status_code == 200
        residency_row = next(
            row for row in platform_view.json() if row["id"] == organization["id"]
        )
        assert residency_row["data_residency_status"] == "blocked"

        with client.app.state.testing_session_local() as db:
            stored_organization = db.get(Organization, organization["id"])
            assert stored_organization is not None
            assert stored_organization.data_residency_region == "us-east-1"
    finally:
        settings.deployment_region = original_region
        settings.app_env = original_environment
        settings.rbac_enforce = original_rbac
        settings.legacy_header_auth = original_legacy
