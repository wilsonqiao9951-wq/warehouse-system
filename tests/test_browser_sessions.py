from fastapi import Response

from app.core.config import settings
from app.services.browser_sessions import (
    SECURE_SESSION_COOKIE,
    browser_session_cookie_name,
    set_browser_session,
)
from app.services.mfa import totp_code


PASSWORD = "correct-browser-password"
TEST_MFA_KEY = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="


def _create_admin(client, email: str = "browser-admin@example.com") -> dict:
    settings.rbac_enforce = False
    response = client.post(
        "/api/users",
        json={
            "name": "Browser Admin",
            "email": email,
            "role": "admin",
            "password": PASSWORD,
        },
    )
    assert response.status_code == 200
    settings.rbac_enforce = True
    settings.legacy_header_auth = False
    return response.json()


def _cookie_login(client, email: str = "browser-admin@example.com"):
    return client.post(
        "/api/auth/login",
        data={"username": email, "password": PASSWORD},
        headers={"X-Session-Mode": "cookie"},
    )


def test_browser_cookie_session_requires_bound_csrf_for_writes(client):
    admin = _create_admin(client)

    login = _cookie_login(client)
    assert login.status_code == 200
    session = login.json()
    assert session["token_type"] == "cookie"
    assert session["user"]["id"] == admin["id"]
    assert "access_token" not in session
    assert len(session["csrf_token"]) >= 40
    set_cookie = login.headers["set-cookie"]
    assert "opf_session=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=strict" in set_cookie
    assert "Path=/" in set_cookie
    assert login.headers["cache-control"] == "no-store"

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["id"] == admin["id"]

    missing = client.post(
        "/api/auth/sessions/revoke-all",
        json={"account_password": PASSWORD},
    )
    assert missing.status_code == 403
    assert missing.json()["detail"] == "CSRF validation failed"

    wrong = client.post(
        "/api/auth/sessions/revoke-all",
        json={"account_password": PASSWORD},
        headers={"X-CSRF-Token": "wrong-csrf-proof"},
    )
    assert wrong.status_code == 403

    revoked = client.post(
        "/api/auth/sessions/revoke-all",
        json={"account_password": PASSWORD},
        headers={"X-CSRF-Token": session["csrf_token"]},
    )
    assert revoked.status_code == 204
    assert "Max-Age=0" in revoked.headers["set-cookie"]
    assert client.get("/api/auth/me").status_code == 401


def test_bearer_clients_remain_compatible_and_take_precedence(client):
    _create_admin(client, "dual-mode-admin@example.com")
    cookie_login = _cookie_login(client, "dual-mode-admin@example.com")
    assert cookie_login.status_code == 200

    bearer_login = client.post(
        "/api/auth/login",
        data={"username": "dual-mode-admin@example.com", "password": PASSWORD},
        headers={"X-Session-Mode": "bearer"},
    )
    assert bearer_login.status_code == 200
    bearer = bearer_login.json()
    assert bearer["token_type"] == "bearer"
    assert bearer["access_token"]

    # A caller supplying Authorization remains a standalone Bearer client even
    # when the user agent also happens to hold a browser session cookie.
    revoked = client.post(
        "/api/auth/sessions/revoke-all",
        json={"account_password": PASSWORD},
        headers={"Authorization": f"Bearer {bearer['access_token']}"},
    )
    assert revoked.status_code == 204


