from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.data_residency import residency_block_reason
from app.models import Organization, OrganizationUsagePeriod, User, UserInvitation, Warehouse


PLAN_DEFAULTS: dict[str, dict[str, int | None]] = {
    "starter": {
        "max_users": 5,
        "max_warehouses": 1,
        "max_vehicle_warehouses": 1,
        "ai_monthly_limit": 0,
        "api_monthly_limit": 0,
    },
    "professional": {
        "max_users": 50,
        "max_warehouses": 10,
        "max_vehicle_warehouses": 50,
        "ai_monthly_limit": 2_000,
        "api_monthly_limit": 10_000,
    },
    "enterprise": {
        "max_users": None,
        "max_warehouses": None,
        "max_vehicle_warehouses": None,
        "ai_monthly_limit": None,
        "api_monthly_limit": None,
    },
}


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def apply_plan_defaults(organization: Organization, plan_code: str) -> None:
    defaults = PLAN_DEFAULTS.get(plan_code)
    if defaults is None:
        raise ValueError("Unsupported commercial plan")
    organization.plan_code = plan_code
    for field_name, value in defaults.items():
        setattr(organization, field_name, value)


def subscription_block_reason(organization: Organization) -> str | None:
    if not organization.is_active:
        return "Organization is inactive"
    if organization.subscription_status == "trialing":
        if not organization.trial_ends_at or organization.trial_ends_at <= datetime.utcnow():
            return "Organization trial has expired"
        return None
    if organization.subscription_status == "active":
        return None
    labels = {
        "past_due": "Organization subscription is past due",
        "suspended": "Organization subscription is suspended",
        "cancelled": "Organization subscription is cancelled",
    }
    return labels.get(
        organization.subscription_status,
        "Organization subscription is unavailable",
    )


def require_subscription_access(
    organization: Organization | None,
    *,
    platform_admin: bool = False,
) -> None:
    if platform_admin:
        return
    if organization is None:
        raise HTTPException(status_code=403, detail="Organization is unavailable")
    reason = subscription_block_reason(organization)
    if reason:
        raise HTTPException(status_code=403, detail=reason)
    reason = residency_block_reason(
        organization.data_residency_region,
        settings.deployment_region,
    )
    if reason:
        raise HTTPException(status_code=403, detail=reason)


def begin_commercial_write(db: Session) -> None:
    """Serialize quota/settings writes on SQLite; other databases use row locks."""
    bind = db.get_bind()
    if bind.dialect.name != "sqlite":
        return
    active_lock_transaction = db.info.get("commercial_write_transaction")
    if (
        active_lock_transaction is not None
        and active_lock_transaction is db.get_transaction()
    ):
        return
    if db.new or db.dirty or db.deleted:
        raise RuntimeError(
            "SQLite commercial lock must be acquired before mutating the session"
        )
    db.rollback()
    db.execute(text("BEGIN IMMEDIATE"))
    db.info["commercial_write_transaction"] = db.get_transaction()


def lock_organization(db: Session, organization_id: int) -> Organization:
    begin_commercial_write(db)
    organization = db.scalar(
        select(Organization)
        .where(Organization.id == organization_id)
        .with_for_update()
    )
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")
    return organization


def current_usage_period(now: datetime | None = None) -> date:
    current = now or _utcnow_naive()
    if current.tzinfo is not None:
        current = current.astimezone(timezone.utc).replace(tzinfo=None)
    return date(current.year, current.month, 1)


def next_usage_period(period_start: date) -> date:
    if period_start.month == 12:
        return date(period_start.year + 1, 1, 1)
    return date(period_start.year, period_start.month + 1, 1)


def organization_usage(
    db: Session,
    organization_id: int,
    *,
    now: datetime | None = None,
) -> dict[str, int | date]:
    now = now or _utcnow_naive()
    period_start = current_usage_period(now)
    active_users = db.scalar(
        select(func.count(User.id)).where(
            User.organization_id == organization_id,
            User.is_active.is_(True),
        )
    ) or 0
    pending_invitations = db.scalar(
        select(func.count(UserInvitation.id)).where(
            UserInvitation.organization_id == organization_id,
            UserInvitation.used_at.is_(None),
            UserInvitation.expires_at > now,
        )
    ) or 0
    active_main_warehouses = db.scalar(
        select(func.count(Warehouse.id)).where(
            Warehouse.organization_id == organization_id,
            Warehouse.is_active.is_(True),
            Warehouse.warehouse_type == "main",
        )
    ) or 0
    active_vehicle_warehouses = db.scalar(
        select(func.count(Warehouse.id)).where(
            Warehouse.organization_id == organization_id,
            Warehouse.is_active.is_(True),
            Warehouse.warehouse_type == "van",
        )
    ) or 0
    monthly_usage = db.scalar(
        select(OrganizationUsagePeriod).where(
            OrganizationUsagePeriod.organization_id == organization_id,
            OrganizationUsagePeriod.period_start == period_start,
        )
    )
    return {
        "active_users": int(active_users),
        "pending_invitations": int(pending_invitations),
        "active_warehouses": int(active_main_warehouses),
        "active_vehicle_warehouses": int(active_vehicle_warehouses),
        "usage_period_start": period_start,
        "ai_monthly_used": monthly_usage.ai_requests if monthly_usage else 0,
        "api_monthly_used": monthly_usage.api_requests if monthly_usage else 0,
    }


