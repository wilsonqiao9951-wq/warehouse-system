from datetime import datetime, timedelta

from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.models import AuditLog, Organization, OrganizationDomain, User, UserRole
from app.services.domains import _txt_value, normalize_custom_domain


def _login(client, email: str, password: str) -> str:
    response = client.post(
        "/api/auth/login",
        data={"username": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_domain_normalization_and_txt_presentation_parsing():
    assert normalize_custom_domain(" Portal.Example-Service.COM. ") == (
        "portal.example-service.com"
    )
    assert normalize_custom_domain("münchen.example.net") == "xn--mnchen-3ya.example.net"
    assert _txt_value('"openpartsflow-" "verification=abc"') == (
        "openpartsflow-verification=abc"
    )
    for rejected in (
        "https://portal.example.com",
        "portal.example.com/path",
        "localhost",
        "customer.local",
        "192.168.1.1",
        "singlelabel",
        ".".join(["a" * 63, "b" * 63, "c" * 63, "d" * 33, "com"]),
    ):
        try:
            normalize_custom_domain(rejected)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Expected domain rejection: {rejected}")


def test_domain_verification_branding_email_identity_rotation_and_removal(
    client,
    monkeypatch,
):
    empty = client.get("/api/organization/domain")
    assert empty.status_code == 200
    assert empty.json() is None

    created = client.put(
        "/api/organization/domain",
        json={"domain": "Portal.Field-Service.COM."},
    )
    assert created.status_code == 200, created.text
    domain = created.json()
    assert domain["domain"] == "portal.field-service.com"
    assert domain["status"] == "pending"
    assert domain["version"] == 0
    assert domain["verification_name"] == (
        "_openpartsflow-challenge.portal.field-service.com"
    )
    assert domain["verification_value"].startswith(
        "openpartsflow-verification="
    )
    assert "verification_token" not in domain
    assert domain["login_url"] is None

    same = client.put(
        "/api/organization/domain",
        json={
            "domain": "portal.field-service.com",
            "expected_version": domain["version"],
        },
    )
    assert same.status_code == 200
    assert same.json()["verification_value"] == domain["verification_value"]
    assert same.json()["version"] == domain["version"]

    pending_email = client.patch(
        "/api/organization/domain/email-identity",
        json={
            "expected_version": domain["version"],
            "enabled": True,
            "from_name": "Field Service Dispatch",
            "local_part": "Dispatch",
        },
    )
    assert pending_email.status_code == 409

    async def missing_txt(name: str):
        assert name == domain["verification_name"]
        return set(), None

    monkeypatch.setattr("app.api.routes.lookup_txt_records", missing_txt)
    first_check = client.post(
        "/api/organization/domain/verify",
        json={"expected_version": domain["version"]},
    )
    assert first_check.status_code == 200, first_check.text
    pending = first_check.json()
    assert pending["status"] == "pending"
    assert pending["version"] == 1
    assert "not found" in pending["verification_error"]

    throttled = client.post(
        "/api/organization/domain/verify",
        json={"expected_version": pending["version"]},
    )
    assert throttled.status_code == 429

    with client.app.state.testing_session_local() as db:
        row = db.get(OrganizationDomain, domain["id"])
        assert row is not None
        row.last_checked_at = datetime.utcnow() - timedelta(minutes=2)
        db.commit()

    async def matching_txt(name: str):
        assert name == domain["verification_name"]
        return {domain["verification_value"], "unrelated=value"}, None

    monkeypatch.setattr("app.api.routes.lookup_txt_records", matching_txt)
    verified_response = client.post(
        "/api/organization/domain/verify",
        json={"expected_version": pending["version"]},
    )
    assert verified_response.status_code == 200, verified_response.text
    verified = verified_response.json()
    assert verified["status"] == "verified"
    assert verified["verified_at"] is not None
    assert verified["login_url"] == "https://portal.field-service.com/login"

    public_branding = client.get(
        "/api/auth/organization-branding/by-domain/PORTAL.FIELD-SERVICE.COM"
    )
    assert public_branding.status_code == 200, public_branding.text
    assert public_branding.json()["slug"] == "test"

    enabled_response = client.patch(
        "/api/organization/domain/email-identity",
        json={
            "expected_version": verified["version"],
            "enabled": True,
            "from_name": "  Field   Service Dispatch  ",
            "local_part": "Dispatch",
        },
    )
    assert enabled_response.status_code == 200, enabled_response.text
    enabled = enabled_response.json()
    assert enabled["email_from_name"] == "Field Service Dispatch"
    assert enabled["email_from_local_part"] == "dispatch"
    assert enabled["email_identity_enabled"] is True
    assert enabled["email_sender_address"] == "dispatch@portal.field-service.com"

    stale = client.patch(
        "/api/organization/domain/email-identity",
        json={
            "expected_version": verified["version"],
            "enabled": False,
            "from_name": "Dispatch",
            "local_part": "dispatch",
        },
    )
    assert stale.status_code == 409

    rotated_response = client.post(
        "/api/organization/domain/rotate-challenge",
        json={"expected_version": enabled["version"]},
    )
    assert rotated_response.status_code == 200, rotated_response.text
    rotated = rotated_response.json()
    assert rotated["status"] == "pending"
    assert rotated["verification_value"] != domain["verification_value"]
    assert rotated["email_identity_enabled"] is False
    assert rotated["email_sender_address"] is None
    assert client.get(
        "/api/auth/organization-branding/by-domain/portal.field-service.com"
    ).status_code == 404

    removed = client.request(
        "DELETE",
        "/api/organization/domain",
        json={"expected_version": rotated["version"]},
    )
    assert removed.status_code == 204, removed.text
    assert client.get("/api/organization/domain").json() is None

    with client.app.state.testing_session_local() as db:
        audit_rows = db.scalars(
            select(AuditLog).where(AuditLog.entity_type == "organization_domain")
        ).all()
        assert {
            "organization_domain_created",
            "organization_domain_verification_checked",
            "organization_email_identity_updated",
            "organization_domain_challenge_rotated",
            "organization_domain_removed",
        }.issubset({row.action for row in audit_rows})
        assert all(
            domain["verification_value"] not in (row.metadata_json or "")
            for row in audit_rows
        )


def test_domain_feature_roles_global_uniqueness_and_tenant_isolation(client):
    original_rbac = settings.rbac_enforce
    original_legacy = settings.legacy_header_auth
    try:
        settings.rbac_enforce = False
        first_admin = client.post(
            "/api/users",
            json={
                "name": "Domain Admin One",
                "email": "domain-admin-one@example.test",
                "role": "admin",
                "password": "domain-admin-one-password",
            },
        )
        manager = client.post(
            "/api/users",
            json={
                "name": "Domain Manager",
                "email": "domain-manager@example.test",
                "role": "manager",
                "password": "domain-manager-password",
            },
        )
        assert first_admin.status_code == 200
        assert manager.status_code == 200
        with client.app.state.testing_session_local() as db:
            second = Organization(
                name="Domain Tenant Two",
                slug="domain-tenant-two",
                plan_code="professional",
            )
            db.add(second)
            db.flush()
            db.add(
                User(
                    organization_id=second.id,
                    name="Domain Admin Two",
                    email="domain-admin-two@example.test",
                    role=UserRole.ADMIN,
                    password_hash=hash_password("domain-admin-two-password"),
                    is_active=True,
                )
            )
            db.commit()

        settings.rbac_enforce = True
        settings.legacy_header_auth = False
        first_token = _login(
            client,
            "domain-admin-one@example.test",
            "domain-admin-one-password",
        )
        manager_token = _login(
            client,
            "domain-manager@example.test",
            "domain-manager-password",
        )
        second_token = _login(
            client,
            "domain-admin-two@example.test",
            "domain-admin-two-password",
        )

        forbidden_role = client.get(
            "/api/organization/domain",
            headers=_bearer(manager_token),
        )
        assert forbidden_role.status_code == 403

        missing_reauthentication = client.put(
            "/api/organization/domain",
            headers=_bearer(first_token),
            json={"domain": "shared.customer-domain.com"},
        )
        assert missing_reauthentication.status_code == 401
        created = client.put(
            "/api/organization/domain",
            headers=_bearer(first_token),
            json={
                "domain": "shared.customer-domain.com",
                "account_password": "domain-admin-one-password",
            },
        )
        assert created.status_code == 200, created.text
        for method, path, payload in (
            (
                "PUT",
                "/api/organization/domain",
                {
                    "domain": "shared.customer-domain.com",
                    "expected_version": created.json()["version"],
                    "account_password": "incorrect-password",
                },
            ),
            (
                "POST",
                "/api/organization/domain/rotate-challenge",
                {
                    "expected_version": created.json()["version"],
                    "account_password": "incorrect-password",
                },
            ),
            (
                "PATCH",
                "/api/organization/domain/email-identity",
                {
                    "expected_version": created.json()["version"],
                    "enabled": False,
                    "from_name": "Domain Dispatch",
                    "local_part": "dispatch",
                    "account_password": "incorrect-password",
                },
            ),
            (
                "DELETE",
                "/api/organization/domain",
                {
                    "expected_version": created.json()["version"],
                    "account_password": "incorrect-password",
                },
            ),
        ):
            rejected = client.request(
                method,
                path,
                headers=_bearer(first_token),
                json=payload,
            )
            assert rejected.status_code == 401, rejected.text
        unchanged = client.get(
            "/api/organization/domain",
            headers=_bearer(first_token),
        ).json()
        assert unchanged["version"] == created.json()["version"]
        assert unchanged["domain"] == created.json()["domain"]
        conflict = client.put(
            "/api/organization/domain",
            headers=_bearer(second_token),
            json={
                "domain": "shared.customer-domain.com",
                "account_password": "domain-admin-two-password",
            },
        )
        assert conflict.status_code == 409
        assert client.get(
            "/api/organization/domain",
            headers=_bearer(second_token),
        ).json() is None
        assert client.get(
            "/api/organization/domain",
            headers=_bearer(first_token),
        ).json()["id"] == created.json()["id"]

        with client.app.state.testing_session_local() as db:
            organization = db.get(Organization, 1)
            assert organization is not None
            organization.plan_code = "starter"
            db.commit()
        starter_blocked = client.get(
            "/api/organization/domain",
            headers=_bearer(first_token),
        )
        assert starter_blocked.status_code == 403
        assert client.get(
            "/api/auth/organization-branding/by-domain/shared.customer-domain.com"
        ).status_code == 404
    finally:
        settings.rbac_enforce = original_rbac
        settings.legacy_header_auth = original_legacy