def test_logout_requires_csrf_and_clears_http_only_session(client):
    _create_admin(client, "logout-admin@example.com")
    login = _cookie_login(client, "logout-admin@example.com")
    csrf_token = login.json()["csrf_token"]

    denied = client.post("/api/auth/logout")
    assert denied.status_code == 403
    assert client.get("/api/auth/me").status_code == 200

    logout = client.post(
        "/api/auth/logout",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert logout.status_code == 204
    assert "Max-Age=0" in logout.headers["set-cookie"]
    assert client.get("/api/auth/me").status_code == 401


def test_production_cookie_uses_secure_host_prefix():
    original_environment = settings.app_env
    try:
        settings.app_env = "production"
        response = Response()
        set_browser_session(response, "signed-token", 600)
        cookie = response.headers["set-cookie"]

        assert browser_session_cookie_name() == SECURE_SESSION_COOKIE
        assert cookie.startswith(f"{SECURE_SESSION_COOKIE}=")
        assert "HttpOnly" in cookie
        assert "Secure" in cookie
        assert "SameSite=strict" in cookie
        assert "Domain=" not in cookie
        assert "Path=/" in cookie
    finally:
        settings.app_env = original_environment


def test_invalid_session_mode_is_rejected_without_setting_cookie(client):
    _create_admin(client, "invalid-mode-admin@example.com")
    response = client.post(
        "/api/auth/login",
        data={"username": "invalid-mode-admin@example.com", "password": PASSWORD},
        headers={"X-Session-Mode": "local-storage"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "X-Session-Mode must be bearer or cookie"
    assert "set-cookie" not in response.headers


def test_engineer_cookie_session_remains_bound_to_registered_device(client):
    settings.rbac_enforce = False
    created = client.post(
        "/api/users",
        json={
            "name": "Browser Engineer",
            "email": "browser-engineer@example.com",
            "role": "engineer",
            "password": PASSWORD,
        },
    )
    assert created.status_code == 200
    settings.rbac_enforce = True
    settings.legacy_header_auth = False
    device_token = "d" * 64
    login = client.post(
        "/api/auth/login",
        data={"username": "browser-engineer@example.com", "password": PASSWORD},
        headers={
            "X-Session-Mode": "cookie",
            "X-Device-Id": "engineer-browser-phone",
            "X-Device-Token": device_token,
            "X-Device-Name": "Engineer phone",
        },
    )
    assert login.status_code == 200
    assert login.json()["device_id"] == "engineer-browser-phone"

    assert client.get("/api/auth/me").status_code == 401
    assert client.get(
        "/api/auth/me",
        headers={"X-Device-Token": "wrong-device-secret"},
    ).status_code == 401
    me = client.get(
        "/api/auth/me",
        headers={"X-Device-Token": device_token},
    )
    assert me.status_code == 200
    assert me.json()["id"] == created.json()["id"]


def test_cookie_session_rejects_a_csrf_proof_from_another_session(client):
    _create_admin(client, "csrf-session-admin@example.com")
    first = _cookie_login(client, "csrf-session-admin@example.com")
    first_csrf = first.json()["csrf_token"]
    second = _cookie_login(client, "csrf-session-admin@example.com")
    second_csrf = second.json()["csrf_token"]
    assert first_csrf != second_csrf

    mismatched = client.post(
        "/api/auth/sessions/revoke-all",
        json={"account_password": PASSWORD},
        headers={"X-CSRF-Token": first_csrf},
    )
    assert mismatched.status_code == 403

    matched = client.post(
        "/api/auth/sessions/revoke-all",
        json={"account_password": PASSWORD},
        headers={"X-CSRF-Token": second_csrf},
    )
    assert matched.status_code == 204


def test_mfa_completion_can_issue_a_cookie_session(client):
    original_key = settings.mfa_encryption_keys
    try:
        settings.mfa_encryption_keys = TEST_MFA_KEY
        _create_admin(client, "cookie-mfa-admin@example.com")
        initial = client.post(
            "/api/auth/login",
            data={"username": "cookie-mfa-admin@example.com", "password": PASSWORD},
        )
        bearer = {"Authorization": f"Bearer {initial.json()['access_token']}"}
        enrollment = client.post(
            "/api/auth/mfa/enrollment/start",
            json={"account_password": PASSWORD},
            headers=bearer,
        )
        secret = enrollment.json()["secret"]
        confirmed = client.post(
            "/api/auth/mfa/enrollment/confirm",
            json={"code": totp_code(secret)},
            headers=bearer,
        )
        recovery_code = confirmed.json()["recovery_codes"][0]

        challenge = client.post(
            "/api/auth/login",
            data={"username": "cookie-mfa-admin@example.com", "password": PASSWORD},
            headers={"X-Session-Mode": "cookie"},
        )
        assert challenge.status_code == 202
        assert "set-cookie" not in challenge.headers
        completed = client.post(
            "/api/auth/mfa/login/complete",
            json={
                "challenge_token": challenge.json()["challenge_token"],
                "code": recovery_code,
            },
            headers={"X-Session-Mode": "cookie"},
        )
        assert completed.status_code == 200
        assert completed.json()["token_type"] == "cookie"
        assert "access_token" not in completed.json()
        assert "HttpOnly" in completed.headers["set-cookie"]
        assert client.get("/api/auth/me").status_code == 200
    finally:
        settings.mfa_encryption_keys = original_key


def test_password_confirmed_sensitive_operation_accepts_cookie_session(client):
    _create_admin(client, "cookie-export-admin@example.com")
    login = _cookie_login(client, "cookie-export-admin@example.com")

    exported = client.post(
        "/api/audit-logs/export",
        json={"account_password": PASSWORD},
        headers={"X-CSRF-Token": login.json()["csrf_token"]},
    )
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/csv")
    assert exported.headers["x-content-sha256"]
