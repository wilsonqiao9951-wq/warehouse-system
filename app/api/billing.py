from __future__ import annotations

import csv
from datetime import date, datetime
from io import StringIO
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.rbac import (
    Actor,
    get_current_actor,
    require_platform_admin,
    require_roles,
)
from app.core.security import verify_password
from app.models import (
    AuditLog,
    BillingLifecycleEvent,
    Organization,
    OrganizationBillingAccount,
    OrganizationUsagePeriod,
    SubscriptionNotice,
    User,
    UserRole,
)
from app.schemas import (
    BillingAccountRead,
    BillingAccountUpsert,
    BillingLifecycleEventRead,
    BillingReconciliationRead,
    BillingWebhookEvent,
    BillingWebhookResponse,
    CommercialCapacityRead,
    CommercialReportExportRequest,
    CommercialUsagePeriodRead,
    OrganizationBillingOverviewRead,
    OrganizationCommercialReportRead,
    PlatformBillingAccountRead,
    PlatformCommercialReportExportRequest,
    PlatformCommercialReportRow,
    SubscriptionNoticeAcknowledge,
    SubscriptionNoticeRead,
)
from app.services.billing import (
    process_billing_webhook_event,
    reconcile_all_billing,
    reconcile_organization_billing,
    utcnow_naive,
    verify_billing_webhook_signature,
)
from app.services.commercial import current_usage_period, lock_organization, organization_usage


router = APIRouter()


def _previous_month(period_start: date) -> date:
    if period_start.month == 1:
        return date(period_start.year - 1, 12, 1)
    return date(period_start.year, period_start.month - 1, 1)


def _organization_commercial_report(
    db: Session,
    organization: Organization,
    *,
    months: int,
) -> OrganizationCommercialReportRead:
    starts: list[date] = []
    cursor = current_usage_period()
    for _ in range(months):
        starts.append(cursor)
        cursor = _previous_month(cursor)
    recorded = {
        row.period_start: row
        for row in db.scalars(
            select(OrganizationUsagePeriod).where(
                OrganizationUsagePeriod.organization_id == organization.id,
                OrganizationUsagePeriod.period_start.in_(starts),
            )
        ).all()
    }
    usage = organization_usage(db, organization.id)
    periods = []
    for period_start in starts:
        row = recorded.get(period_start)
        periods.append(
            CommercialUsagePeriodRead(
                period_start=period_start,
                ai_requests=row.ai_requests if row else 0,
                api_requests=row.api_requests if row else 0,
                last_ai_used_at=row.last_ai_used_at if row else None,
                last_api_used_at=row.last_api_used_at if row else None,
            )
        )
    return OrganizationCommercialReportRead(
        organization_id=organization.id,
        organization_name=organization.name,
        organization_slug=organization.slug,
        plan_code=organization.plan_code,
        subscription_status=organization.subscription_status,
        generated_at=utcnow_naive(),
        ai_monthly_limit=organization.ai_monthly_limit,
        api_monthly_limit=organization.api_monthly_limit,
        capacity=CommercialCapacityRead(
            active_users=int(usage["active_users"]),
            pending_invitations=int(usage["pending_invitations"]),
            active_warehouses=int(usage["active_warehouses"]),
            active_vehicle_warehouses=int(usage["active_vehicle_warehouses"]),
            max_users=organization.max_users,
            max_warehouses=organization.max_warehouses,
            max_vehicle_warehouses=organization.max_vehicle_warehouses,
        ),
        periods=periods,
    )


