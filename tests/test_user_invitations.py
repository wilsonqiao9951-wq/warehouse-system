from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

from sqlalchemy import select

from app.core.config import settings
from app.models import AuditLog, Organization, UserInvitation, UserRole
from app.services.password_reset_delivery import InvitationDeliveryError


INVITATION_SETTING_NAMES = (
    "app_env",
    "rbac_enforce",
    "legacy_header_auth",
    "invitation_email_enabled",
    "auth_email_from",
    "smtp_host",
    "smtp_port",
    "smtp_username",
    "smtp_password",
    "smtp_use_starttls",
    "smtp_use_ssl",
    "smtp_timeout_seconds",
)


def _snapshot_invitation_settings() -> dict[str, object]:
    return {name: getattr(settings, name) for name in INVITATION_SETTING_NAMES}


def _restore_invitation_settings(values: dict[str, object]) -> None:
    for name, value in values.items():
        setattr(settings, name, value)


def _configure_invitation_smtp() -> None:
    settings.invitation_email_enabled = True
    settings.auth_email_from = "OpenPartsFlow <security@example.com>"
    settings.smtp_host = "smtp.example.com"
    settings.smtp_port = 587
    settings.smtp_username = "relay-user"
    settings.smtp_password = "secure-relay-password"
    settings.smtp_use_starttls = True
    settings.smtp_use_ssl = False
    settings.smtp_timeout_seconds = 10


