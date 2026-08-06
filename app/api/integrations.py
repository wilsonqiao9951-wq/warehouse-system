from __future__ import annotations

from datetime import datetime
import json
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rbac import Actor, get_current_actor, require_roles
from app.models import (
    AuditLog,
    ExternalIntegration,
    ExternalSyncLog,
    ExternalWorkOrderLink,
    Organization,
    Part,
    UserRole,
    Warehouse,
    WorkOrder,
)
from app.schemas import (
    ExternalInventoryBalanceRead,
    ExternalIntegrationCreate,
    ExternalIntegrationRead,
    ExternalIntegrationRotate,
    ExternalIntegrationSecretRead,
    ExternalIntegrationUpdate,
    ExternalPartRecommendationRead,
    ExternalSyncLogRead,
    ExternalWorkOrderRead,
    ExternalWorkOrderUpsert,
    ExternalWorkOrderUpsertRead,
)
from app.services.integrations import (
    api_key_prefix,
    generate_api_key,
    hash_api_key,
    integration_read,
    sync_log_read,
    upsert_external_work_order,
    validate_field_mapping,
    validate_subscribed_events,
    validate_webhook_url,
)
from app.services.inventory import get_available_stock_quantity, get_stock_balances
from app.services.commercial import require_subscription_access
from app.services.recommendations import build_part_recommendations


router = APIRouter()


def _integration_or_404(db: Session, integration_id: int) -> ExternalIntegration:
    integration = db.get(ExternalIntegration, integration_id)
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    return integration


def _audit_integration(
    db: Session,
    actor: Actor,
    action: str,
    integration: ExternalIntegration,
    metadata: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            organization_id=actor.organization_id,
            user_id=actor.user_id,
            action=action,
            entity_type="external_integration",
            entity_id=integration.id,
            metadata_json=json.dumps(
                {
                    "actor_role": actor.role.value,
                    "provider": integration.provider,
                    **(metadata or {}),
                },
                separators=(",", ":"),
            ),
            timestamp=datetime.utcnow(),
        )
    )


