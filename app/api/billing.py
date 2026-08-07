from __future__ import annotations

import csv
from datetime import date, datetime, timedelta
from hashlib import sha256
from io import StringIO
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy import func, or_, select
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
    StripeBillingOperation,
    StripeWebhookReceipt,
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
    StripeBillingOperationRead,
    StripeCheckoutRequest,
    StripePortalSessionRequest,
    StripeRedirectSessionRead,
    StripeRefundRead,
    StripeRefundRequest,
)
from app.services.billing import (
    process_billing_webhook_event,
    reconcile_all_billing,
    reconcile_organization_billing,
    utcnow_naive,
    verify_billing_webhook_signature,
)
from app.services.commercial import current_usage_period, lock_organization, organization_usage
from app.services.stripe_billing import (
    StripeConfigurationError,
    StripeRequestError,
    configured_price_ids,
    require_stripe_configuration,
    stripe_api_get,
    stripe_api_post,
    stripe_plan_for_price,
    stripe_redirect_url,
    utc_from_epoch,
    verify_stripe_signature,
)


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


def _stripe_failure(exc: StripeRequestError) -> HTTPException:
    status = 503 if exc.code == "stripe_unavailable" else 502
    return HTTPException(status_code=status, detail=f"Stripe request failed: {exc.code}")


