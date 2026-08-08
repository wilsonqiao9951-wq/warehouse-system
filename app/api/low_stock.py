from __future__ import annotations

from datetime import datetime, timezone
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rbac import Actor, get_current_actor, require_roles
from app.models import (
    AuditLog,
    InventoryNotification,
    Part,
    StockThresholdRule,
    UserRole,
    Warehouse,
)
from app.schemas import (
    InventoryNotificationAction,
    InventoryNotificationRead,
    LowStockEvaluationRead,
    StockThresholdRuleRead,
    StockThresholdRuleUpsert,
)
from app.services.inventory import begin_inventory_write, get_stock_quantity
from app.services.low_stock import (
    ACTIVE_ALERT_STATUSES,
    effective_stock_threshold,
    evaluate_inventory_position,
    inventory_notification_read,
    resolve_inventory_notification,
    stock_threshold_rule_read,
)


router = APIRouter(prefix="/inventory", tags=["low-stock"])
MAX_EVALUATION_POSITIONS = 50_000


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _audit(
    db: Session,
    actor: Actor,
    action: str,
    entity_type: str,
    entity_id: int | None,
    metadata: dict,
) -> None:
    db.add(
        AuditLog(
            organization_id=actor.organization_id,
            user_id=actor.user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            metadata_json=json.dumps(
                {
                    "actor_role": actor.role.value,
                    "auth_method": actor.auth_method,
                    "device_id": actor.device_id,
                    **metadata,
                },
                default=str,
                separators=(",", ":"),
            ),
            timestamp=_utcnow_naive(),
        )
    )


@router.get("/stock-threshold-rules", response_model=list[StockThresholdRuleRead])
def list_stock_threshold_rules(
    response: Response,
    warehouse_id: int | None = Query(default=None, ge=1),
    part_id: int | None = Query(default=None, ge=1),
    is_active: bool | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=500),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    response.headers["Cache-Control"] = "no-store"
    query = select(StockThresholdRule).where(
        StockThresholdRule.organization_id == actor.organization_id
    )
    if warehouse_id is not None:
        query = query.where(StockThresholdRule.warehouse_id == warehouse_id)
    if part_id is not None:
        query = query.where(StockThresholdRule.part_id == part_id)
    if is_active is not None:
        query = query.where(StockThresholdRule.is_active.is_(is_active))
    rows = db.scalars(
        query.order_by(StockThresholdRule.updated_at.desc(), StockThresholdRule.id.desc()).limit(limit)
    ).all()
    return [stock_threshold_rule_read(db, row) for row in rows]


@router.put(
    "/stock-threshold-rules/{warehouse_id}/{part_id}",
    response_model=StockThresholdRuleRead,
)
def upsert_stock_threshold_rule(
    warehouse_id: int,
    part_id: int,
    payload: StockThresholdRuleUpsert,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    begin_inventory_write(db)
    warehouse = db.scalar(
        select(Warehouse).where(
            Warehouse.id == warehouse_id,
            Warehouse.organization_id == actor.organization_id,
        )
    )
    part = db.scalar(
        select(Part).where(
            Part.id == part_id,
            Part.organization_id == actor.organization_id,
        )
    )
    if not warehouse:
        raise HTTPException(status_code=404, detail="Warehouse not found")
    if not part:
        raise HTTPException(status_code=404, detail="Part not found")
    if payload.is_active and (not warehouse.is_active or not part.is_active):
        raise HTTPException(
            status_code=422,
            detail="An active threshold rule requires an active warehouse and part",
        )

    rule = db.scalar(
        select(StockThresholdRule)
        .where(
            StockThresholdRule.organization_id == actor.organization_id,
            StockThresholdRule.warehouse_id == warehouse_id,
            StockThresholdRule.part_id == part_id,
        )
        .with_for_update()
    )
    previous: dict | None = None
    if rule is None:
        if payload.expected_version is not None:
            raise HTTPException(status_code=409, detail="Threshold rule does not exist; refresh before saving")
        rule = StockThresholdRule(
            organization_id=actor.organization_id,
            warehouse_id=warehouse_id,
            part_id=part_id,
            threshold_quantity=payload.threshold_quantity,
            reorder_quantity=payload.reorder_quantity,
            is_active=payload.is_active,
            reason=payload.reason.strip(),
            version=0,
            created_by=actor.user_id,
            updated_by=actor.user_id,
        )
        db.add(rule)
        audit_action = "stock_threshold_rule_created"
    else:
        if payload.expected_version is None or rule.version != payload.expected_version:
            raise HTTPException(status_code=409, detail="Threshold rule changed; refresh before saving")
        previous = {
            "threshold_quantity": rule.threshold_quantity,
            "reorder_quantity": rule.reorder_quantity,
            "is_active": rule.is_active,
            "version": rule.version,
        }
        rule.threshold_quantity = payload.threshold_quantity
        rule.reorder_quantity = payload.reorder_quantity
        rule.is_active = payload.is_active
        rule.reason = payload.reason.strip()
        rule.updated_by = actor.user_id
        rule.version += 1
        audit_action = "stock_threshold_rule_updated"

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Threshold rule was created or changed concurrently; refresh before saving",
        ) from exc
    quantity = get_stock_quantity(db, part_id, warehouse_id)
    alert, alert_created = evaluate_inventory_position(
        db,
        actor.organization_id,
        part=part,
        warehouse=warehouse,
        quantity=quantity,
    )
    _audit(
        db,
        actor,
        audit_action,
        "stock_threshold_rule",
        rule.id,
        {
            "warehouse_id": warehouse_id,
            "part_id": part_id,
            "previous": previous,
            "threshold_quantity": rule.threshold_quantity,
            "reorder_quantity": rule.reorder_quantity,
            "is_active": rule.is_active,
            "reason": rule.reason,
            "new_version": rule.version,
            "current_quantity": quantity,
            "alert_id": alert.id if alert else None,
            "alert_created": alert_created,
        },
    )
    db.commit()
    db.refresh(rule)
    return stock_threshold_rule_read(db, rule)


