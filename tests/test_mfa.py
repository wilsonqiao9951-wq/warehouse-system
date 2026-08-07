from datetime import datetime, timezone

from sqlalchemy import select

from app.core.config import settings
from app.models import AuthSecurityEvent, User
from app.services.data_exports import _row_payload
from app.services.mfa import (
    MfaConfigurationError,
    TOTP_PERIOD_SECONDS,
    decrypt_totp_secret,
    encrypt_totp_secret,
    totp_code,
)


TEST_MFA_KEY = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="
PASSWORD = "correct-password"


def _create_user(client, *, email: str, role: str = "admin") -> dict:
    response = client.post(
        "/api/users",
        json={
            "name": email.split("@", 1)[0],
            "email": email,
            "role": role,
            "password": PASSWORD,
        },
    )
    assert response.status_code == 200
    return response.json()


def _login(client, email: str):
    return client.post(
        "/api/auth/login",
        data={"username": email, "password": PASSWORD},
    )


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_admin_mfa_enrollment_login_replay_recovery_and_disable(client):
    original = (settings.rbac_enforce, settings.legacy_header_auth, settings.mfa_encryption_keys)
    try:
        settings.rbac_enforce = False
        admin = _create_user(client, email="mfa-admin@example.com")
        settings.rbac_enforce = True
        settings.legacy_header_auth = False
        settings.mfa_encryption_keys = TEST_MFA_KEY

        initial_login = _login(client, admin["email"])
        assert initial_login.status_code == 200
        initial_token = initial_login.json()["access_token"]
        headers = _bearer(initial_token)

        status = client.get("/api/auth/mfa/status", headers=headers)
        assert status.status_code == 200
        assert status.json() == {
            "eligible": True,
            "available": True,
            "enabled": False,
            "enabled_at": None,
            "enrollment_pending": False,
        }

        wrong_password = client.post(
            "/api/auth/mfa/enrollment/start",
            json={"account_password": "incorrect-password"},
            headers=headers,
        )
        assert wrong_password.status_code == 401

        started = client.post(
            "/api/auth/mfa/enrollment/start",
            json={"account_password": PASSWORD},
            headers=headers,
        )
        assert started.status_code == 200
        secret = started.json()["secret"]
        assert started.json()["provisioning_uri"].startswith("otpauth://totp/")
        assert secret in started.json()["provisioning_uri"]

        with client.app.state.testing_session_local() as db:
            stored = db.get(User, admin["id"])
            assert stored is not None
            assert stored.mfa_secret_encrypted
            assert secret not in stored.mfa_secret_encrypted
            export_payload = _row_payload(stored)
            assert "password_hash" not in export_payload
            assert "mfa_secret_encrypted" not in export_payload
            assert "mfa_recovery_codes_json" not in export_payload
            assert "mfa_last_used_step" not in export_payload

        confirmed = client.post(
            "/api/auth/mfa/enrollment/confirm",
            json={"code": totp_code(secret)},
            headers=headers,
        )
        assert confirmed.status_code == 200
        recovery_codes = confirmed.json()["recovery_codes"]
        assert len(recovery_codes) == 10
        assert len(set(recovery_codes)) == 10
        assert client.get("/api/auth/me", headers=headers).status_code == 401

        challenged = _login(client, admin["email"])
        assert challenged.status_code == 202
        challenge = challenged.json()["challenge_token"]
        assert challenged.json()["mfa_required"] is True
        assert "access_token" not in challenged.json()
        assert client.get("/api/auth/me", headers=_bearer(challenge)).status_code == 401

        invalid = client.post(
            "/api/auth/mfa/login/complete",
            json={"challenge_token": challenge, "code": "000000"},
        )
        assert invalid.status_code == 401

        current_step = int(datetime.now(timezone.utc).timestamp()) // TOTP_PERIOD_SECONDS
        next_step_code = totp_code(secret, step=current_step + 1)
        completed = client.post(
            "/api/auth/mfa/login/complete",
            json={"challenge_token": challenge, "code": next_step_code},
        )
        assert completed.status_code == 200
        mfa_token = completed.json()["access_token"]
        assert client.get("/api/auth/me", headers=_bearer(mfa_token)).status_code == 200

        replayed = client.post(
            "/api/auth/mfa/login/complete",
            json={"challenge_token": challenge, "code": next_step_code},
        )
        assert replayed.status_code == 401

        disabled = client.post(
            "/api/auth/mfa/disable",
            json={"account_password": PASSWORD, "code": recovery_codes[0]},
            headers=_bearer(mfa_token),
        )
        assert disabled.status_code == 204
        assert client.get("/api/auth/me", headers=_bearer(mfa_token)).status_code == 401
        assert _login(client, admin["email"]).status_code == 200

        with client.app.state.testing_session_local() as db:
            stored = db.get(User, admin["id"])
            assert stored is not None
            assert stored.mfa_secret_encrypted is None
            assert stored.mfa_recovery_codes_json is None
            events = db.scalars(
                select(AuthSecurityEvent).where(AuthSecurityEvent.user_id == admin["id"])
            ).all()
            outcomes = {event.outcome for event in events if event.event_type == "mfa"}
            assert {
                "mfa_challenge_required",
                "mfa_success",
                "mfa_invalid",
                "mfa_enrolled",
                "mfa_disabled",
            }.issubset(outcomes)
            assert all(len(event.principal_fingerprint) == 64 for event in events)
    finally:
        settings.rbac_enforce, settings.legacy_header_auth, settings.mfa_encryption_keys = original


