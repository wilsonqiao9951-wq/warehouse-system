from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
import json
import time
from typing import Callable

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import set_platform_database_scope
from app.models import (
    AuditLog,
    BillingLifecycleEvent,
    Organization,
    OrganizationBillingAccount,
    SubscriptionNotice,
)
from app.schemas import BillingWebhookEvent
from app.services.commercial import (
    apply_plan_defaults,
    begin_commercial_write,
    lock_organization,
)


@dataclass(frozen=True)
class BillingReconciliationStats:
    organizations_checked: int = 0
    notices_created: int = 0
    notices_resolved: int = 0


@dataclass(frozen=True)
class _NoticeSpec:
    notice_type: str
    severity: str
    message: str
    effective_at: datetime


def utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def billing_payload_sha256(body: bytes) -> str:
    return sha256(body).hexdigest()


def billing_webhook_signature(body: bytes, timestamp: int, secret: str) -> str:
    signed = str(timestamp).encode("ascii") + b"." + body
    digest = hmac.new(secret.encode("utf-8"), signed, sha256).hexdigest()
    return f"sha256={digest}"


def verify_billing_webhook_signature(
    body: bytes,
    timestamp_header: str | None,
    signature_header: str | None,
    *,
    now_epoch: int | None = None,
) -> None:
    secret = settings.billing_webhook_secret
    if len(secret) < 32:
        raise RuntimeError("Billing webhook secret is not configured safely")
    try:
        timestamp = int(timestamp_header or "")
    except ValueError as exc:
        raise ValueError("Billing webhook timestamp is invalid") from exc
    current = int(time.time()) if now_epoch is None else now_epoch
    tolerance = max(30, settings.billing_webhook_tolerance_seconds)
    if abs(current - timestamp) > tolerance:
        raise ValueError("Billing webhook timestamp is outside the allowed window")
    supplied = signature_header or ""
    expected = billing_webhook_signature(body, timestamp, secret)
    if len(supplied) != len(expected) or not hmac.compare_digest(supplied, expected):
        raise ValueError("Billing webhook signature is invalid")


def _notice_specs(
    organization: Organization,
    account: OrganizationBillingAccount | None,
    *,
    now: datetime,
    window_days: int,
) -> list[_NoticeSpec]:
    specs: list[_NoticeSpec] = []
    window_end = now + timedelta(days=max(1, window_days))
    if organization.subscription_status == "trialing" and organization.trial_ends_at:
        if organization.trial_ends_at <= now:
            specs.append(
                _NoticeSpec(
                    "trial_expired",
                    "critical",
                    "The organization trial has expired and normal access is blocked.",
                    organization.trial_ends_at,
                )
            )
        elif organization.trial_ends_at <= window_end:
            specs.append(
                _NoticeSpec(
                    "trial_ending",
                    "warning",
                    f"The organization trial ends at {organization.trial_ends_at.isoformat()}Z.",
                    organization.trial_ends_at,
                )
            )

    if account and account.cancel_at_period_end and account.current_period_end:
        specs.append(
            _NoticeSpec(
                "cancellation_scheduled",
                "warning",
                f"The subscription is scheduled to cancel at {account.current_period_end.isoformat()}Z.",
                account.current_period_end,
            )
        )
    elif (
        account
        and organization.subscription_status == "active"
        and account.current_period_end
        and now < account.current_period_end <= window_end
    ):
        specs.append(
            _NoticeSpec(
                "renewal_upcoming",
                "info",
                f"The subscription billing period renews at {account.current_period_end.isoformat()}Z.",
                account.current_period_end,
            )
        )
    elif (
        account
        and organization.subscription_status == "active"
        and account.current_period_end
        and account.current_period_end <= now
    ):
        specs.append(
            _NoticeSpec(
                "renewal_overdue",
                "critical",
                "The recorded billing period ended without a newer provider lifecycle event.",
                account.current_period_end,
            )
        )

    status_notice = {
        "past_due": (
            "payment_past_due",
            "critical",
            "The subscription is past due and normal access is blocked.",
        ),
        "suspended": (
            "subscription_suspended",
            "critical",
            "The subscription is suspended and normal access is blocked.",
        ),
        "cancelled": (
            "subscription_cancelled",
            "critical",
            "The subscription is cancelled and normal access is blocked.",
        ),
    }.get(organization.subscription_status)
    if status_notice:
        effective_at = (
            (account.grace_ends_at if account else None)
            or (account.last_event_at if account else None)
            or organization.updated_at
            or now
        )
        specs.append(
            _NoticeSpec(
                status_notice[0],
                status_notice[1],
                status_notice[2],
                effective_at,
            )
        )
    return specs