@router.post("/low-stock/evaluate", response_model=LowStockEvaluationRead)
def evaluate_low_stock(
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    begin_inventory_write(db)
    parts = db.scalars(
        select(Part).where(
            Part.organization_id == actor.organization_id,
            Part.is_active.is_(True),
        ).order_by(Part.id)
    ).all()
    warehouses = db.scalars(
        select(Warehouse).where(
            Warehouse.organization_id == actor.organization_id,
            Warehouse.is_active.is_(True),
        ).order_by(Warehouse.id)
    ).all()
    if len(parts) * len(warehouses) > MAX_EVALUATION_POSITIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Inventory evaluation is limited to {MAX_EVALUATION_POSITIONS} positions per run",
        )
    scanned = below_threshold = created = already_active = recovered_active = 0
    for part in parts:
        for warehouse in warehouses:
            scanned += 1
            quantity = get_stock_quantity(db, part.id, warehouse.id)
            _rule, threshold, _reorder = effective_stock_threshold(
                db,
                actor.organization_id,
                part,
                warehouse.id,
                current_quantity=quantity,
            )
            if quantity <= threshold:
                below_threshold += 1
                _alert, was_created = evaluate_inventory_position(
                    db,
                    actor.organization_id,
                    part=part,
                    warehouse=warehouse,
                    quantity=quantity,
                )
                if was_created:
                    created += 1
                else:
                    already_active += 1
            else:
                active = db.scalar(
                    select(InventoryNotification.id).where(
                        InventoryNotification.organization_id == actor.organization_id,
                        InventoryNotification.part_id == part.id,
                        InventoryNotification.warehouse_id == warehouse.id,
                        InventoryNotification.status.in_(ACTIVE_ALERT_STATUSES),
                    )
                )
                recovered_active += int(active is not None)
    result = LowStockEvaluationRead(
        scanned=scanned,
        below_threshold=below_threshold,
        created=created,
        already_active=already_active,
        recovered_active=recovered_active,
    )
    _audit(db, actor, "low_stock_evaluated", "inventory_notification", None, result.model_dump())
    db.commit()
    return result


@router.post(
    "/notifications/{notification_id}/actions",
    response_model=InventoryNotificationRead,
)
def act_on_low_stock_notification(
    notification_id: int,
    payload: InventoryNotificationAction,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    begin_inventory_write(db)
    item = db.scalar(
        select(InventoryNotification)
        .where(
            InventoryNotification.id == notification_id,
            InventoryNotification.organization_id == actor.organization_id,
        )
        .with_for_update()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Low-stock notification not found")
    if (
        payload.action == "acknowledge"
        and item.status == "acknowledged"
        and item.acknowledged_by == actor.user_id
        and (item.acknowledgement_note or "") == ((payload.note or "").strip())
    ):
        return inventory_notification_read(db, item)
    if (
        payload.action == "resolve"
        and item.status == "resolved"
        and item.resolved_by == actor.user_id
        and (item.resolution_reason or "") == ((payload.reason or "").strip())
    ):
        return inventory_notification_read(db, item)
    if item.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Low-stock notification changed; refresh before continuing")

    before = item.status
    if payload.action == "acknowledge":
        if item.status != "open":
            raise HTTPException(status_code=409, detail="Only an open notification can be acknowledged")
        item.status = "acknowledged"
        item.acknowledged_by = actor.user_id
        item.acknowledged_at = _utcnow_naive()
        item.acknowledgement_note = payload.note.strip() if payload.note else None
        item.version += 1
    else:
        if item.status != "acknowledged":
            raise HTTPException(status_code=409, detail="A notification must be acknowledged before resolution")
        view = inventory_notification_read(db, item)
        replenishment_completed = view.linked_replenishment_status == "completed"
        if not view.recovered and not replenishment_completed:
            raise HTTPException(
                status_code=409,
                detail="Stock must recover above the effective threshold or the linked replenishment must complete",
            )
        resolve_inventory_notification(
            item,
            actor_user_id=actor.user_id,
            reason=payload.reason or "Resolved with verified stock evidence",
        )
    _audit(
        db,
        actor,
        f"inventory_notification_{payload.action}d",
        "inventory_notification",
        item.id,
        {
            "from_status": before,
            "to_status": item.status,
            "previous_version": payload.expected_version,
            "new_version": item.version,
            "note": payload.note,
            "reason": payload.reason,
        },
    )
    db.commit()
    db.refresh(item)
    return inventory_notification_read(db, item)