def _admin_headers(client, email: str = "invitation-owner@example.com") -> dict[str, str]:
    settings.rbac_enforce = False
    created = client.post(
        "/api/users",
        json={
            "name": "Invitation Owner",
            "email": email,
            "role": "admin",
            "password": "admin-password",
        },
    )
    assert created.status_code == 200
    settings.rbac_enforce = True
    settings.legacy_header_auth = False
    login = client.post(
        "/api/auth/login",
        data={"username": email, "password": "admin-password"},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_admin_invites_user_and_token_is_single_use(client):
    original_rbac = settings.rbac_enforce
    original_legacy = settings.legacy_header_auth
    try:
        settings.rbac_enforce = False
        client.post(
            "/api/users",
            json={
                "name": "Invitation Admin",
                "email": "invite-admin@example.com",
                "role": "admin",
                "password": "admin-password",
            },
        )
        settings.rbac_enforce = True
        settings.legacy_header_auth = False
        login = client.post(
            "/api/auth/login",
            data={"username": "invite-admin@example.com", "password": "admin-password"},
        ).json()
        headers = {"Authorization": f"Bearer {login['access_token']}"}
        created = client.post(
            "/api/users/invitations",
            headers=headers,
            json={"name": "New Engineer", "email": "new-engineer@example.com", "role": "engineer"},
        )
        assert created.status_code == 200
        assert created.json()["delivery_status"] == "manual"
        token = parse_qs(urlparse(created.json()["invitation_url"]).query)["token"][0]

        with client.app.state.testing_session_local() as db:
            invitation = db.scalar(select(UserInvitation))
            assert invitation is not None
            assert token not in invitation.token_hash
            assert len(invitation.token_hash) == 64

        info = client.get(f"/api/auth/invitations/{token}")
        assert info.status_code == 200
        assert info.json()["email"] == "new-engineer@example.com"
        assert info.json()["organization_name"] == "Test Organization"

        accepted = client.post(
            "/api/auth/invitations/accept",
            json={"token": token, "password": "engineer-password"},
        )
        assert accepted.status_code == 200
        assert accepted.json()["organization_id"] == 1
        assert accepted.json()["role"] == "engineer"
        assert client.post(
            "/api/auth/invitations/accept",
            json={"token": token, "password": "another-password"},
        ).status_code == 400
        engineer_login = client.post(
            "/api/auth/login",
            data={"username": "new-engineer@example.com", "password": "engineer-password"},
        )
        assert engineer_login.status_code == 200
    finally:
        settings.rbac_enforce = original_rbac
        settings.legacy_header_auth = original_legacy


def test_expired_invitation_is_rejected(client):
    settings.rbac_enforce = False
    created = client.post(
        "/api/users/invitations",
        json={"name": "Expired User", "email": "expired@example.com", "role": "warehouse"},
    )
    token = parse_qs(urlparse(created.json()["invitation_url"]).query)["token"][0]
    with client.app.state.testing_session_local() as db:
        invitation = db.scalar(select(UserInvitation))
        invitation.expires_at = datetime.utcnow() - timedelta(minutes=1)
        db.commit()
    assert client.get(f"/api/auth/invitations/{token}").status_code == 400


def test_production_invitation_is_delivered_only_to_recipient(client, monkeypatch):
    original = _snapshot_invitation_settings()
    delivered: list[dict[str, str]] = []
    try:
        headers = _admin_headers(client)
        settings.app_env = "production"
        _configure_invitation_smtp()

        def fake_delivery(**kwargs):
            delivered.append(kwargs)

        monkeypatch.setattr("app.api.routes.deliver_invitation_email", fake_delivery)
        response = client.post(
            "/api/users/invitations",
            headers=headers,
            json={
                "name": "Verified Engineer",
                "email": "verified-engineer@example.com",
                "role": "engineer",
            },
        )
        assert response.status_code == 200
        assert response.json()["delivery_status"] == "pending"
        assert response.json()["invitation_url"] is None
        assert len(delivered) == 1
        invitation_url = delivered[0]["invitation_url"]
        raw_token = parse_qs(urlparse(invitation_url).query)["token"][0]
        assert delivered[0]["recipient"] == "verified-engineer@example.com"

        with client.app.state.testing_session_local() as db:
            invitation = db.scalar(select(UserInvitation))
            audit = db.scalar(
                select(AuditLog).where(
                    AuditLog.action == "create_user_invitation"
                )
            )
            assert invitation.delivery_status == "sent"
            assert invitation.delivery_attempt_count == 1
            assert invitation.last_delivery_attempt_at is not None
            assert invitation.delivered_at is not None
            assert invitation.delivery_failure_code is None
            assert raw_token not in invitation.token_hash
            assert audit is not None
            assert "verified-engineer@example.com" not in audit.metadata_json
            assert raw_token not in audit.metadata_json
    finally:
        _restore_invitation_settings(original)


def test_invitation_delivery_failure_records_safe_evidence(client, monkeypatch):
    original = _snapshot_invitation_settings()
    try:
        headers = _admin_headers(client, "failed-invite-owner@example.com")
        settings.app_env = "production"
        _configure_invitation_smtp()

        def failed_delivery(**_kwargs):
            raise InvitationDeliveryError("smtp_connect_error")

        monkeypatch.setattr("app.api.routes.deliver_invitation_email", failed_delivery)
        response = client.post(
            "/api/users/invitations",
            headers=headers,
            json={
                "name": "Delivery Failure",
                "email": "failed-delivery@example.com",
                "role": "warehouse",
            },
        )
        assert response.status_code == 200
        assert response.json()["invitation_url"] is None
        with client.app.state.testing_session_local() as db:
            invitation = db.scalar(select(UserInvitation))
            assert invitation.delivery_status == "failed"
            assert invitation.delivery_attempt_count == 1
            assert invitation.delivery_failure_code == "smtp_connect_error"
            assert invitation.last_delivery_attempt_at is not None
            assert invitation.delivered_at is None
    finally:
        _restore_invitation_settings(original)


def test_production_without_invitation_delivery_fails_closed(client):
    original = _snapshot_invitation_settings()
    try:
        headers = _admin_headers(client, "disabled-invite-owner@example.com")
        settings.app_env = "production"
        settings.invitation_email_enabled = False
        response = client.post(
            "/api/users/invitations",
            headers=headers,
            json={
                "name": "No Delivery",
                "email": "no-delivery@example.com",
                "role": "engineer",
            },
        )
        assert response.status_code == 503
        assert response.json()["detail"] == "Invitation email delivery is not configured"
        with client.app.state.testing_session_local() as db:
            assert db.scalar(select(UserInvitation)) is None
    finally:
        _restore_invitation_settings(original)


def test_reissuing_invitation_never_invalidates_another_tenant(client):
    original = _snapshot_invitation_settings()
    try:
        settings.app_env = "test"
        headers = _admin_headers(client, "tenant-invite-owner@example.com")
        first = client.post(
            "/api/users/invitations",
            headers=headers,
            json={"name": "Tenant One", "email": "shared@example.com", "role": "engineer"},
        )
        assert first.status_code == 200
        with client.app.state.testing_session_local() as db:
            db.add(Organization(id=2, name="Other Tenant", slug="other-tenant"))
            db.add(
                UserInvitation(
                    organization_id=2,
                    email="shared@example.com",
                    name="Tenant Two",
                    role=UserRole.WAREHOUSE,
                    token_hash="a" * 64,
                    delivery_status="manual",
                    expires_at=datetime.utcnow() + timedelta(hours=24),
                )
            )
            db.commit()

        replacement = client.post(
            "/api/users/invitations",
            headers=headers,
            json={"name": "Tenant One Again", "email": "shared@example.com", "role": "manager"},
        )
        assert replacement.status_code == 200
        with client.app.state.testing_session_local() as db:
            invitations = db.scalars(
                select(UserInvitation).order_by(UserInvitation.id)
            ).all()
            tenant_one = [row for row in invitations if row.organization_id == 1]
            tenant_two = [row for row in invitations if row.organization_id == 2]
            assert tenant_one[0].used_at is not None
            assert tenant_one[1].used_at is None
            assert tenant_two[0].used_at is None
    finally:
        _restore_invitation_settings(original)