def _platform_commercial_rows(
    db: Session,
    period_start: date,
) -> list[PlatformCommercialReportRow]:
    organizations = db.scalars(select(Organization).order_by(Organization.id)).all()
    recorded = {
        row.organization_id: row
        for row in db.scalars(
            select(OrganizationUsagePeriod).where(
                OrganizationUsagePeriod.period_start == period_start
            )
        ).all()
    }
    rows = []
    for organization in organizations:
        capacity = organization_usage(db, organization.id)
        usage = recorded.get(organization.id)
        rows.append(
            PlatformCommercialReportRow(
                organization_id=organization.id,
                organization_name=organization.name,
                organization_slug=organization.slug,
                plan_code=organization.plan_code,
                subscription_status=organization.subscription_status,
                period_start=period_start,
                ai_requests=usage.ai_requests if usage else 0,
                ai_monthly_limit=organization.ai_monthly_limit,
                api_requests=usage.api_requests if usage else 0,
                api_monthly_limit=organization.api_monthly_limit,
                active_users=int(capacity["active_users"]),
                pending_invitations=int(capacity["pending_invitations"]),
                max_users=organization.max_users,
                active_warehouses=int(capacity["active_warehouses"]),
                max_warehouses=organization.max_warehouses,
                active_vehicle_warehouses=int(capacity["active_vehicle_warehouses"]),
                max_vehicle_warehouses=organization.max_vehicle_warehouses,
            )
        )
    return rows


def _safe_csv_cell(value: object) -> object:
    if not isinstance(value, str):
        return value
    if value and (value[0] in "=+-@" or value[0] in "\t\r"):
        return f"'{value}"
    return value