def _stripe_request_digest(operation_type: str, values: dict[str, object]) -> str:
    safe = {"operation_type": operation_type, **values}
    return sha256(
        json.dumps(safe, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _existing_stripe_operation(
    db: Session,
    organization_id: int,
    client_request_id: str,
    request_digest: str,
) -> StripeBillingOperation | None:
    operation = db.scalar(
        select(StripeBillingOperation).where(
            StripeBillingOperation.organization_id == organization_id,
            StripeBillingOperation.client_request_id == client_request_id,
        )
    )
    if operation and operation.request_sha256 != request_digest:
        raise HTTPException(
            status_code=409,
            detail="Billing request identifier was reused with different content",
        )
    return operation


def _new_stripe_operation(
    db: Session,
    actor: Actor,
    account: OrganizationBillingAccount | None,
    client_request_id: str,
    operation_type: str,
    request_digest: str,
    *,
    organization_id: int | None = None,
    target_plan_code: str | None = None,
    amount_minor: int | None = None,
) -> StripeBillingOperation:
    target_organization_id = organization_id or actor.organization_id
    operation = StripeBillingOperation(
        organization_id=target_organization_id,
        billing_account_id=account.id if account else None,
        requested_by=actor.user_id,
        client_request_id=client_request_id,
        operation_type=operation_type,
        status="pending",
        request_sha256=request_digest,
        target_plan_code=target_plan_code,
        amount_minor=amount_minor,
    )
    db.add(operation)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = _existing_stripe_operation(
            db, target_organization_id, client_request_id, request_digest
        )
        if existing:
            return existing
        raise HTTPException(status_code=409, detail="Billing request already exists") from exc
    db.refresh(operation)
    return operation


def _complete_stripe_operation(
    db: Session,
    actor: Actor,
    operation: StripeBillingOperation,
    *,
    external_object_id: str | None,
    external_request_id: str | None,
    failure_code: str | None = None,
) -> None:
    operation.status = "failed" if failure_code else "succeeded"
    operation.external_object_id = external_object_id
    operation.external_request_id = external_request_id
    operation.failure_code = failure_code
    operation.completed_at = utcnow_naive()
    db.add(operation)
    _billing_audit(
        db,
        actor,
        operation.organization_id,
        f"stripe_{operation.operation_type}_{operation.status}",
        "stripe_billing_operation",
        operation.id,
        {
            "operation_type": operation.operation_type,
            "status": operation.status,
            "target_plan_code": operation.target_plan_code,
            "amount_minor": operation.amount_minor,
            "external_object_id": external_object_id,
            "external_request_id": external_request_id,
            "failure_code": failure_code,
            "request_sha256": operation.request_sha256,
        },
    )
    db.commit()


def _stripe_account_for_org(
    db: Session,
    organization_id: int,
    *,
    create: bool,
    actor: Actor | None = None,
) -> OrganizationBillingAccount | None:
    account = db.scalar(
        select(OrganizationBillingAccount)
        .where(OrganizationBillingAccount.organization_id == organization_id)
        .with_for_update()
    )
    if account and account.provider != "stripe":
        raise HTTPException(
            status_code=409,
            detail="This organization is bound to a different billing provider",
        )
    if account is None and create:
        account = OrganizationBillingAccount(
            organization_id=organization_id,
            provider="stripe",
            created_by=actor.user_id if actor else None,
            updated_by=actor.user_id if actor else None,
        )
        db.add(account)
        db.flush()
    return account


def _ensure_stripe_refs_available(
    db: Session,
    organization_id: int,
    customer_id: str,
    subscription_id: str,
) -> None:
    conflict = db.scalar(
        select(OrganizationBillingAccount.id).where(
            OrganizationBillingAccount.provider == "stripe",
            OrganizationBillingAccount.organization_id != organization_id,
            or_(
                OrganizationBillingAccount.external_customer_id == customer_id,
                OrganizationBillingAccount.external_subscription_id == subscription_id,
            ),
        )
    )
    if conflict:
        raise HTTPException(
            status_code=409,
            detail="Stripe references are already bound to another organization",
        )


def _stripe_price_from_object(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and isinstance(value.get("id"), str):
        return value["id"]
    return None


def _stripe_subscription_period(obj: dict) -> tuple[datetime | None, datetime | None]:
    start = utc_from_epoch(obj.get("current_period_start"))
    end = utc_from_epoch(obj.get("current_period_end"))
    items = obj.get("items") if isinstance(obj.get("items"), dict) else {}
    entries = items.get("data") if isinstance(items.get("data"), list) else []
    first = entries[0] if entries and isinstance(entries[0], dict) else {}
    return start or utc_from_epoch(first.get("current_period_start")), end or utc_from_epoch(first.get("current_period_end"))


def _stripe_subscription_price(obj: dict) -> str | None:
    items = obj.get("items") if isinstance(obj.get("items"), dict) else {}
    entries = items.get("data") if isinstance(items.get("data"), list) else []
    first = entries[0] if entries and isinstance(entries[0], dict) else {}
    return _stripe_price_from_object(first.get("price"))


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


async def _bounded_webhook_body(request: Request) -> bytes:
    max_bytes = max(1024, settings.billing_webhook_max_bytes)
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > max_bytes:
            raise HTTPException(status_code=413, detail="Billing webhook payload is too large")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/billing/webhooks/stripe", response_model=BillingWebhookResponse)
async def receive_stripe_billing_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
    db: Session = Depends(get_db),
):
    if not settings.stripe_billing_enabled:
        raise HTTPException(status_code=503, detail="Stripe billing is disabled")
    body = await _bounded_webhook_body(request)
    try:
        verify_stripe_signature(body, stripe_signature)
    except StripeConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from None
    try:
        raw = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=422, detail="Stripe webhook JSON is invalid") from None
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="Stripe webhook must be an object")
    event_id = raw.get("id")
    event_type = raw.get("type")
    created = utc_from_epoch(raw.get("created"))
    data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
    obj = data.get("object") if isinstance(data.get("object"), dict) else {}
    if (
        not isinstance(event_id, str)
        or not event_id.startswith("evt_")
        or not isinstance(event_type, str)
        or not event_type
        or not created
        or not obj
    ):
        raise HTTPException(status_code=422, detail="Stripe webhook envelope is incomplete")
    payload_digest = sha256(body).hexdigest()
    receipt = db.scalar(
        select(StripeWebhookReceipt).where(
            StripeWebhookReceipt.external_event_id == event_id
        )
    )
    if receipt:
        if receipt.payload_sha256 != payload_digest:
            raise HTTPException(
                status_code=409,
                detail="Stripe event identifier was reused with different content",
            )
        organization = (
            db.get(Organization, receipt.organization_id)
            if receipt.organization_id is not None
            else None
        )
        return BillingWebhookResponse(
            external_event_id=event_id,
            processing_status=receipt.processing_status,
            duplicate=True,
            subscription_status=organization.subscription_status if organization else None,
            plan_code=organization.plan_code if organization else None,
        )

    if event_type == "checkout.session.completed":
        metadata = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
        organization_value = metadata.get("openpartsflow_organization_id") or obj.get("client_reference_id")
        try:
            organization_id = int(organization_value)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="Stripe checkout is missing tenant metadata") from None
        db.info.pop("organization_id", None)
        organization = lock_organization(db, organization_id)
        account = _stripe_account_for_org(db, organization_id, create=True)
        customer_id = obj.get("customer")
        subscription_id = obj.get("subscription")
        if not isinstance(customer_id, str) or not customer_id.startswith("cus_"):
            raise HTTPException(status_code=422, detail="Stripe checkout is missing a customer")
        if not isinstance(subscription_id, str) or not subscription_id.startswith("sub_"):
            raise HTTPException(status_code=422, detail="Stripe checkout is missing a subscription")
        if account.external_customer_id not in {None, customer_id}:
            raise HTTPException(status_code=409, detail="Stripe customer tenant binding conflicts")
        if account.external_subscription_id not in {None, subscription_id}:
            raise HTTPException(status_code=409, detail="Stripe subscription tenant binding conflicts")
        _ensure_stripe_refs_available(
            db, organization_id, customer_id, subscription_id
        )
        duplicate = (
            account.external_customer_id == customer_id
            and account.external_subscription_id == subscription_id
        )
        account.external_customer_id = customer_id
        account.external_subscription_id = subscription_id
        account.updated_at = utcnow_naive()
        account.version += 0 if duplicate else 1
        db.add(account)
        request_id = metadata.get("openpartsflow_request_id")
        if isinstance(request_id, str):
            operation = db.scalar(
                select(StripeBillingOperation).where(
                    StripeBillingOperation.organization_id == organization_id,
                    StripeBillingOperation.client_request_id == request_id,
                    StripeBillingOperation.operation_type == "checkout",
                )
            )
            if operation and operation.external_object_id not in {None, obj.get("id")}:
                raise HTTPException(status_code=409, detail="Stripe checkout evidence conflicts")
        db.add(
            AuditLog(
                organization_id=organization_id,
                user_id=None,
                action="stripe_checkout_webhook_bound",
                entity_type="organization_billing_account",
                entity_id=account.id,
                metadata_json=json.dumps(
                    {
                        "external_event_id": event_id,
                        "duplicate": duplicate,
                        "payload_sha256": payload_digest,
                    },
                    separators=(",", ":"),
                ),
                timestamp=utcnow_naive(),
            )
        )
        db.add(
            StripeWebhookReceipt(
                organization_id=organization_id,
                external_event_id=event_id,
                event_type=event_type,
                processing_status="bound",
                payload_sha256=payload_digest,
                received_at=utcnow_naive(),
                processed_at=utcnow_naive(),
            )
        )
        db.commit()
        return BillingWebhookResponse(
            external_event_id=event_id,
            processing_status="bound",
            duplicate=duplicate,
            subscription_status=organization.subscription_status,
            plan_code=organization.plan_code,
        )

    mapped_types = {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "invoice.paid",
        "invoice.payment_failed",
        "invoice.payment_action_required",
        "invoice.finalization_failed",
    }
    if event_type not in mapped_types:
        db.add(
            StripeWebhookReceipt(
                organization_id=None,
                external_event_id=event_id,
                event_type=str(event_type)[:100],
                processing_status="ignored",
                payload_sha256=payload_digest,
                received_at=utcnow_naive(),
                processed_at=utcnow_naive(),
            )
        )
        db.commit()
        return BillingWebhookResponse(
            external_event_id=event_id,
            processing_status="ignored",
            duplicate=False,
        )

    is_subscription = str(event_type).startswith("customer.subscription.")
    customer_id = obj.get("customer")
    subscription_id = obj.get("id") if is_subscription else obj.get("subscription")
    if not is_subscription and subscription_id is None:
        parent = obj.get("parent") if isinstance(obj.get("parent"), dict) else {}
        details = (
            parent.get("subscription_details")
            if isinstance(parent.get("subscription_details"), dict)
            else {}
        )
        subscription_id = details.get("subscription")
    if isinstance(subscription_id, dict):
        subscription_id = subscription_id.get("id")
    if not isinstance(customer_id, str) or not customer_id.startswith("cus_"):
        raise HTTPException(status_code=422, detail="Stripe event is missing a customer")
    if not isinstance(subscription_id, str) or not subscription_id.startswith("sub_"):
        raise HTTPException(status_code=422, detail="Stripe event is missing a subscription")

    db.info.pop("organization_id", None)
    account = db.scalar(
        select(OrganizationBillingAccount).where(
            OrganizationBillingAccount.provider == "stripe",
            OrganizationBillingAccount.external_customer_id == customer_id,
            or_(
                OrganizationBillingAccount.external_subscription_id.is_(None),
                OrganizationBillingAccount.external_subscription_id == subscription_id,
            ),
        )
    )
    if not account:
        metadata = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
        if not is_subscription:
            parent = obj.get("parent") if isinstance(obj.get("parent"), dict) else {}
            details = (
                parent.get("subscription_details")
                if isinstance(parent.get("subscription_details"), dict)
                else {}
            )
            metadata = (
                details.get("metadata")
                if isinstance(details.get("metadata"), dict)
                else metadata
            )
        try:
            metadata_organization_id = int(metadata.get("openpartsflow_organization_id"))
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=404,
                detail="Stripe subscription tenant binding not found",
            ) from None
        lock_organization(db, metadata_organization_id)
        account = _stripe_account_for_org(
            db, metadata_organization_id, create=True
        )
        if account.external_customer_id not in {None, customer_id}:
            raise HTTPException(status_code=409, detail="Stripe customer tenant binding conflicts")
        if account.external_subscription_id not in {None, subscription_id}:
            raise HTTPException(status_code=409, detail="Stripe subscription tenant binding conflicts")
        _ensure_stripe_refs_available(
            db, metadata_organization_id, customer_id, subscription_id
        )
        account.external_customer_id = customer_id
        account.external_subscription_id = subscription_id
        account.version += 1
        db.add(account)
        db.flush()

    internal_type = "subscription.renewed"
    current_start: datetime | None = None
    current_end: datetime | None = None
    cancel_at_period_end: bool | None = None
    trial_ends_at: datetime | None = None
    price_id: str | None = None
    if is_subscription:
        current_start, current_end = _stripe_subscription_period(obj)
        price_id = _stripe_subscription_price(obj)
        status = obj.get("status")
        cancel_at_period_end = bool(obj.get("cancel_at_period_end"))
        if event_type == "customer.subscription.deleted" or status == "canceled":
            internal_type = "subscription.cancelled"
            cancel_at_period_end = None
        elif status == "trialing":
            internal_type = "trial.started"
            trial_ends_at = utc_from_epoch(obj.get("trial_end"))
            cancel_at_period_end = None
        elif status in {"past_due", "unpaid", "incomplete_expired"}:
            internal_type = "payment.failed"
            cancel_at_period_end = None
        elif status == "paused":
            internal_type = "subscription.suspended"
            cancel_at_period_end = None
        elif event_type == "customer.subscription.created":
            internal_type = "subscription.activated"
    else:
        lines = obj.get("lines") if isinstance(obj.get("lines"), dict) else {}
        entries = lines.get("data") if isinstance(lines.get("data"), list) else []
        first_line = entries[0] if entries and isinstance(entries[0], dict) else {}
        period = first_line.get("period") if isinstance(first_line.get("period"), dict) else {}
        current_start = utc_from_epoch(period.get("start"))
        current_end = utc_from_epoch(period.get("end"))
        price_id = _stripe_price_from_object(first_line.get("price"))
        if price_id is None:
            pricing = (
                first_line.get("pricing")
                if isinstance(first_line.get("pricing"), dict)
                else {}
            )
            details = (
                pricing.get("price_details")
                if isinstance(pricing.get("price_details"), dict)
                else {}
            )
            price_id = _stripe_price_from_object(details.get("price"))
        if event_type != "invoice.paid":
            internal_type = "payment.failed"

    plan_code = stripe_plan_for_price(price_id)
    if internal_type in {"subscription.activated", "subscription.renewed"} and (
        not current_start or not current_end
    ):
        raise HTTPException(status_code=422, detail="Stripe subscription period is incomplete")
    payload = BillingWebhookEvent(
        event_id=event_id,
        event_type=internal_type,
        occurred_at=created,
        external_customer_id=customer_id,
        external_subscription_id=subscription_id,
        plan_code=(
            plan_code
            if internal_type in {"trial.started", "subscription.activated", "subscription.renewed"}
            else None
        ),
        trial_ends_at=trial_ends_at,
        current_period_start=current_start if internal_type in {"subscription.activated", "subscription.renewed"} else None,
        current_period_end=current_end if internal_type in {"subscription.activated", "subscription.renewed"} else None,
        cancel_at_period_end=cancel_at_period_end if internal_type in {"subscription.activated", "subscription.renewed"} else None,
    )
    event, organization, duplicate = process_billing_webhook_event(
        db,
        payload,
        body,
        provider="stripe",
        account_id=account.id,
    )
    return BillingWebhookResponse(
        event_id=event.id,
        external_event_id=event.external_event_id,
        processing_status=event.processing_status,
        duplicate=duplicate,
        subscription_status=event.after_subscription_status if duplicate else organization.subscription_status,
        plan_code=event.after_plan_code if duplicate else organization.plan_code,
    )