def reconcile_organization_billing(
    db: Session,
    organization: Organization,
    account: OrganizationBillingAccount | None,
    *,
    now: datetime | None = None,
    source_event_id: int | None = None,
) -> BillingReconciliationStats:
    checked_at = now or utcnow_naive()
    specs = _notice_specs(
        organization,
        account,
        now=checked_at,
        window_days=settings.billing_notice_window_days,
    )
    existing = db.scalars(
        select(SubscriptionNotice).where(
            SubscriptionNotice.organization_id == organization.id
        )
    ).all()
    by_key = {(row.notice_type, row.effective_at): row for row in existing}
    active_keys = {(spec.notice_type, spec.effective_at) for spec in specs}
    created = 0
    resolved = 0

    for spec in specs:
        key = (spec.notice_type, spec.effective_at)
        row = by_key.get(key)
        if row is None:
            db.add(
                SubscriptionNotice(
                    organization_id=organization.id,
                    source_event_id=source_event_id,
                    notice_type=spec.notice_type,
                    status="open",
                    severity=spec.severity,
                    message=spec.message,
                    effective_at=spec.effective_at,
                )
            )
            created += 1
        elif row.status == "resolved":
            row.status = "open"
            row.severity = spec.severity
            row.message = spec.message
            row.source_event_id = source_event_id or row.source_event_id
            row.acknowledged_by = None
            row.acknowledged_at = None
            row.resolved_at = None
            row.version += 1
            db.add(row)
            created += 1

    for row in existing:
        key = (row.notice_type, row.effective_at)
        if row.status != "resolved" and key not in active_keys:
            row.status = "resolved"
            row.resolved_at = checked_at
            row.version += 1
            db.add(row)
            resolved += 1

    db.flush()
    return BillingReconciliationStats(1, created, resolved)


def reconcile_billing_lifecycle(
    session_factory: Callable[[], Session],
    *,
    now: datetime | None = None,
) -> BillingReconciliationStats:
    with session_factory() as db:
        stats = reconcile_all_billing(db, now=now)
        db.commit()
    return stats


def reconcile_all_billing(
    db: Session,
    *,
    now: datetime | None = None,
) -> BillingReconciliationStats:
    checked_at = now or utcnow_naive()
    total_created = 0
    total_resolved = 0
    organizations_checked = 0
    set_platform_database_scope(db)
    begin_commercial_write(db)
    organizations = db.scalars(
        select(Organization).order_by(Organization.id).with_for_update()
    ).all()
    accounts = {
        row.organization_id: row
        for row in db.scalars(select(OrganizationBillingAccount)).all()
    }
    for organization in organizations:
        stats = reconcile_organization_billing(
            db,
            organization,
            accounts.get(organization.id),
            now=checked_at,
        )
        organizations_checked += stats.organizations_checked
        total_created += stats.notices_created
        total_resolved += stats.notices_resolved
    return BillingReconciliationStats(
        organizations_checked,
        total_created,
        total_resolved,
    )


_EVENT_TARGET_STATUS = {
    "trial.started": "trialing",
    "subscription.activated": "active",
    "subscription.renewed": "active",
    "payment.failed": "past_due",
    "subscription.suspended": "suspended",
    "subscription.cancelled": "cancelled",
}