def test_non_admin_cannot_enroll_and_mfa_failures_are_rate_limited(client):
    original = (
        settings.rbac_enforce,
        settings.legacy_header_auth,
        settings.mfa_encryption_keys,
        settings.mfa_max_attempts,
    )
    try:
        settings.rbac_enforce = False
        engineer = _create_user(client, email="mfa-engineer@example.com", role="engineer")
        admin = _create_user(client, email="mfa-limited@example.com")
        settings.rbac_enforce = True
        settings.legacy_header_auth = False
        settings.mfa_encryption_keys = TEST_MFA_KEY
        settings.mfa_max_attempts = 3

        engineer_login = _login(client, engineer["email"])
        denied = client.post(
            "/api/auth/mfa/enrollment/start",
            json={"account_password": PASSWORD},
            headers=_bearer(engineer_login.json()["access_token"]),
        )
        assert denied.status_code == 403

        admin_login = _login(client, admin["email"])
        admin_headers = _bearer(admin_login.json()["access_token"])
        started = client.post(
            "/api/auth/mfa/enrollment/start",
            json={"account_password": PASSWORD},
            headers=admin_headers,
        )
        secret = started.json()["secret"]
        assert client.post(
            "/api/auth/mfa/enrollment/confirm",
            json={"code": totp_code(secret)},
            headers=admin_headers,
        ).status_code == 200

        challenge = _login(client, admin["email"]).json()["challenge_token"]
        for _ in range(3):
            response = client.post(
                "/api/auth/mfa/login/complete",
                json={"challenge_token": challenge, "code": "111111"},
            )
            assert response.status_code == 401
        limited = client.post(
            "/api/auth/mfa/login/complete",
            json={"challenge_token": challenge, "code": "222222"},
        )
        assert limited.status_code == 429
        assert limited.headers["retry-after"] == str(settings.mfa_challenge_expire_minutes * 60)
    finally:
        (
            settings.rbac_enforce,
            settings.legacy_header_auth,
            settings.mfa_encryption_keys,
            settings.mfa_max_attempts,
        ) = original


def test_totp_matches_rfc_6238_sha1_vector_truncated_to_six_digits():
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    assert totp_code(secret, step=1) == "287082"


def test_mfa_secret_encryption_detects_tampering_and_supports_key_rotation():
    original = settings.mfa_encryption_keys
    second_key = "Hx4dHBsaGRgXFhUUExIREA8ODQwLCgkIBwYFBAMCAQA="
    try:
        settings.mfa_encryption_keys = TEST_MFA_KEY
        old_ciphertext = encrypt_totp_secret("OLDSECRET")
        assert decrypt_totp_secret(old_ciphertext) == "OLDSECRET"

        settings.mfa_encryption_keys = f"{second_key},{TEST_MFA_KEY}"
        assert decrypt_totp_secret(old_ciphertext) == "OLDSECRET"
        new_ciphertext = encrypt_totp_secret("NEWSECRET")
        assert decrypt_totp_secret(new_ciphertext) == "NEWSECRET"

        settings.mfa_encryption_keys = TEST_MFA_KEY
        try:
            decrypt_totp_secret(new_ciphertext)
            assert False, "new ciphertext must require the new primary key"
        except MfaConfigurationError:
            pass

        settings.mfa_encryption_keys = f"{second_key},{TEST_MFA_KEY}"
        tampered = new_ciphertext[:-1] + ("A" if new_ciphertext[-1] != "A" else "B")
        try:
            decrypt_totp_secret(tampered)
            assert False, "authenticated encryption must reject tampering"
        except MfaConfigurationError:
            pass
    finally:
        settings.mfa_encryption_keys = original
