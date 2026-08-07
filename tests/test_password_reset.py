from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

from sqlalchemy import select

from app.core.config import settings
from app.models import AuthSecurityEvent, PasswordResetToken, User
from app.services.data_exports import _row_payload
from app.services.password_reset_delivery import PasswordResetDeliveryError


RESET_SETTING_NAMES = (
    "app_env",
    "rbac_enforce",
    "legacy_header_auth",
    "password_reset_email_enabled",
    "auth_email_from",
    "smtp_host",
    "smtp_port",
    "smtp_username",
    "smtp_password",
    "smtp_use_starttls",
    "smtp_use_ssl",
    "smtp_timeout_seconds",
    "password_reset_principal_requests",
    "password_reset_source_requests",
    "password_reset_rate_limit_window_seconds",
)


def _snapshot_settings() -> dict[str, object]:
    return {name: getattr(settings, name) for name in RESET_SETTING_NAMES}


def _restore_settings(values: dict[str, object]) -> None:
    for name, value in values.items():
        setattr(settings, name, value)


def _create_user(client, email: str, password: str = "initial-password") -> dict:
    settings.rbac_enforce = False
    response = client.post(
        "/api/users",
        json={
            "name": "Reset User",
            "email": email,
            "role": "admin",
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


def _token_from_url(url: str) -> str:
    return parse_qs(urlparse(url).query)["token"][0]


def _configure_smtp() -> None:
    settings.password_reset_email_enabled = True
    settings.auth_email_from = "OpenPartsFlow <security@example.com>"
    settings.smtp_host = "smtp.example.com"
    settings.smtp_port = 587
    settings.smtp_username = "relay-user"
    settings.smtp_password = "secure-relay-password"
    settings.smtp_use_starttls = True
    settings.smtp_use_ssl = False
    settings.smtp_timeout_seconds = 10


def test_manual_password_reset_is_single_use_and_revokes_old_sessions(client):
    original = _snapshot_settings()
    try:
        user = _create_user(client, "reset@example.com")
        settings.app_env = "test"
        settings.password_reset_email_enabled = False
        settings.rbac_enforce = True
        settings.legacy_header_auth = False

        old_login = _login(client, user["email"], "initial-password")
        assert old_login.status_code == 200
        old_headers = {
            "Authorization": f"Bearer {old_login.json()['access_token']}"
        }

        requested = client.post(
            "/api/auth/password-reset/request",
            json={"email": "RESET@example.com"},
        )
        unknown = client.post(
            "/api/auth/password-reset/request",
            json={"email": "unknown@example.com"},
        )
        assert requested.status_code == unknown.status_code == 202
        assert requested.json()["message"] == unknown.json()["message"]
        assert requested.json()["reset_url"]
        assert unknown.json()["reset_url"] is None
        raw_token = _token_from_url(requested.json()["reset_url"])

        with client.app.state.testing_session_local() as db:
            row = db.scalar(select(PasswordResetToken))
            assert row is not None
            assert row.delivery_status == "manual"
            assert raw_token != row.token_hash
            assert len(row.token_hash) == 64
            exported = _row_payload(row)
            assert "token_hash" not in exported
            assert "principal_fingerprint" not in exported
            assert "source_fingerprint" not in exported

        completed = client.post(
            "/api/auth/password-reset/complete",
            json={"token": raw_token, "password": "replacement-password"},
        )
        assert completed.status_code == 204
        replay = client.post(
            "/api/auth/password-reset/complete",
            json={"token": raw_token, "password": "another-password"},
        )
        assert replay.status_code == 400
        assert client.get("/api/auth/me", headers=old_headers).status_code == 401
        assert _login(client, user["email"], "initial-password").status_code == 401
        assert _login(client, user["email"], "replacement-password").status_code == 200

        with client.app.state.testing_session_local() as db:
            stored_user = db.get(User, user["id"])
            row = db.scalar(select(PasswordResetToken))
            events = db.scalars(
                select(AuthSecurityEvent).where(
                    AuthSecurityEvent.event_type == "password_reset"
                )
            ).all()
            assert stored_user.auth_version == 1
            assert row.used_at is not None
            assert {event.outcome for event in events} >= {
                "reset_requested",
                "reset_request_ignored",
                "reset_completed",
                "reset_rejected",
            }
    finally:
        _restore_settings(original)


def test_new_request_invalidates_old_token_and_rate_limit_stays_generic(client):
    original = _snapshot_settings()
    try:
        user = _create_user(client, "supersede@example.com")
        settings.app_env = "test"
        settings.password_reset_email_enabled = False
        settings.password_reset_principal_requests = 2
        settings.password_reset_source_requests = 20
        settings.rbac_enforce = True

        first = client.post(
            "/api/auth/password-reset/request", json={"email": user["email"]}
        )
        second = client.post(
            "/api/auth/password-reset/request", json={"email": user["email"]}
        )
        limited = client.post(
            "/api/auth/password-reset/request", json={"email": user["email"]}
        )
        assert first.status_code == second.status_code == limited.status_code == 202
        assert first.json()["reset_url"]
        assert second.json()["reset_url"]
        assert limited.json()["reset_url"] is None
        assert client.post(
            "/api/auth/password-reset/complete",
            json={
                "token": _token_from_url(first.json()["reset_url"]),
                "password": "replacement-password",
            },
        ).status_code == 400

        second_token = _token_from_url(second.json()["reset_url"])
        with client.app.state.testing_session_local() as db:
            active = db.scalar(
                select(PasswordResetToken).where(
                    PasswordResetToken.token_hash.is_not(None),
                    PasswordResetToken.invalidated_at.is_(None),
                )
            )
            active.expires_at = datetime.utcnow() - timedelta(seconds=1)
            db.commit()
        assert client.post(
            "/api/auth/password-reset/complete",
            json={"token": second_token, "password": "replacement-password"},
        ).status_code == 400

        with client.app.state.testing_session_local() as db:
            assert len(db.scalars(select(PasswordResetToken)).all()) == 2
    finally:
        _restore_settings(original)


def test_production_smtp_delivery_hides_token_and_records_result(client, monkeypatch):
    original = _snapshot_settings()
    delivered: list[str] = []
    try:
        user = _create_user(client, "mail-reset@example.com")
        settings.app_env = "production"
        settings.rbac_enforce = True
        _configure_smtp()

        def fake_delivery(**kwargs):
            delivered.append(kwargs["reset_url"])

        monkeypatch.setattr("app.api.routes.deliver_password_reset_email", fake_delivery)
        configuration = client.get("/api/auth/password-reset/configuration")
        assert configuration.status_code == 200
        assert configuration.json() == {"available": True, "expires_in_minutes": 30}

        response = client.post(
            "/api/auth/password-reset/request", json={"email": user["email"]}
        )
        unknown = client.post(
            "/api/auth/password-reset/request", json={"email": "unknown-mail@example.com"}
        )
        assert response.status_code == 202
        assert unknown.status_code == 202
        assert response.json() == unknown.json()
        assert response.json()["reset_url"] is None
        assert len(delivered) == 1
        assert _token_from_url(delivered[0])
        with client.app.state.testing_session_local() as db:
            row = db.scalar(select(PasswordResetToken))
            assert row.delivery_status == "sent"
            assert row.delivery_attempted_at is not None
            assert row.failure_code is None

        delivered.clear()

        def failed_delivery(**_kwargs):
            raise PasswordResetDeliveryError("smtp_connect_error")

        monkeypatch.setattr("app.api.routes.deliver_password_reset_email", failed_delivery)
        failed = client.post(
            "/api/auth/password-reset/request", json={"email": user["email"]}
        )
        assert failed.status_code == 202
        with client.app.state.testing_session_local() as db:
            latest = db.scalars(
                select(PasswordResetToken).order_by(PasswordResetToken.id.desc())
            ).first()
            assert latest.delivery_status == "failed"
            assert latest.failure_code == "smtp_connect_error"
    finally:
        _restore_settings(original)


def test_production_without_delivery_fails_closed_for_every_email(client):
    original = _snapshot_settings()
    try:
        _create_user(client, "disabled-reset@example.com")
        settings.app_env = "production"
        settings.password_reset_email_enabled = False
        settings.rbac_enforce = True
        configuration = client.get("/api/auth/password-reset/configuration")
        assert configuration.status_code == 200
        assert configuration.json()["available"] is False
        for email in ("disabled-reset@example.com", "unknown@example.com"):
            response = client.post(
                "/api/auth/password-reset/request", json={"email": email}
            )
            assert response.status_code == 503
            assert response.json()["detail"] == "Password reset delivery is not configured"
    finally:
        _restore_settings(original)