def process_billing_webhook_event(
    db: Session,
    payload: BillingWebhookEvent,
    body: bytes,
    *,
    received_at: datetime | None = None,
    provider: str = "generic",
    account_id: int | None = None,
) -> tuple[BillingLifecycleEvent, Organization, bool]:
    if provider not in {"generic", "stripe"}:
        raise ValueError("Unsupported billing provider")
    received = received_at or utcnow_naive()
    payload_digest = billing_payload_sha256(body)
    begin_commercial_write(db)
    existing = db.scalar(
        select(BillingLifecycleEvent).where(
            BillingLifecycleEvent.provider == provider,
            BillingLifecycleEvent.external_event_id == payload.event_id,
        )
    )
    if existing:
        if not hmac.compare_digest(existing.payload_sha256, payload_digest):
            raise HTTPException(
                status_code=409,
                detail="Billing event identifier was reused with different content",
            )
        organization = db.get(Organization, existing.organization_id)
        if not organization:
            raise HTTPException(status_code=404, detail="Billing organization not found")
        return existing, organization, True

    account_query = select(OrganizationBillingAccount).where(
        OrganizationBillingAccount.provider == provider
    )
    if account_id is not None:
        account_query = account_query.where(OrganizationBillingAccount.id == account_id)
    else:
        account_query = account_query.where(
            OrganizationBillingAccount.external_customer_id == payload.external_customer_id,
            OrganizationBillingAccount.external_subscription_id == payload.external_subscription_id,
        )
    account_ref = db.scalar(account_query)
    if not account_ref:
        raise HTTPException(status_code=404, detail="Billing subscription not found")
    organization = lock_organization(db, account_ref.organization_id)
    account = db.scalar(
        select(OrganizationBillingAccount)
        .where(OrganizationBillingAccount.id == account_ref.id)
        .with_for_update()
    )
    if (
        not account
        or account.provider != provider
        or (
            account.external_customer_id is not None
            and account.external_customer_id != payload.external_customer_id
        )
        or (
            account.external_subscription_id is not None
            and account.external_subscription_id != payload.external_subscription_id
        )
    ):
        raise HTTPException(status_code=409, detail="Billing account changed during processing")

    if payload.plan_code and payload.event_type not in {
        "trial.started",
        "subscription.activated",
        "subscription.renewed",
    }:
        raise HTTPException(
            status_code=422,
            detail="This billing event type cannot change the commercial plan",
        )
    if payload.occurred_at > received + timedelta(
        seconds=max(30, settings.billing_webhook_tolerance_seconds)
    ):
        raise HTTPException(
            status_code=422,
            detail="Billing event occurrence time is too far in the future",
        )
    if (
        payload.event_type == "subscription.cancellation_scheduled"
        and payload.current_period_end is None
        and account.current_period_end is None
    ):
        raise HTTPException(
            status_code=422,
            detail="A scheduled cancellation requires a billing period end",
        )

    if account.external_customer_id is None:
        account.external_customer_id = payload.external_customer_id
    if account.external_subscription_id is None:
        account.external_subscription_id = payload.external_subscription_id

    before_status = organization.subscription_status
    before_plan = organization.plan_code
    is_stale = bool(account.last_event_at and payload.occurred_at <= account.last_event_at)
    processing_status = "ignored_stale" if is_stale else "applied"

    if not is_stale:
        target_status = _EVENT_TARGET_STATUS.get(payload.event_type)
        if target_status:
            organization.subscription_status = target_status
        if payload.plan_code and payload.plan_code != organization.plan_code:
            apply_plan_defaults(organization, payload.plan_code)
        if payload.event_type == "trial.started":
            organization.trial_ends_at = payload.trial_ends_at
        elif payload.event_type in {"subscription.activated", "subscription.renewed"}:
            organization.trial_ends_at = None

        if payload.current_period_start is not None:
            account.current_period_start = payload.current_period_start
            account.current_period_end = payload.current_period_end
        if payload.event_type == "subscription.cancellation_scheduled":
            account.cancel_at_period_end = True
        elif payload.event_type == "subscription.cancellation_reversed":
            account.cancel_at_period_end = False
        elif payload.event_type == "subscription.cancelled":
            account.cancel_at_period_end = False
        elif payload.cancel_at_period_end is not None:
            account.cancel_at_period_end = payload.cancel_at_period_end
        elif payload.event_type in {
            "trial.started",
            "subscription.activated",
            "subscription.renewed",
        }:
            account.cancel_at_period_end = False

        if payload.event_type == "payment.failed":
            account.grace_ends_at = payload.grace_ends_at
        elif payload.event_type in {
            "trial.started",
            "subscription.activated",
            "subscription.renewed",
        }:
            account.grace_ends_at = None
        elif payload.grace_ends_at is not None:
            account.grace_ends_at = payload.grace_ends_at

        account.last_event_at = payload.occurred_at
        account.last_event_id = payload.event_id
        account.version += 1
        db.add(account)
        if (
            before_status != organization.subscription_status
            or before_plan != organization.plan_code
            or payload.event_type == "trial.started"
        ):
            organization.settings_version += 1
            db.add(organization)

    event = BillingLifecycleEvent(
        organization_id=organization.id,
        billing_account_id=account.id,
        provider=provider,
        external_event_id=payload.event_id,
        event_type=payload.event_type,
        processing_status=processing_status,
        payload_sha256=payload_digest,
        before_subscription_status=before_status,
        after_subscription_status=organization.subscription_status,
        before_plan_code=before_plan,
        after_plan_code=organization.plan_code,
        occurred_at=payload.occurred_at,
        received_at=received,
        processed_at=utcnow_naive(),
    )
    db.add(event)
    db.flush()
    db.add(
        AuditLog(
            organization_id=organization.id,
            user_id=None,
            action=(
                "billing_lifecycle_event_applied"
                if processing_status == "applied"
                else "billing_lifecycle_event_ignored_stale"
            ),
            entity_type="billing_lifecycle_event",
            entity_id=event.id,
            metadata_json=json.dumps(
                {
                    "provider": provider,
                    "external_event_id": payload.event_id,
                    "event_type": payload.event_type,
                    "processing_status": processing_status,
                    "before_subscription_status": before_status,
                    "after_subscription_status": organization.subscription_status,
                    "before_plan_code": before_plan,
                    "after_plan_code": organization.plan_code,
                    "payload_sha256": payload_digest,
                },
                separators=(",", ":"),
            ),
            timestamp=utcnow_naive(),
        )
    )
    reconcile_organization_billing(
        db,
        organization,
        account,
        now=received,
        source_event_id=event.id,
    )
    db.commit()
    db.refresh(event)
    db.refresh(organization)
    return event, organization, False
