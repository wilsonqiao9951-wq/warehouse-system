from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.models import AuthSecurityEvent, Organization, User


def _create_user(client, email: str, password: str, role: str = "admin") -> dict:
    response = client.post(
        "/api/users",
        json={
            "name": email.split("@", 1)[0],
            "email": email,
            "role": role,
            "password": password,
        },
    )
    assert response.status_code == 200
    return response.json()


def _login(client, email: str, password: str):
    return client.post(
        "/api/auth/login",
        data={"username": email, "password": password},
    )


def test_login_rate_limit_and_tenant_safe_security_event_read(client):
    original = (
        settings.rbac_enforce,
        settings.legacy_header_auth,
        settings.login_rate_limit_principal_failures,
        settings.login_rate_limit_source_failures,
        settings.login_rate_limit_window_seconds,
    )
    try:
        settings.rbac_enforce = False
        target = _create_user(client, "target@example.com", "target-password")
        auditor = _create_user(client, "auditor@example.com", "auditor-password")
        with client.app.state.testing_session_local() as db:
            db.add(Organization(id=2, name="Other Organization", slug="other"))
            other = User(
                organization_id=2,
                name="Other Admin",
                email="other-admin@example.com",
                role="admin",
                password_hash=hash_password("other-password"),
            )
            db.add(other)
            db.commit()
            db.refresh(other)
            other_id = other.id

        settings.rbac_enforce = True
        settings.legacy_header_auth = False
        settings.login_rate_limit_principal_failures = 3
        settings.login_rate_limit_source_failures = 50
        settings.login_rate_limit_window_seconds = 600

        for _ in range(3):
            assert _login(client, target["email"], "incorrect-password").status_code == 401
        blocked = _login(client, target["email"], "target-password")
        assert blocked.status_code == 429
        assert blocked.headers["retry-after"] == "600"
        assert blocked.json()["detail"] == "Too many login attempts; try again later"

        other_login = _login(client, "other-admin@example.com", "other-password")
        assert other_login.status_code == 200
        auditor_login = _login(client, auditor["email"], "auditor-password")
        assert auditor_login.status_code == 200
        events_response = client.get(
            "/api/auth/security-events",
            headers={"Authorization": f"Bearer {auditor_login.json()['access_token']}"},
        )
        assert events_response.status_code == 200
        events = events_response.json()
        assert sum(row["outcome"] == "invalid_credentials" for row in events) == 3
        assert sum(row["outcome"] == "rate_limited" for row in events) == 1
        assert all(row["user_id"] != other_id for row in events)
        assert all("principal_fingerprint" not in row for row in events)
        assert all("source_fingerprint" not in row for row in events)

        with client.app.state.testing_session_local() as db:
            stored = db.scalars(
                select(AuthSecurityEvent).where(AuthSecurityEvent.user_id == target["id"])
            ).all()
            assert len(stored) == 4
            assert all(len(row.principal_fingerprint) == 64 for row in stored)
            assert all(target["email"] not in row.principal_fingerprint for row in stored)
    finally:
        (
            settings.rbac_enforce,
            settings.legacy_header_auth,
            settings.login_rate_limit_principal_failures,
            settings.login_rate_limit_source_failures,
            settings.login_rate_limit_window_seconds,
        ) = original


def test_password_change_and_revoke_all_invalidate_existing_tokens(client):
    original_rbac = settings.rbac_enforce
    original_legacy = settings.legacy_header_auth
    try:
        settings.rbac_enforce = False
        user = _create_user(client, "session-admin@example.com", "initial-password")
        settings.rbac_enforce = True
        settings.legacy_header_auth = False

        first_login = _login(client, user["email"], "initial-password")
        assert first_login.status_code == 200
        first_headers = {
            "Authorization": f"Bearer {first_login.json()['access_token']}"
        }
        assert client.get("/api/auth/me", headers=first_headers).status_code == 200

        settings.rbac_enforce = False
        changed = client.post(
            f"/api/users/{user['id']}/set-password",
            json={"password": "replacement-password"},
        )
        assert changed.status_code == 204
        settings.rbac_enforce = True

        revoked = client.get("/api/auth/me", headers=first_headers)
        assert revoked.status_code == 401
        assert revoked.json()["detail"] == "Session has been revoked"
        assert _login(client, user["email"], "initial-password").status_code == 401

        second_login = _login(client, user["email"], "replacement-password")
        assert second_login.status_code == 200
        second_headers = {
            "Authorization": f"Bearer {second_login.json()['access_token']}"
        }
        revoke = client.post(
            "/api/auth/sessions/revoke-all",
            json={"account_password": "replacement-password"},
            headers=second_headers,
        )
        assert revoke.status_code == 204
        assert client.get("/api/auth/me", headers=second_headers).status_code == 401

        third_login = _login(client, user["email"], "replacement-password")
        assert third_login.status_code == 200
        third_headers = {
            "Authorization": f"Bearer {third_login.json()['access_token']}"
        }
        events = client.get("/api/auth/security-events", headers=third_headers)
        assert events.status_code == 200
        assert any(
            row["event_type"] == "session_revocation"
            and row["outcome"] == "sessions_revoked"
            for row in events.json()
        )
    finally:
        settings.rbac_enforce = original_rbac
        settings.legacy_header_auth = original_legacy