@router.post(
    "/organization/billing/stripe/checkout",
    response_model=StripeRedirectSessionRead,
)
def create_stripe_checkout_session(
    payload: StripeCheckoutRequest,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    _require_account_reauthentication(db, actor, payload.account_password)
    try:
        require_stripe_configuration()
    except StripeConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    prices = configured_price_ids()
    price_id = prices.get(payload.target_plan_code)
    if not price_id:
        raise HTTPException(status_code=409, detail="This plan is not available for Stripe checkout")
    organization = lock_organization(db, actor.organization_id)
    account = _stripe_account_for_org(db, organization.id, create=True, actor=actor)
    if account.external_subscription_id:
        raise HTTPException(status_code=409, detail="Use the billing portal for an existing subscription")
    digest = _stripe_request_digest(
        "checkout", {"organization_id": organization.id, "plan_code": payload.target_plan_code}
    )
    operation = _existing_stripe_operation(db, organization.id, payload.client_request_id, digest)
    if operation:
        return StripeRedirectSessionRead(
            operation_id=operation.id,
            status=operation.status,
            external_object_id=operation.external_object_id,
            replayed=True,
        )
    operation = _new_stripe_operation(
        db,
        actor,
        account,
        payload.client_request_id,
        "checkout",
        digest,
        target_plan_code=payload.target_plan_code,
    )
    user = db.get(User, actor.user_id) if actor.user_id else None
    frontend = settings.frontend_public_url.rstrip("/")
    form = {
        "mode": "subscription",
        "line_items[0][price]": price_id,
        "line_items[0][quantity]": "1",
        "client_reference_id": str(organization.id),
        "success_url": f"{frontend}/settings?checkout=success",
        "cancel_url": f"{frontend}/settings?checkout=cancelled",
        "metadata[openpartsflow_organization_id]": str(organization.id),
        "metadata[openpartsflow_plan_code]": payload.target_plan_code,
        "metadata[openpartsflow_request_id]": payload.client_request_id,
        "subscription_data[metadata][openpartsflow_organization_id]": str(organization.id),
        "subscription_data[metadata][openpartsflow_plan_code]": payload.target_plan_code,
        "automatic_tax[enabled]": str(settings.stripe_automatic_tax_enabled).lower(),
        "tax_id_collection[enabled]": str(settings.stripe_tax_id_collection_enabled).lower(),
    }
    if account.external_customer_id:
        form["customer"] = account.external_customer_id
    elif user and user.email:
        form["customer_email"] = user.email
    try:
        result = stripe_api_post(
            "/v1/checkout/sessions",
            form,
            idempotency_key=f"opf-checkout-{organization.id}-{payload.client_request_id}",
        )
        session_id = str(result.data.get("id") or "")
        if not session_id.startswith("cs_"):
            raise StripeRequestError(502, "stripe_invalid_checkout_session", result.request_id)
        url = stripe_redirect_url(result.data.get("url"), "checkout.stripe.com")
        _complete_stripe_operation(
            db,
            actor,
            operation,
            external_object_id=session_id,
            external_request_id=result.request_id,
        )
        return StripeRedirectSessionRead(
            operation_id=operation.id,
            status="succeeded",
            external_object_id=session_id,
            url=url,
            expires_at=utc_from_epoch(result.data.get("expires_at")),
        )
    except StripeRequestError as exc:
        _complete_stripe_operation(
            db,
            actor,
            operation,
            external_object_id=None,
            external_request_id=exc.request_id,
            failure_code=exc.code,
        )
        raise _stripe_failure(exc) from exc


@router.post(
    "/organization/billing/stripe/portal",
    response_model=StripeRedirectSessionRead,
)
def create_stripe_portal_session(
    payload: StripePortalSessionRequest,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    _require_account_reauthentication(db, actor, payload.account_password)
    try:
        require_stripe_configuration()
    except StripeConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    organization = lock_organization(db, actor.organization_id)
    account = _stripe_account_for_org(db, organization.id, create=False)
    if not account or not account.external_customer_id:
        raise HTTPException(status_code=409, detail="No Stripe customer is connected")
    digest = _stripe_request_digest(
        "portal", {"organization_id": organization.id, "customer_id": account.external_customer_id}
    )
    operation = _existing_stripe_operation(db, organization.id, payload.client_request_id, digest)
    if operation:
        return StripeRedirectSessionRead(
            operation_id=operation.id,
            status=operation.status,
            external_object_id=operation.external_object_id,
            replayed=True,
        )
    operation = _new_stripe_operation(
        db, actor, account, payload.client_request_id, "portal", digest
    )
    try:
        result = stripe_api_post(
            "/v1/billing_portal/sessions",
            {
                "customer": account.external_customer_id,
                "return_url": f"{settings.frontend_public_url.rstrip('/')}/settings",
            },
            idempotency_key=f"opf-portal-{organization.id}-{payload.client_request_id}",
        )
        session_id = str(result.data.get("id") or "")
        if not session_id.startswith("bps_"):
            raise StripeRequestError(502, "stripe_invalid_portal_session", result.request_id)
        url = stripe_redirect_url(result.data.get("url"), "billing.stripe.com")
        _complete_stripe_operation(
            db, actor, operation, external_object_id=session_id, external_request_id=result.request_id
        )
        return StripeRedirectSessionRead(
            operation_id=operation.id,
            status="succeeded",
            external_object_id=session_id,
            url=url,
        )
    except StripeRequestError as exc:
        _complete_stripe_operation(
            db,
            actor,
            operation,
            external_object_id=None,
            external_request_id=exc.request_id,
            failure_code=exc.code,
        )
        raise _stripe_failure(exc) from exc


@router.get(
    "/organization/billing/stripe/operations",
    response_model=list[StripeBillingOperationRead],
)
def list_organization_stripe_operations(
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    rows = db.scalars(
        select(StripeBillingOperation)
        .order_by(StripeBillingOperation.created_at.desc(), StripeBillingOperation.id.desc())
        .limit(limit)
    ).all()
    return [StripeBillingOperationRead.model_validate(row) for row in rows]


@router.post("/platform/billing/stripe/refunds", response_model=StripeRefundRead)
def create_stripe_refund(
    payload: StripeRefundRequest,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_platform_admin(actor)
    _require_account_reauthentication(db, actor, payload.account_password)
    try:
        require_stripe_configuration()
    except StripeConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    db.info.pop("organization_id", None)
    organization = lock_organization(db, payload.organization_id)
    account = _stripe_account_for_org(db, organization.id, create=False)
    if not account or not account.external_customer_id:
        raise HTTPException(status_code=409, detail="No Stripe customer is connected")
    digest = _stripe_request_digest(
        "refund",
        {
            "organization_id": organization.id,
            "payment_intent_id": payload.payment_intent_id,
            "amount_minor": payload.amount_minor,
            "reason": payload.reason,
            "business_reason": payload.business_reason,
        },
    )
    existing = _existing_stripe_operation(db, organization.id, payload.client_request_id, digest)
    if existing:
        return StripeRefundRead(
            operation_id=existing.id,
            status=existing.status,
            external_object_id=existing.external_object_id,
            amount_minor=existing.amount_minor,
            replayed=True,
        )
    try:
        intent = stripe_api_get(f"/v1/payment_intents/{payload.payment_intent_id}")
    except StripeRequestError as exc:
        raise _stripe_failure(exc) from exc
    if intent.data.get("customer") != account.external_customer_id:
        raise HTTPException(status_code=403, detail="Payment does not belong to this organization")
    operation = _new_stripe_operation(
        db,
        actor,
        account,
        payload.client_request_id,
        "refund",
        digest,
        organization_id=organization.id,
        amount_minor=payload.amount_minor,
    )
    form = {
        "payment_intent": payload.payment_intent_id,
        "reason": payload.reason,
        "metadata[openpartsflow_organization_id]": str(organization.id),
        "metadata[openpartsflow_operation_id]": str(operation.id),
    }
    if payload.amount_minor is not None:
        form["amount"] = str(payload.amount_minor)
    try:
        result = stripe_api_post(
            "/v1/refunds",
            form,
            idempotency_key=f"opf-refund-{organization.id}-{payload.client_request_id}",
        )
        refund_id = str(result.data.get("id") or "")
        if not refund_id.startswith("re_"):
            raise StripeRequestError(502, "stripe_invalid_refund", result.request_id)
        _complete_stripe_operation(
            db, actor, operation, external_object_id=refund_id, external_request_id=result.request_id
        )
        return StripeRefundRead(
            operation_id=operation.id,
            status="succeeded",
            external_object_id=refund_id,
            amount_minor=payload.amount_minor,
        )
    except StripeRequestError as exc:
        _complete_stripe_operation(
            db,
            actor,
            operation,
            external_object_id=None,
            external_request_id=exc.request_id,
            failure_code=exc.code,
        )
        raise _stripe_failure(exc) from exc


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
        stripe_enabled=settings.stripe_billing_enabled,
        stripe_checkout_plans=list(configured_price_ids()) if settings.stripe_billing_enabled else [],
        stripe_portal_available=bool(
            settings.stripe_billing_enabled
            and account
            and account.provider == "stripe"
            and account.external_customer_id
        ),
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
