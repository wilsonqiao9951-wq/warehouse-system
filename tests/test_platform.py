from sqlalchemy import select

from app.core.config import settings
from app.models import User


def _login(client, email: str, password: str) -> str:
    response = client.post("/api/auth/login", data={"username": email, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


def test_platform_admin_can_onboard_and_suspend_customer(client):
    original_rbac = settings.rbac_enforce
    original_legacy = settings.legacy_header_auth
    try:
        settings.rbac_enforce = False
        platform_user = client.post(
            "/api/users",
            json={
                "name": "Platform Owner",
                "email": "platform@example.com",
                "role": "admin",
                "password": "platform-password",
            },
        ).json()
        customer_admin = client.post(
            "/api/users",
            json={
                "name": "Normal Customer Admin",
                "email": "normal-admin@example.com",
                "role": "admin",
                "password": "customer-password",
            },
        ).json()
        with client.app.state.testing_session_local() as db:
            stored = db.scalar(select(User).where(User.id == platform_user["id"]))
            assert stored is not None
            stored.is_platform_admin = True
            db.commit()

        settings.rbac_enforce = True
        settings.legacy_header_auth = False
        platform_token = _login(client, "platform@example.com", "platform-password")
        normal_token = _login(client, "normal-admin@example.com", "customer-password")

        denied = client.get(
            "/api/platform/organizations",
            headers={"Authorization": f"Bearer {normal_token}"},
        )
        assert denied.status_code == 403

        created = client.post(
            "/api/platform/organizations",
            headers={"Authorization": f"Bearer {platform_token}"},
            json={
                "name": "Acme Service Company",
                "slug": "acme-service",
                "admin_name": "Acme Admin",
                "admin_email": "admin@acme.example",
                "admin_password": "acme-initial-password",
            },
        )
        assert created.status_code == 200
        organization = created.json()
        assert organization["slug"] == "acme-service"
        assert organization["total_users"] == 1
        assert organization["is_active"] is True

        duplicate = client.post(
            "/api/platform/organizations",
            headers={"Authorization": f"Bearer {platform_token}"},
            json={
                "name": "Duplicate Acme",
                "slug": "acme-service",
                "admin_name": "Other Admin",
                "admin_email": "other@acme.example",
                "admin_password": "other-initial-password",
            },
        )
        assert duplicate.status_code == 409

        acme_token = _login(client, "admin@acme.example", "acme-initial-password")
        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {acme_token}"})
        assert me.status_code == 200
        assert me.json()["organization_id"] == organization["id"]
        assert me.json()["is_platform_admin"] is False

        suspended = client.patch(
            f"/api/platform/organizations/{organization['id']}",
            headers={"Authorization": f"Bearer {platform_token}"},
            json={"is_active": False},
        )
        assert suspended.status_code == 200
        assert suspended.json()["is_active"] is False

        blocked_login = client.post(
            "/api/auth/login",
            data={"username": "admin@acme.example", "password": "acme-initial-password"},
        )
        assert blocked_login.status_code == 401
        blocked_existing_token = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {acme_token}"},
        )
        assert blocked_existing_token.status_code == 403
    finally:
        settings.rbac_enforce = original_rbac
        settings.legacy_header_auth = original_legacy
