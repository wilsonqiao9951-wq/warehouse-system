from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from urllib.parse import parse_qs, urlparse

from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.database import Base, configure_sqlite_connection
from app.core.security import hash_password
from app.models import AuditLog, Organization, User, UserRole
from app.services.commercial import enforce_user_capacity, lock_organization


def _login(client, email: str, password: str) -> str:
    response = client.post(
        "/api/auth/login",
        data={"username": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _platform_token(client) -> str:
    settings.rbac_enforce = False
    created = client.post(
        "/api/users",
        json={
            "name": "Commercial Platform Owner",
            "email": "commercial-platform@example.test",
            "role": "admin",
            "password": "commercial-platform-password",
        },
    )
    assert created.status_code == 200, created.text
    with client.app.state.testing_session_local() as db:
        user = db.get(User, created.json()["id"])
        assert user is not None
        user.is_platform_admin = True
        db.commit()
    settings.rbac_enforce = True
    settings.legacy_header_auth = False
    return _login(
        client,
        "commercial-platform@example.test",
        "commercial-platform-password",
    )


def test_file_sqlite_serializes_competing_seat_creation(tmp_path):
    database_path = (tmp_path / "commercial-capacity.db").as_posix()
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )
    event.listen(engine, "connect", configure_sqlite_connection)
    Base.metadata.create_all(engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with Session() as db:
        db.add(
            Organization(
                id=1,
                name="Commercial Concurrency",
                slug="commercial-concurrency",
                plan_code="starter",
                max_users=2,
            )
        )
        db.add(
            User(
                organization_id=1,
                name="Existing Administrator",
                email="existing-commercial-admin@example.test",
                role=UserRole.ADMIN,
                is_active=True,
            )
        )
        db.commit()

    barrier = Barrier(2)

    def create_competing_user(index: int) -> str:
        with Session() as db:
            db.info["organization_id"] = 1
            barrier.wait(timeout=5)
            organization = lock_organization(db, 1)
            try:
                enforce_user_capacity(
                    db,
                    organization,
                    include_pending=False,
                )
            except HTTPException as exc:
                db.rollback()
                assert exc.status_code == 409
                return "limit"
            db.add(
                User(
                    organization_id=1,
                    name=f"Competing User {index}",
                    email=f"competing-user-{index}@example.test",
                    role=UserRole.ENGINEER,
                    is_active=True,
                )
            )
            db.commit()
            return "created"

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(create_competing_user, (1, 2)))
        assert sorted(outcomes) == ["created", "limit"]
        with Session() as db:
            db.info["organization_id"] = 1
            active_users = db.scalars(
                select(User).where(User.is_active.is_(True))
            ).all()
            assert len(active_users) == 2
    finally:
        engine.dispose()


def test_branding_is_versioned_public_safe_and_tenant_scoped(client):
    original_rbac = settings.rbac_enforce
    original_legacy = settings.legacy_header_auth
    try:
        settings.rbac_enforce = False
        admin = client.post(
            "/api/users",
            json={
                "name": "Brand Admin",
                "email": "brand-admin@example.test",
                "role": "admin",
                "password": "brand-admin-password",
            },
        ).json()
        client.post(
            "/api/users",
            json={
                "name": "Brand Manager",
                "email": "brand-manager@example.test",
                "role": "manager",
                "password": "brand-manager-password",
            },
        )
        with client.app.state.testing_session_local() as db:
            other = Organization(
                name="Other Brand Tenant",
                slug="other-brand",
                brand_primary_color="#334455",
            )
            db.add(other)
            db.flush()
            db.add(
                User(
                    organization_id=other.id,
                    name="Other Brand Admin",
                    email="other-brand-admin@example.test",
                    role=UserRole.ADMIN,
                    password_hash=hash_password("other-brand-password"),
                    is_active=True,
                )
            )
            db.commit()

        settings.rbac_enforce = True
        settings.legacy_header_auth = False
        admin_token = _login(
            client,
            "brand-admin@example.test",
            "brand-admin-password",
        )
        manager_token = _login(
            client,
            "brand-manager@example.test",
            "brand-manager-password",
        )
        other_token = _login(
            client,
            "other-brand-admin@example.test",
            "other-brand-password",
        )

        initial = client.get(
            "/api/organization/settings",
            headers=_bearer(admin_token),
        )
        assert initial.status_code == 200
        assert initial.json()["settings_version"] == 0
        assert initial.json()["plan_code"] == "professional"

        invalid_logo = client.patch(
            "/api/organization/settings/branding",
            headers=_bearer(admin_token),
            json={
                "expected_version": 0,
                "brand_logo_url": "http://unsafe.example.test/logo.svg",
            },
        )
        assert invalid_logo.status_code == 422

        manager_denied = client.patch(
            "/api/organization/settings/branding",
            headers=_bearer(manager_token),
            json={
                "expected_version": 0,
                "brand_primary_color": "#123456",
            },
        )
        assert manager_denied.status_code == 403

        updated = client.patch(
            "/api/organization/settings/branding",
            headers=_bearer(admin_token),
            json={
                "expected_version": 0,
                "brand_logo_url": "https://cdn.example.test/acme/logo.png",
                "brand_primary_color": "#123456",
                "brand_login_headline": "Welcome to ACME Field Service",
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["settings_version"] == 1
        assert updated.json()["brand_primary_color"] == "#123456"

        stale = client.patch(
            "/api/organization/settings/branding",
            headers=_bearer(admin_token),
            json={
                "expected_version": 0,
                "brand_primary_color": "#abcdef",
            },
        )
        assert stale.status_code == 409

        public = client.get("/api/auth/organization-branding/test")
        assert public.status_code == 200
        public_payload = public.json()
        assert public_payload == {
            "name": "Test Organization",
            "slug": "test",
            "brand_logo_url": "https://cdn.example.test/acme/logo.png",
            "brand_primary_color": "#123456",
            "brand_login_headline": "Welcome to ACME Field Service",
        }
        assert "plan_code" not in public_payload
        assert "max_users" not in public_payload

        other_settings = client.get(
            "/api/organization/settings",
            headers=_bearer(other_token),
        )
        assert other_settings.status_code == 200
        assert other_settings.json()["slug"] == "other-brand"
        assert other_settings.json()["brand_primary_color"] == "#334455"

        with client.app.state.testing_session_local() as db:
            audit = db.scalar(
                select(AuditLog).where(
                    AuditLog.organization_id == 1,
                    AuditLog.user_id == admin["id"],
                    AuditLog.action == "organization_branding_updated",
                )
            )
            assert audit is not None
            assert "brand_primary_color" in (audit.metadata_json or "")
    finally:
        settings.rbac_enforce = original_rbac
        settings.legacy_header_auth = original_legacy


def test_starter_seat_and_warehouse_limits_then_enterprise_override(client):
    original_rbac = settings.rbac_enforce
    original_legacy = settings.legacy_header_auth
    try:
        platform_token = _platform_token(client)
        created = client.post(
            "/api/platform/organizations",
            headers=_bearer(platform_token),
            json={
                "name": "Starter Service Co",
                "slug": "starter-service",
                "admin_name": "Starter Admin",
                "admin_email": "starter-admin@example.test",
                "admin_password": "starter-admin-password",
                "plan_code": "starter",
                "trial_days": 0,
            },
        )
        assert created.status_code == 200, created.text
        organization = created.json()
        assert organization["plan_code"] == "starter"
        assert organization["subscription_status"] == "active"
        assert organization["max_users"] == 5
        assert organization["max_warehouses"] == 1
        assert organization["max_vehicle_warehouses"] == 1
        assert organization["ai_monthly_limit"] == 0
        assert organization["api_monthly_limit"] == 0

        admin_token = _login(
            client,
            "starter-admin@example.test",
            "starter-admin-password",
        )
        invitation_urls: list[str] = []
        for index in range(4):
            invitation = client.post(
                "/api/users/invitations",
                headers=_bearer(admin_token),
                json={
                    "name": f"Starter Engineer {index}",
                    "email": f"starter-engineer-{index}@example.test",
                    "role": "engineer",
                },
            )
            assert invitation.status_code == 200, invitation.text
            invitation_urls.append(invitation.json()["invitation_url"])

        over_limit = client.post(
            "/api/users/invitations",
            headers=_bearer(admin_token),
            json={
                "name": "Too Many Seats",
                "email": "starter-over-limit@example.test",
                "role": "engineer",
            },
        )
        assert over_limit.status_code == 409
        assert "user limit reached" in over_limit.json()["detail"]

        replacement = client.post(
            "/api/users/invitations",
            headers=_bearer(admin_token),
            json={
                "name": "Starter Engineer 0",
                "email": "starter-engineer-0@example.test",
                "role": "engineer",
            },
        )
        assert replacement.status_code == 200
        raw_token = parse_qs(
            urlparse(replacement.json()["invitation_url"]).query
        )["token"][0]
        accepted = client.post(
            "/api/auth/invitations/accept",
            json={
                "token": raw_token,
                "password": "starter-engineer-password",
            },
        )
        assert accepted.status_code == 200, accepted.text
        engineer_id = accepted.json()["id"]

        direct_replacement = client.post(
            "/api/users",
            headers=_bearer(admin_token),
            json={
                "name": "Starter Engineer 1",
                "email": "starter-engineer-1@example.test",
                "role": "warehouse",
                "password": "starter-direct-password",
            },
        )
        assert direct_replacement.status_code == 200, direct_replacement.text

        direct_user = client.post(
            "/api/users",
            headers=_bearer(admin_token),
            json={
                "name": "Direct Over Limit",
                "email": "direct-over-limit@example.test",
                "role": "warehouse",
                "password": "direct-over-limit-password",
            },
        )
        assert direct_user.status_code == 409

        main_warehouse = client.post(
            "/api/warehouses",
            headers=_bearer(admin_token),
            json={"name": "Starter Main", "warehouse_type": "main"},
        )
        assert main_warehouse.status_code == 200, main_warehouse.text
        second_main = client.post(
            "/api/warehouses",
            headers=_bearer(admin_token),
            json={"name": "Starter Main Two", "warehouse_type": "main"},
        )
        assert second_main.status_code == 409
        assert "warehouse limit reached" in second_main.json()["detail"]

        van = client.post(
            "/api/warehouses",
            headers=_bearer(admin_token),
            json={
                "name": "Starter Van",
                "warehouse_type": "van",
                "assigned_user_id": engineer_id,
            },
        )
        assert van.status_code == 200, van.text
        second_van = client.post(
            "/api/warehouses",
            headers=_bearer(admin_token),
            json={
                "name": "Starter Van Two",
                "warehouse_type": "van",
                "assigned_user_id": engineer_id,
            },
        )
        assert second_van.status_code == 409
        assert "vehicle inventory limit reached" in second_van.json()["detail"]

        usage = client.get(
            "/api/organization/settings",
            headers=_bearer(admin_token),
        )
        assert usage.status_code == 200
        assert usage.json()["active_users"] == 3
        assert usage.json()["pending_invitations"] == 2
        assert usage.json()["active_warehouses"] == 1
        assert usage.json()["active_vehicle_warehouses"] == 1

        trial_end = datetime.now(timezone.utc) + timedelta(days=14)
        trialing = client.patch(
            f"/api/platform/organizations/{organization['id']}",
            headers=_bearer(platform_token),
            json={
                "expected_version": organization["settings_version"],
                "subscription_status": "trialing",
                "trial_ends_at": trial_end.isoformat(),
            },
        )
        assert trialing.status_code == 200, trialing.text
        assert trialing.json()["settings_version"] == 1
        assert trialing.json()["subscription_status"] == "trialing"

        enterprise = client.patch(
            f"/api/platform/organizations/{organization['id']}",
            headers=_bearer(platform_token),
            json={
                "expected_version": trialing.json()["settings_version"],
                "plan_code": "enterprise",
                "subscription_status": "active",
                "trial_ends_at": None,
            },
        )
        assert enterprise.status_code == 200, enterprise.text
        assert enterprise.json()["settings_version"] == 2
        assert enterprise.json()["max_users"] is None
        assert enterprise.json()["max_warehouses"] is None

        stale_platform_update = client.patch(
            f"/api/platform/organizations/{organization['id']}",
            headers=_bearer(platform_token),
            json={
                "expected_version": 0,
                "subscription_status": "past_due",
            },
        )
        assert stale_platform_update.status_code == 409

        enterprise_invite = client.post(
            "/api/users/invitations",
            headers=_bearer(admin_token),
            json={
                "name": "Enterprise Extra Seat",
                "email": "enterprise-extra@example.test",
                "role": "warehouse",
            },
        )
        assert enterprise_invite.status_code == 200

        with client.app.state.testing_session_local() as db:
            actions = set(
                db.scalars(
                    select(AuditLog.action).where(
                        AuditLog.organization_id == organization["id"]
                    )
                ).all()
            )
            assert "organization_created" in actions
            assert "organization_subscription_updated" in actions
    finally:
        settings.rbac_enforce = original_rbac
        settings.legacy_header_auth = original_legacy


def test_expired_trial_blocks_password_token_and_api_key_access(client):
    original_rbac = settings.rbac_enforce
    original_legacy = settings.legacy_header_auth
    try:
        settings.rbac_enforce = False
        with client.app.state.testing_session_local() as db:
            trial = Organization(
                name="Expiring Trial Tenant",
                slug="expiring-trial",
                subscription_status="trialing",
                trial_ends_at=datetime.utcnow() + timedelta(days=1),
                brand_login_headline="Trial field service",
            )
            db.add(trial)
            db.flush()
            db.add(
                User(
                    organization_id=trial.id,
                    name="Trial Admin",
                    email="trial-admin@example.test",
                    role=UserRole.ADMIN,
                    password_hash=hash_password("trial-admin-password"),
                    is_active=True,
                )
            )
            db.commit()

        settings.rbac_enforce = True
        settings.legacy_header_auth = False
        token = _login(
            client,
            "trial-admin@example.test",
            "trial-admin-password",
        )
        integration = client.post(
            "/api/integrations",
            headers=_bearer(token),
            json={
                "name": "Trial API",
                "provider": "generic",
                "field_mapping": {},
            },
        )
        assert integration.status_code == 200, integration.text
        api_key = integration.json()["api_key"]

        with client.app.state.testing_session_local() as db:
            trial = db.scalar(
                select(Organization).where(
                    Organization.slug == "expiring-trial"
                )
            )
            assert trial is not None
            trial.trial_ends_at = datetime.utcnow() - timedelta(seconds=1)
            db.commit()

        blocked_login = client.post(
            "/api/auth/login",
            data={
                "username": "trial-admin@example.test",
                "password": "trial-admin-password",
            },
        )
        assert blocked_login.status_code == 403
        assert blocked_login.json()["detail"] == "Organization trial has expired"

        blocked_token = client.get(
            "/api/auth/me",
            headers=_bearer(token),
        )
        assert blocked_token.status_code == 403
        assert blocked_token.json()["detail"] == "Organization trial has expired"

        blocked_api = client.get(
            "/api/external/v1/inventory",
            headers={"X-API-Key": api_key},
        )
        assert blocked_api.status_code == 403
        assert blocked_api.json()["detail"] == "Organization trial has expired"

        public_branding = client.get(
            "/api/auth/organization-branding/expiring-trial"
        )
        assert public_branding.status_code == 200
        assert public_branding.json()["brand_login_headline"] == "Trial field service"
    finally:
        settings.rbac_enforce = original_rbac
        settings.legacy_header_auth = original_legacy
