from sqlalchemy import select

from app.core.config import settings
from app.models import User


def test_bearer_login_me_and_inactive_user(client):
    original_rbac = settings.rbac_enforce
    original_legacy = settings.legacy_header_auth
    try:
        settings.rbac_enforce = False
        created = client.post(
            "/api/users",
            json={
                "name": "Login Admin",
                "email": "login-admin@example.com",
                "role": "admin",
                "password": "correct-password",
            },
        )
        assert created.status_code == 200
        user = created.json()
        assert "password" not in user
        assert "password_hash" not in user
        assert user["is_active"] is True

        settings.rbac_enforce = True
        settings.legacy_header_auth = False

        bad_login = client.post(
            "/api/auth/login",
            data={"username": "login-admin@example.com", "password": "wrong-password"},
        )
        assert bad_login.status_code == 401

        login = client.post(
            "/api/auth/login",
            data={"username": "LOGIN-ADMIN@example.com", "password": "correct-password"},
        )
        assert login.status_code == 200
        auth = login.json()
        assert auth["token_type"] == "bearer"
        assert auth["expires_in"] > 0
        token = auth["access_token"]

        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json()["id"] == user["id"]
        assert me.json()["organization_id"] == 1

        missing = client.get("/api/parts")
        assert missing.status_code == 401
        legacy_rejected = client.get("/api/parts", headers={"X-User-Id": str(user["id"])})
        assert legacy_rejected.status_code == 401
        tampered = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token[:-1]}x"})
        assert tampered.status_code == 401

        with client.app.state.testing_session_local() as db:
            stored_user = db.scalar(select(User).where(User.id == user["id"]))
            assert stored_user is not None
            assert stored_user.password_hash
            stored_user.is_active = False
            db.commit()

        inactive = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert inactive.status_code == 401
    finally:
        settings.rbac_enforce = original_rbac
        settings.legacy_header_auth = original_legacy


def test_admin_can_set_initial_password(client):
    settings.rbac_enforce = False
    created = client.post(
        "/api/users",
        json={"name": "Invited User", "email": "invited@example.com", "role": "engineer"},
    )
    assert created.status_code == 200
    user_id = created.json()["id"]

    no_password_login = client.post(
        "/api/auth/login",
        data={"username": "invited@example.com", "password": "initial-password"},
    )
    assert no_password_login.status_code == 401

    password_set = client.post(
        f"/api/users/{user_id}/set-password",
        json={"password": "initial-password"},
    )
    assert password_set.status_code == 204

    login = client.post(
        "/api/auth/login",
        data={"username": "invited@example.com", "password": "initial-password"},
    )
    assert login.status_code == 200
