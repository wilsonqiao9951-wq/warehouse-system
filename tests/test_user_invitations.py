from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

from sqlalchemy import select

from app.core.config import settings
from app.models import UserInvitation


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