def get_external_integration(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> ExternalIntegration:
    provided_key = x_api_key or ""
    if len(provided_key) > 200:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    prefix = api_key_prefix(provided_key)
    candidate = (
        db.scalar(
            select(ExternalIntegration).where(
                ExternalIntegration.key_prefix == prefix,
            )
        )
        if prefix
        else None
    )
    expected_hash = candidate.api_key_hash if candidate else "0" * 64
    key_matches = secrets.compare_digest(hash_api_key(provided_key), expected_hash)
    if not candidate or not key_matches or not candidate.is_active:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    organization = db.get(Organization, candidate.organization_id)
    require_subscription_access(organization)
    db.info["organization_id"] = candidate.organization_id
    return candidate


@router.get(
    "/integrations",
    response_model=list[ExternalIntegrationRead],
)
def list_integrations(
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    rows = db.scalars(
        select(ExternalIntegration).order_by(
            ExternalIntegration.is_active.desc(),
            ExternalIntegration.name,
            ExternalIntegration.id,
        )
    ).all()
    return [integration_read(row) for row in rows]


@router.post(
    "/integrations",
    response_model=ExternalIntegrationSecretRead,
)
def create_integration(
    payload: ExternalIntegrationCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    mapping = validate_field_mapping(payload.field_mapping)
    webhook_url = validate_webhook_url(payload.webhook_url)
    subscribed_events = validate_subscribed_events(payload.subscribed_events)
    if subscribed_events and not webhook_url:
        raise HTTPException(
            status_code=422,
            detail="A webhook URL is required when outbound events are subscribed",
        )
    raw_key, prefix, key_hash = generate_api_key()
    integration = ExternalIntegration(
        organization_id=actor.organization_id,
        name=payload.name.strip(),
        provider=payload.provider,
        key_prefix=prefix,
        api_key_hash=key_hash,
        field_mapping_json=json.dumps(mapping, separators=(",", ":")),
        webhook_url=webhook_url,
        subscribed_events_json=json.dumps(subscribed_events, separators=(",", ":")),
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    db.add(integration)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="An integration with this name already exists",
        ) from exc
    _audit_integration(db, actor, "create_external_integration", integration)
    db.commit()
    db.refresh(integration)
    return ExternalIntegrationSecretRead(
        integration=integration_read(integration),
        api_key=raw_key,
    )


@router.patch(
    "/integrations/{integration_id}",
    response_model=ExternalIntegrationRead,
)
def update_integration(
    integration_id: int,
    payload: ExternalIntegrationUpdate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    integration = _integration_or_404(db, integration_id)
    if integration.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Integration version is stale")
    changed_fields: list[str] = []
    if payload.name is not None:
        integration.name = payload.name.strip()
        changed_fields.append("name")
    if payload.field_mapping is not None:
        integration.field_mapping_json = json.dumps(
            validate_field_mapping(payload.field_mapping),
            separators=(",", ":"),
        )
        changed_fields.append("field_mapping")
    webhook_url = integration.webhook_url
    if "webhook_url" in payload.model_fields_set:
        webhook_url = validate_webhook_url(payload.webhook_url)
    subscribed_events = json.loads(integration.subscribed_events_json or "[]")
    if payload.subscribed_events is not None:
        subscribed_events = validate_subscribed_events(payload.subscribed_events)
    if subscribed_events and not webhook_url:
        raise HTTPException(
            status_code=422,
            detail="A webhook URL is required when outbound events are subscribed",
        )
    if "webhook_url" in payload.model_fields_set:
        integration.webhook_url = webhook_url
        changed_fields.append("webhook_url")
    if payload.subscribed_events is not None:
        integration.subscribed_events_json = json.dumps(
            subscribed_events,
            separators=(",", ":"),
        )
        changed_fields.append("subscribed_events")
    if payload.is_active is not None:
        integration.is_active = payload.is_active
        changed_fields.append("is_active")
    integration.version += 1
    integration.updated_by = actor.user_id
    db.add(integration)
    _audit_integration(
        db,
        actor,
        "update_external_integration",
        integration,
        {
            "changed_fields": sorted(changed_fields),
            "new_version": integration.version,
        },
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="An integration with this name already exists",
        ) from exc
    db.refresh(integration)
    return integration_read(integration)


@router.post(
    "/integrations/{integration_id}/rotate-key",
    response_model=ExternalIntegrationSecretRead,
)
def rotate_integration_key(
    integration_id: int,
    payload: ExternalIntegrationRotate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    integration = _integration_or_404(db, integration_id)
    if integration.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Integration version is stale")
    raw_key, prefix, key_hash = generate_api_key()
    previous_prefix = integration.key_prefix
    integration.key_prefix = prefix
    integration.api_key_hash = key_hash
    integration.version += 1
    integration.updated_by = actor.user_id
    db.add(integration)
    _audit_integration(
        db,
        actor,
        "rotate_external_integration_key",
        integration,
        {
            "previous_key_prefix": previous_prefix,
            "new_key_prefix": prefix,
            "new_version": integration.version,
        },
    )
    db.commit()
    db.refresh(integration)
    return ExternalIntegrationSecretRead(
        integration=integration_read(integration),
        api_key=raw_key,
    )


@router.get(
    "/integrations/{integration_id}/sync-logs",
    response_model=list[ExternalSyncLogRead],
)
def list_integration_sync_logs(
    integration_id: int,
    status: str | None = Query(
        default=None,
        pattern="^(pending|processing|processed|failed)$",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    _integration_or_404(db, integration_id)
    stmt = select(ExternalSyncLog).where(
        ExternalSyncLog.integration_id == integration_id
    )
    if status:
        stmt = stmt.where(ExternalSyncLog.status == status)
    rows = db.scalars(
        stmt.order_by(
            ExternalSyncLog.created_at.desc(),
            ExternalSyncLog.id.desc(),
        ).limit(limit)
    ).all()
    return [sync_log_read(row) for row in rows]


@router.post(
    "/integrations/{integration_id}/sync-logs/{log_id}/retry",
    response_model=ExternalSyncLogRead,
)
def retry_integration_delivery(
    integration_id: int,
    log_id: int,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    _integration_or_404(db, integration_id)
    log = db.get(ExternalSyncLog, log_id)
    if (
        not log
        or log.integration_id != integration_id
        or log.direction != "outbound"
    ):
        raise HTTPException(status_code=404, detail="Outbound delivery not found")
    if log.status == "processed":
        raise HTTPException(status_code=409, detail="Delivery already succeeded")
    log.status = "pending"
    log.response_status_code = None
    log.response_json = None
    log.error_message = None
    log.next_retry_at = datetime.utcnow()
    log.last_attempt_at = None
    log.processed_at = None
    db.add(log)
    _audit_integration(
        db,
        actor,
        "retry_external_delivery",
        log.integration,
        {"sync_log_id": log.id, "event_type": log.event_type},
    )
    db.commit()
    db.refresh(log)
    return sync_log_read(log)


def _external_work_order(
    db: Session,
    integration: ExternalIntegration,
    external_id: str,
) -> tuple[ExternalWorkOrderLink, WorkOrder]:
    link = db.scalar(
        select(ExternalWorkOrderLink).where(
            ExternalWorkOrderLink.integration_id == integration.id,
            ExternalWorkOrderLink.external_id == external_id,
        )
    )
    work_order = db.get(WorkOrder, link.work_order_id) if link else None
    if not link or not work_order:
        raise HTTPException(status_code=404, detail="External work order not found")
    return link, work_order


def _mark_external_read(db: Session, integration: ExternalIntegration) -> None:
    integration.last_used_at = datetime.utcnow()
    db.add(integration)
    db.commit()


@router.get(
    "/external/v1/inventory",
    response_model=list[ExternalInventoryBalanceRead],
)
def external_inventory(
    part_number: str | None = Query(default=None, max_length=120),
    warehouse_code: str | None = Query(default=None, max_length=50),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    integration: ExternalIntegration = Depends(get_external_integration),
):
    parts = {
        row.id: row
        for row in db.scalars(select(Part).where(Part.is_active.is_(True))).all()
    }
    warehouses = {
        row.id: row
        for row in db.scalars(select(Warehouse).where(Warehouse.is_active.is_(True))).all()
    }
    part_filter = (part_number or "").strip().casefold()
    warehouse_filter = (warehouse_code or "").strip().casefold()
    rows: list[ExternalInventoryBalanceRead] = []
    for balance in get_stock_balances(db):
        part = parts.get(balance.part_id)
        warehouse = warehouses.get(balance.warehouse_id)
        if not part or not warehouse:
            continue
        if part_filter and part.part_number.casefold() != part_filter:
            continue
        if warehouse_filter and warehouse.code.casefold() != warehouse_filter:
            continue
        rows.append(
            ExternalInventoryBalanceRead(
                part_number=part.part_number,
                part_name=part.name,
                warehouse_code=warehouse.code,
                warehouse_name=warehouse.name,
                quantity=balance.quantity,
                available_quantity=get_available_stock_quantity(
                    db,
                    part.id,
                    warehouse.id,
                ),
                unit=part.unit,
                is_low_stock=balance.is_low_stock,
            )
        )
        if len(rows) >= limit:
            break
    _mark_external_read(db, integration)
    return rows


@router.get(
    "/external/v1/work-orders/{external_id}",
    response_model=ExternalWorkOrderRead,
)
def external_work_order_status(
    external_id: str,
    db: Session = Depends(get_db),
    integration: ExternalIntegration = Depends(get_external_integration),
):
    link, work_order = _external_work_order(db, integration, external_id)
    result = ExternalWorkOrderRead(
        external_id=link.external_id,
        work_order_id=work_order.id,
        ticket_number=work_order.ticket_number,
        status=work_order.status,
        assigned_engineer_id=work_order.engineer_id or work_order.assigned_user_id,
        claimed=work_order.claimed_by_id is not None,
        started_at=work_order.started_at,
        paused_at=work_order.paused_at,
        completed_at=work_order.completed_at,
        final_outcome=work_order.final_outcome,
        updated_at=work_order.updated_at,
    )
    _mark_external_read(db, integration)
    return result


@router.get(
    "/external/v1/work-orders/{external_id}/recommendations",
    response_model=list[ExternalPartRecommendationRead],
)
def external_work_order_recommendations(
    external_id: str,
    db: Session = Depends(get_db),
    integration: ExternalIntegration = Depends(get_external_integration),
):
    _, work_order = _external_work_order(db, integration, external_id)
    result = [
        ExternalPartRecommendationRead(
            part_number=row.part.part_number,
            part_name=row.part.name,
            recommended_quantity=row.recommended_quantity,
            historical_usage_count=row.usage_count,
            success_rate=row.success_rate,
            average_repair_minutes=row.average_repair_minutes,
            available_quantity=row.available_quantity,
            inventory_location=row.inventory_location,
            confidence=row.confidence,
            reason=row.reason,
        )
        for row in build_part_recommendations(db, work_order)
    ]
    _mark_external_read(db, integration)
    return result


@router.post(
    "/external/v1/work-orders",
    response_model=ExternalWorkOrderUpsertRead,
)
def external_work_order_upsert(
    payload: ExternalWorkOrderUpsert,
    idempotency_key: str = Header(
        min_length=8,
        max_length=160,
        alias="X-Idempotency-Key",
    ),
    db: Session = Depends(get_db),
    integration: ExternalIntegration = Depends(get_external_integration),
):
    cleaned_idempotency_key = idempotency_key.strip()
    if len(cleaned_idempotency_key) < 8:
        raise HTTPException(
            status_code=422,
            detail="X-Idempotency-Key must contain at least 8 non-space characters",
        )
    return upsert_external_work_order(
        db,
        integration,
        payload,
        cleaned_idempotency_key,
    )
