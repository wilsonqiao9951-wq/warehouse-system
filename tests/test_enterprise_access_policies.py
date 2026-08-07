from datetime import datetime

from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.models import AuditLog, Organization, User, UserPermissionGrant, UserRole


PASSWORD = "enterprise-access-password"


def _create_user(client, name: str, role: str, headers: dict[str, str] | None = None) -> dict:
    response = client.post(
        "/api/users",
        headers=headers or {},
        json={
            "name": name,
            "email": f"{name}@example.test",
            "role": role,
            "password": PASSWORD,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _headers(user_id: int) -> dict[str, str]:
    return {"X-User-Id": str(user_id)}


def _set_permission(
    client,
    admin_id: int,
    user_id: int,
    code: str,
    effect: str,
    reason: str = "Approved enterprise access change",
):
    return client.put(
        f"/api/users/{user_id}/permissions/{code}",
        headers=_headers(admin_id),
        json={"effect": effect, "reason": reason},
    )


def test_role_defaults_allow_deny_inherit_and_audit(client):
    original_rbac = settings.rbac_enforce
    original_legacy = settings.legacy_header_auth
    try:
        settings.rbac_enforce = False
        admin = _create_user(client, "access-admin", "admin")
        settings.rbac_enforce = True
        settings.legacy_header_auth = True
        manager = _create_user(client, "access-manager", "manager", _headers(admin["id"]))
        warehouse = _create_user(client, "access-warehouse", "warehouse", _headers(admin["id"]))

        manager_matrix = client.get(
            "/api/permissions/me",
            headers=_headers(manager["id"]),
        )
        assert manager_matrix.status_code == 200
        assert "users.read" in manager_matrix.json()["effective_permissions"]
        assert "audit.export" not in manager_matrix.json()["effective_permissions"]

        denied_users = client.get("/api/users", headers=_headers(warehouse["id"]))
        assert denied_users.status_code == 403
        assert denied_users.json()["detail"] == "Permission required: users.read"

        allowed = _set_permission(
            client,
            admin["id"],
            warehouse["id"],
            "users.read",
            "allow",
        )
        assert allowed.status_code == 200, allowed.text
        assert "users.read" in allowed.json()["effective_permissions"]
        assert allowed.json()["overrides"][0]["effect"] == "allow"
        assert client.get("/api/users", headers=_headers(warehouse["id"])).status_code == 200

        denied_manager = _set_permission(
            client,
            admin["id"],
            manager["id"],
            "users.read",
            "deny",
            "Temporarily remove employee directory access",
        )
        assert denied_manager.status_code == 200
        assert "users.read" not in denied_manager.json()["effective_permissions"]
        assert client.get("/api/users", headers=_headers(manager["id"])).status_code == 403

        inherited = _set_permission(
            client,
            admin["id"],
            manager["id"],
            "users.read",
            "inherit",
            "Restore the manager role default",
        )
        assert inherited.status_code == 200
        assert inherited.json()["overrides"] == []
        assert "users.read" in inherited.json()["effective_permissions"]
        assert client.get("/api/users", headers=_headers(manager["id"])).status_code == 200

        audit = client.get(
            "/api/audit-logs/search?action=change_user_permission",
            headers=_headers(admin["id"]),
        )
        assert audit.status_code == 200
        assert audit.json()["total"] == 3
        assert all(
            row["metadata"]["target_user_id"] in {manager["id"], warehouse["id"]}
            for row in audit.json()["items"]
        )
    finally:
        settings.rbac_enforce = original_rbac
        settings.legacy_header_auth = original_legacy


def test_delegated_read_permissions_and_sensitive_management_boundaries(client):
    original_rbac = settings.rbac_enforce
    original_legacy = settings.legacy_header_auth
    try:
        settings.rbac_enforce = False
        admin = _create_user(client, "policy-admin", "admin")
        settings.rbac_enforce = True
        settings.legacy_header_auth = True
        warehouse = _create_user(client, "policy-warehouse", "warehouse", _headers(admin["id"]))

        assert client.get("/api/audit-logs/search", headers=_headers(warehouse["id"])).status_code == 403
        assert client.get("/api/integrations", headers=_headers(warehouse["id"])).status_code == 403
        assert client.get("/api/dashboard/admin/warehouses", headers=_headers(warehouse["id"])).status_code == 403

        for code in ("audit.read", "integrations.read", "reports.read"):
            response = _set_permission(client, admin["id"], warehouse["id"], code, "allow")
            assert response.status_code == 200, response.text

        assert client.get("/api/audit-logs/search", headers=_headers(warehouse["id"])).status_code == 200
        assert client.get("/api/integrations", headers=_headers(warehouse["id"])).status_code == 200
        assert client.get("/api/dashboard/admin/warehouses", headers=_headers(warehouse["id"])).status_code == 200

        create_denied = client.post(
            "/api/integrations",
            headers=_headers(warehouse["id"]),
            json={"name": "Denied ERP", "provider": "erp", "field_mapping": {}},
        )
        assert create_denied.status_code == 403
        assert create_denied.json()["detail"] == "Permission required: integrations.manage"

        grant_manage = _set_permission(
            client,
            admin["id"],
            warehouse["id"],
            "integrations.manage",
            "allow",
        )
        assert grant_manage.status_code == 200
        created = client.post(
            "/api/integrations",
            headers=_headers(warehouse["id"]),
            json={"name": "Delegated ERP", "provider": "erp", "field_mapping": {}},
        )
        assert created.status_code == 200, created.text

        non_admin_change = _set_permission(
            client,
            warehouse["id"],
            warehouse["id"],
            "audit.export",
            "allow",
        )
        assert non_admin_change.status_code == 403
        immutable_admin = _set_permission(
            client,
            admin["id"],
            admin["id"],
            "users.read",
            "deny",
        )
        assert immutable_admin.status_code == 409
        unknown = _set_permission(
            client,
            admin["id"],
            warehouse["id"],
            "unknown.permission",
            "allow",
        )
        assert unknown.status_code == 404
        blank_reason = _set_permission(
            client,
            admin["id"],
            warehouse["id"],
            "audit.export",
            "allow",
            "   ",
        )
        assert blank_reason.status_code == 422
    finally:
        settings.rbac_enforce = original_rbac
        settings.legacy_header_auth = original_legacy


def test_permission_grants_are_tenant_isolated(client):
    original_rbac = settings.rbac_enforce
    original_legacy = settings.legacy_header_auth
    try:
        settings.rbac_enforce = False
        admin = _create_user(client, "tenant-one-policy-admin", "admin")
        settings.rbac_enforce = True
        settings.legacy_header_auth = True

        with client.app.state.testing_session_local() as db:
            tenant_two = Organization(name="Permission Tenant Two", slug="permission-tenant-two")
            db.add(tenant_two)
            db.flush()
            tenant_two_user = User(
                organization_id=tenant_two.id,
                name="Tenant Two Manager",
                email="tenant-two-policy@example.test",
                role=UserRole.MANAGER,
                password_hash=hash_password(PASSWORD),
            )
            db.add(tenant_two_user)
            db.flush()
            db.add(
                UserPermissionGrant(
                    organization_id=tenant_two.id,
                    user_id=tenant_two_user.id,
                    permission_code="audit.read",
                    effect="deny",
                    reason="Tenant two private policy",
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
            )
            db.commit()
            tenant_two_user_id = tenant_two_user.id

        response = client.get(
            f"/api/users/{tenant_two_user_id}/permissions",
            headers=_headers(admin["id"]),
        )
        assert response.status_code == 404
        with client.app.state.testing_session_local() as db:
            tenant_one_grants = db.scalars(
                select(UserPermissionGrant).where(
                    UserPermissionGrant.organization_id == admin["organization_id"]
                )
            ).all()
            assert tenant_one_grants == []
            assert db.scalar(
                select(AuditLog).where(AuditLog.organization_id != admin["organization_id"])
            ) is None
    finally:
        settings.rbac_enforce = original_rbac
        settings.legacy_header_auth = original_legacy