def _csv_download(filename: str, rows: list[list[object]]) -> StreamingResponse:
    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    for row in rows:
        writer.writerow([_safe_csv_cell(value) for value in row])
    content = "\ufeff" + output.getvalue()
    return StreamingResponse(
        iter([content]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _require_account_reauthentication(
    db: Session,
    actor: Actor,
    password: str | None,
) -> None:
    if actor.auth_method == "test":
        return
    if actor.auth_method != "bearer" or actor.user_id is None:
        raise HTTPException(status_code=401, detail="Bearer authentication required")
    user = db.get(User, actor.user_id)
    if not password or not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Account password verification failed")


def _billing_audit(
    db: Session,
    actor: Actor,
    organization_id: int,
    action: str,
    entity_type: str,
    entity_id: int | None,
    metadata: dict,
) -> None:
    db.add(
        AuditLog(
            organization_id=organization_id,
            user_id=actor.user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            metadata_json=json.dumps(
                {
                    "actor_role": actor.role.value,
                    "auth_method": actor.auth_method,
                    **metadata,
                },
                default=str,
                separators=(",", ":"),
            ),
            timestamp=utcnow_naive(),
        )
    )


def _platform_account_read(
    db: Session,
    account: OrganizationBillingAccount,
) -> PlatformBillingAccountRead:
    organization = db.get(Organization, account.organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Billing organization not found")
    open_count = db.scalar(
        select(func.count(SubscriptionNotice.id)).where(
            SubscriptionNotice.organization_id == organization.id,
            SubscriptionNotice.status == "open",
        )
    ) or 0
    return PlatformBillingAccountRead(
        **BillingAccountRead.model_validate(account).model_dump(),
        organization_name=organization.name,
        organization_slug=organization.slug,
        plan_code=organization.plan_code,
        subscription_status=organization.subscription_status,
        open_notice_count=int(open_count),
    )


@router.post(
    "/billing/webhooks/generic",
    response_model=BillingWebhookResponse,
)
async def receive_generic_billing_webhook(
    request: Request,
    x_openpartsflow_timestamp: str | None = Header(
        default=None,
        alias="X-OpenPartsFlow-Timestamp",
    ),
    x_openpartsflow_signature: str | None = Header(
        default=None,
        alias="X-OpenPartsFlow-Signature",
    ),
    db: Session = Depends(get_db),
):
    max_bytes = max(1024, settings.billing_webhook_max_bytes)
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > max_bytes:
            raise HTTPException(status_code=413, detail="Billing webhook payload is too large")
        chunks.append(chunk)
    body = b"".join(chunks)
    try:
        verify_billing_webhook_signature(
            body,
            x_openpartsflow_timestamp,
            x_openpartsflow_signature,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from None
    try:
        payload = BillingWebhookEvent.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=exc.errors(include_input=False),
        ) from None
    event, organization, duplicate = process_billing_webhook_event(db, payload, body)
    return BillingWebhookResponse(
        event_id=event.id,
        external_event_id=event.external_event_id,
        processing_status=event.processing_status,
        duplicate=duplicate,
        subscription_status=(
            event.after_subscription_status
            if duplicate
            else organization.subscription_status
        ),
        plan_code=event.after_plan_code if duplicate else organization.plan_code,
    )


@router.get(
    "/organization/billing",
    response_model=OrganizationBillingOverviewRead,
)
def get_organization_billing(
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    organization = lock_organization(db, actor.organization_id)
    account = db.scalar(select(OrganizationBillingAccount))
    reconcile_organization_billing(db, organization, account)
    db.commit()
    notices = db.scalars(
        select(SubscriptionNotice)
        .order_by(SubscriptionNotice.effective_at.desc(), SubscriptionNotice.id.desc())
        .limit(100)
    ).all()
    return OrganizationBillingOverviewRead(
        organization_id=organization.id,
        plan_code=organization.plan_code,
        subscription_status=organization.subscription_status,
        trial_ends_at=organization.trial_ends_at,
        account=(BillingAccountRead.model_validate(account) if account else None),
        notices=[SubscriptionNoticeRead.model_validate(row) for row in notices],
    )


@router.post(
    "/organization/billing/notices/{notice_id}/acknowledge",
    response_model=SubscriptionNoticeRead,
)
def acknowledge_subscription_notice(
    notice_id: int,
    payload: SubscriptionNoticeAcknowledge,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    lock_organization(db, actor.organization_id)
    row = db.scalar(
        select(SubscriptionNotice)
        .where(SubscriptionNotice.id == notice_id)
        .with_for_update()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Subscription notice not found")
    if row.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Subscription notice version is stale")
    if row.status == "resolved":
        raise HTTPException(status_code=409, detail="Resolved notices cannot be acknowledged")
    if row.status == "open":
        row.status = "acknowledged"
        row.acknowledged_by = actor.user_id
        row.acknowledged_at = utcnow_naive()
        row.version += 1
        db.add(row)
        _billing_audit(
            db,
            actor,
            actor.organization_id,
            "subscription_notice_acknowledged",
            "subscription_notice",
            row.id,
            {"notice_type": row.notice_type, "version": row.version},
        )
        db.commit()
        db.refresh(row)
    return SubscriptionNoticeRead.model_validate(row)


@router.get(
    "/platform/billing/accounts",
    response_model=list[PlatformBillingAccountRead],
)
def list_platform_billing_accounts(
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_platform_admin(actor)
    db.info.pop("organization_id", None)
    accounts = db.scalars(
        select(OrganizationBillingAccount).order_by(OrganizationBillingAccount.id)
    ).all()
    return [_platform_account_read(db, row) for row in accounts]


@router.put(
    "/platform/billing/accounts/{organization_id}",
    response_model=PlatformBillingAccountRead,
)
def put_platform_billing_account(
    organization_id: int,
    payload: BillingAccountUpsert,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_platform_admin(actor)
    _require_account_reauthentication(db, actor, payload.account_password)
    db.info.pop("organization_id", None)
    organization = lock_organization(db, organization_id)
    account = db.scalar(
        select(OrganizationBillingAccount)
        .where(OrganizationBillingAccount.organization_id == organization_id)
        .with_for_update()
    )
    created = account is None
    if account:
        if account.version != payload.expected_version:
            raise HTTPException(status_code=409, detail="Billing account version is stale")
        binding_changed = (
            account.provider != payload.provider
            or account.external_customer_id != payload.external_customer_id
            or account.external_subscription_id != payload.external_subscription_id
        )
        account.provider = payload.provider
        account.external_customer_id = payload.external_customer_id
        account.external_subscription_id = payload.external_subscription_id
        account.current_period_start = payload.current_period_start
        account.current_period_end = payload.current_period_end
        account.cancel_at_period_end = payload.cancel_at_period_end
        account.grace_ends_at = payload.grace_ends_at
        account.updated_by = actor.user_id
        account.version += 1
        if binding_changed:
            account.last_event_at = None
            account.last_event_id = None
    else:
        if payload.expected_version != 0:
            raise HTTPException(status_code=409, detail="Billing account does not exist")
        account = OrganizationBillingAccount(
            organization_id=organization_id,
            provider=payload.provider,
            external_customer_id=payload.external_customer_id,
            external_subscription_id=payload.external_subscription_id,
            current_period_start=payload.current_period_start,
            current_period_end=payload.current_period_end,
            cancel_at_period_end=payload.cancel_at_period_end,
            grace_ends_at=payload.grace_ends_at,
            created_by=actor.user_id,
            updated_by=actor.user_id,
        )
        db.add(account)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Billing provider references are already assigned",
        ) from exc
    _billing_audit(
        db,
        actor,
        organization_id,
        "billing_account_created" if created else "billing_account_updated",
        "organization_billing_account",
        account.id,
        {
            "provider": account.provider,
            "has_customer_reference": bool(account.external_customer_id),
            "has_subscription_reference": bool(account.external_subscription_id),
            "cancel_at_period_end": account.cancel_at_period_end,
            "version": account.version,
        },
    )
    reconcile_organization_billing(db, organization, account)
    db.commit()
    db.refresh(account)
    return _platform_account_read(db, account)


@router.get(
    "/platform/billing/events",
    response_model=list[BillingLifecycleEventRead],
)
def list_platform_billing_events(
    organization_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_platform_admin(actor)
    db.info.pop("organization_id", None)
    query = select(BillingLifecycleEvent)
    if organization_id is not None:
        query = query.where(BillingLifecycleEvent.organization_id == organization_id)
    rows = db.scalars(
        query.order_by(
            BillingLifecycleEvent.received_at.desc(),
            BillingLifecycleEvent.id.desc(),
        ).limit(limit)
    ).all()
    return [BillingLifecycleEventRead.model_validate(row) for row in rows]


@router.get(
    "/platform/billing/notices",
    response_model=list[SubscriptionNoticeRead],
)
def list_platform_subscription_notices(
    organization_id: int | None = Query(default=None, ge=1),
    status: str | None = Query(default=None, pattern="^(open|acknowledged|resolved)$"),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_platform_admin(actor)
    db.info.pop("organization_id", None)
    query = select(SubscriptionNotice)
    if organization_id is not None:
        query = query.where(SubscriptionNotice.organization_id == organization_id)
    if status is not None:
        query = query.where(SubscriptionNotice.status == status)
    rows = db.scalars(
        query.order_by(
            SubscriptionNotice.effective_at.desc(),
            SubscriptionNotice.id.desc(),
        ).limit(limit)
    ).all()
    return [SubscriptionNoticeRead.model_validate(row) for row in rows]


@router.post(
    "/platform/billing/reconcile",
    response_model=BillingReconciliationRead,
)
def reconcile_platform_billing(
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_platform_admin(actor)
    db.info.pop("organization_id", None)
    stats = reconcile_all_billing(db)
    db.commit()
    return BillingReconciliationRead(
        organizations_checked=stats.organizations_checked,
        notices_created=stats.notices_created,
        notices_resolved=stats.notices_resolved,
    )


@router.get(
    "/organization/commercial-report",
    response_model=OrganizationCommercialReportRead,
)
def get_organization_commercial_report(
    months: int = Query(default=12, ge=1, le=36),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    organization = db.get(Organization, actor.organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")
    return _organization_commercial_report(db, organization, months=months)


@router.post("/organization/commercial-report/export")
def export_organization_commercial_report(
    payload: CommercialReportExportRequest,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    _require_account_reauthentication(db, actor, payload.account_password)
    organization = db.get(Organization, actor.organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")
    report = _organization_commercial_report(db, organization, months=payload.months)
    rows: list[list[object]] = [[
        "organization_id",
        "organization_name",
        "organization_slug",
        "plan_code",
        "subscription_status",
        "period_start_utc",
        "ai_requests",
        "current_ai_monthly_limit",
        "api_requests",
        "current_api_monthly_limit",
        "active_users",
        "pending_invitations",
        "current_max_users",
        "active_main_warehouses",
        "current_max_main_warehouses",
        "active_vehicle_inventories",
        "current_max_vehicle_inventories",
        "generated_at_utc",
    ]]
    for period in report.periods:
        rows.append([
            report.organization_id,
            report.organization_name,
            report.organization_slug,
            report.plan_code,
            report.subscription_status,
            period.period_start.isoformat(),
            period.ai_requests,
            report.ai_monthly_limit if report.ai_monthly_limit is not None else "unlimited",
            period.api_requests,
            report.api_monthly_limit if report.api_monthly_limit is not None else "unlimited",
            report.capacity.active_users,
            report.capacity.pending_invitations,
            report.capacity.max_users if report.capacity.max_users is not None else "unlimited",
            report.capacity.active_warehouses,
            report.capacity.max_warehouses if report.capacity.max_warehouses is not None else "unlimited",
            report.capacity.active_vehicle_warehouses,
            report.capacity.max_vehicle_warehouses if report.capacity.max_vehicle_warehouses is not None else "unlimited",
            report.generated_at.isoformat() + "Z",
        ])
    _billing_audit(
        db,
        actor,
        organization.id,
        "organization_commercial_report_exported",
        "commercial_report",
        None,
        {"format": "csv", "months": payload.months, "generated_at": report.generated_at},
    )
    db.commit()
    return _csv_download(
        f"openpartsflow-commercial-usage-{report.organization_slug}.csv",
        rows,
    )


@router.get(
    "/platform/commercial-report",
    response_model=list[PlatformCommercialReportRow],
)
def get_platform_commercial_report(
    period_start: date | None = Query(default=None),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_platform_admin(actor)
    selected = period_start or current_usage_period()
    if selected.day != 1:
        raise HTTPException(status_code=422, detail="Report period must start on day one")
    db.info.pop("organization_id", None)
    return _platform_commercial_rows(db, selected)


@router.post("/platform/commercial-report/export")
def export_platform_commercial_report(
    payload: PlatformCommercialReportExportRequest,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_platform_admin(actor)
    _require_account_reauthentication(db, actor, payload.account_password)
    db.info.pop("organization_id", None)
    report_rows = _platform_commercial_rows(db, payload.period_start)
    rows: list[list[object]] = [[
        "organization_id",
        "organization_name",
        "organization_slug",
        "plan_code",
        "subscription_status",
        "period_start_utc",
        "ai_requests",
        "current_ai_monthly_limit",
        "api_requests",
        "current_api_monthly_limit",
        "active_users",
        "pending_invitations",
        "current_max_users",
        "active_main_warehouses",
        "current_max_main_warehouses",
        "active_vehicle_inventories",
        "current_max_vehicle_inventories",
    ]]
    for row in report_rows:
        rows.append([
            row.organization_id,
            row.organization_name,
            row.organization_slug,
            row.plan_code,
            row.subscription_status,
            row.period_start.isoformat(),
            row.ai_requests,
            row.ai_monthly_limit if row.ai_monthly_limit is not None else "unlimited",
            row.api_requests,
            row.api_monthly_limit if row.api_monthly_limit is not None else "unlimited",
            row.active_users,
            row.pending_invitations,
            row.max_users if row.max_users is not None else "unlimited",
            row.active_warehouses,
            row.max_warehouses if row.max_warehouses is not None else "unlimited",
            row.active_vehicle_warehouses,
            row.max_vehicle_warehouses if row.max_vehicle_warehouses is not None else "unlimited",
        ])
    generated_at = utcnow_naive()
    _billing_audit(
        db,
        actor,
        actor.organization_id,
        "platform_commercial_report_exported",
        "commercial_report",
        None,
        {
            "format": "csv",
            "period_start": payload.period_start,
            "organization_count": len(report_rows),
            "generated_at": generated_at,
        },
    )
    db.commit()
    return _csv_download(
        f"openpartsflow-platform-commercial-{payload.period_start.isoformat()}.csv",
        rows,
    )