def consume_monthly_usage(
    db: Session,
    organization_id: int,
    *,
    ai_requests: int = 0,
    api_requests: int = 0,
    now: datetime | None = None,
) -> OrganizationUsagePeriod:
    """Atomically reserve monthly AI/API capacity in the caller's transaction."""
    if ai_requests < 0 or api_requests < 0 or not (ai_requests or api_requests):
        raise ValueError("Usage increments must be non-negative and non-zero")

    used_at = now or _utcnow_naive()
    if used_at.tzinfo is not None:
        used_at = used_at.astimezone(timezone.utc).replace(tzinfo=None)
    period_start = current_usage_period(used_at)
    organization = lock_organization(db, organization_id)
    usage = db.scalar(
        select(OrganizationUsagePeriod)
        .where(
            OrganizationUsagePeriod.organization_id == organization_id,
            OrganizationUsagePeriod.period_start == period_start,
        )
        .with_for_update()
    )
    current_ai = usage.ai_requests if usage else 0
    current_api = usage.api_requests if usage else 0

    requested = (
        ("AI", current_ai, ai_requests, organization.ai_monthly_limit),
        ("API", current_api, api_requests, organization.api_monthly_limit),
    )
    for label, current, increment, limit in requested:
        if not increment:
            continue
        if limit == 0:
            raise HTTPException(
                status_code=403,
                detail=f"{label} capability is not included in this plan.",
            )
        if limit is not None and current + increment > limit:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"{label} monthly limit reached ({limit}). "
                    f"Usage resets on {next_usage_period(period_start).isoformat()}."
                ),
            )

    if usage is None:
        usage = OrganizationUsagePeriod(
            organization_id=organization_id,
            period_start=period_start,
        )
        db.add(usage)
    if ai_requests:
        usage.ai_requests = current_ai + ai_requests
        usage.last_ai_used_at = used_at
    if api_requests:
        usage.api_requests = current_api + api_requests
        usage.last_api_used_at = used_at
    db.add(usage)
    db.flush()
    return usage


def enforce_user_capacity(
    db: Session,
    organization: Organization,
    *,
    include_pending: bool,
    replacing_email: str | None = None,
) -> None:
    if organization.max_users is None:
        return
    now = datetime.utcnow()
    active_users = db.scalar(
        select(func.count(User.id)).where(
            User.organization_id == organization.id,
            User.is_active.is_(True),
        )
    ) or 0
    pending_invitations = 0
    if include_pending:
        query = select(func.count(UserInvitation.id)).where(
            UserInvitation.organization_id == organization.id,
            UserInvitation.used_at.is_(None),
            UserInvitation.expires_at > now,
        )
        if replacing_email:
            query = query.where(func.lower(UserInvitation.email) != replacing_email.lower())
        pending_invitations = db.scalar(query) or 0
    if active_users + pending_invitations >= organization.max_users:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{organization.plan_code.title()} plan user limit reached "
                f"({organization.max_users})."
            ),
        )


def enforce_warehouse_capacity(
    db: Session,
    organization: Organization,
    warehouse_type: str,
) -> None:
    limit = (
        organization.max_vehicle_warehouses
        if warehouse_type == "van"
        else organization.max_warehouses
    )
    if limit is None:
        return
    current = db.scalar(
        select(func.count(Warehouse.id)).where(
            Warehouse.organization_id == organization.id,
            Warehouse.is_active.is_(True),
            Warehouse.warehouse_type == warehouse_type,
        )
    ) or 0
    if current >= limit:
        label = "vehicle inventory" if warehouse_type == "van" else "warehouse"
        raise HTTPException(
            status_code=409,
            detail=(
                f"{organization.plan_code.title()} plan {label} limit reached "
                f"({limit})."
            ),
        )
