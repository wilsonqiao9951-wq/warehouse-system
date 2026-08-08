from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    InventoryNotification,
    Part,
    ReplenishmentRequest,
    StockThresholdRule,
    User,
    Warehouse,
)
from app.schemas import InventoryNotificationRead, StockThresholdRuleRead
from app.services.inventory import get_stock_quantity


ACTIVE_ALERT_STATUSES = ("open", "acknowledged")


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def effective_stock_threshold(
    db: Session,
    organization_id: int,
    part: Part,
    warehouse_id: int,
    *,
    current_quantity: int,
) -> tuple[StockThresholdRule | None, int, int]:
    rule = db.scalar(
        select(StockThresholdRule).where(
            StockThresholdRule.organization_id == organization_id,
            StockThresholdRule.warehouse_id == warehouse_id,
            StockThresholdRule.part_id == part.id,
            StockThresholdRule.is_active.is_(True),
        )
    )
    if rule:
        return rule, rule.threshold_quantity, rule.reorder_quantity
    threshold = max(part.safety_stock, part.min_stock)
    return None, threshold, max(1, threshold + 1 - current_quantity)


def evaluate_inventory_position(
    db: Session,
    organization_id: int,
    *,
    part: Part,
    warehouse: Warehouse,
    quantity: int,
    work_order_id: int | None = None,
) -> tuple[InventoryNotification | None, bool]:
    rule, threshold, _reorder_quantity = effective_stock_threshold(
        db,
        organization_id,
        part,
        warehouse.id,
        current_quantity=quantity,
    )
    if quantity > threshold:
        return None, False
    existing = db.scalar(
        select(InventoryNotification)
        .where(
            InventoryNotification.organization_id == organization_id,
            InventoryNotification.part_id == part.id,
            InventoryNotification.warehouse_id == warehouse.id,
            InventoryNotification.status.in_(ACTIVE_ALERT_STATUSES),
        )
        .with_for_update()
    )
    if existing:
        return existing, False

    item = InventoryNotification(
        organization_id=organization_id,
        part_id=part.id,
        warehouse_id=warehouse.id,
        work_order_id=work_order_id,
        threshold_rule_id=rule.id if rule else None,
        threshold_quantity=threshold,
        observed_quantity=quantity,
        message=(
            f"{part.part_number} stock at {warehouse.name} is {quantity}; "
            f"the effective low-stock threshold is {threshold}."
        ),
    )
    savepoint = db.begin_nested()
    try:
        db.add(item)
        db.flush()
        savepoint.commit()
        return item, True
    except IntegrityError:
        savepoint.rollback()
        existing = db.scalar(
            select(InventoryNotification).where(
                InventoryNotification.organization_id == organization_id,
                InventoryNotification.part_id == part.id,
                InventoryNotification.warehouse_id == warehouse.id,
                InventoryNotification.status.in_(ACTIVE_ALERT_STATUSES),
            )
        )
        if existing:
            return existing, False
        raise


def resolve_inventory_notification(
    notification: InventoryNotification,
    *,
    actor_user_id: int | None,
    reason: str,
    resolved_at: datetime | None = None,
) -> bool:
    if notification.status == "resolved":
        return False
    notification.status = "resolved"
    notification.resolved_by = actor_user_id
    notification.resolved_at = resolved_at or _utcnow_naive()
    notification.resolution_reason = reason.strip()[:500]
    notification.version += 1
    return True


def reopen_inventory_notification(notification: InventoryNotification) -> None:
    if notification.status == "open":
        return
    notification.status = "open"
    notification.resolved_by = None
    notification.resolved_at = None
    notification.resolution_reason = None
    notification.version += 1


def stock_threshold_rule_read(
    db: Session,
    rule: StockThresholdRule,
) -> StockThresholdRuleRead:
    warehouse = db.get(Warehouse, rule.warehouse_id)
    part = db.get(Part, rule.part_id)

    def user_name(user_id: int | None) -> str | None:
        user = db.get(User, user_id) if user_id else None
        return user.name if user else None

    return StockThresholdRuleRead(
        id=rule.id,
        organization_id=rule.organization_id,
        warehouse_id=rule.warehouse_id,
        warehouse_name=warehouse.name if warehouse else f"Warehouse #{rule.warehouse_id}",
        part_id=rule.part_id,
        part_number=part.part_number if part else f"Part #{rule.part_id}",
        part_name=part.name if part else "Unavailable part",
        threshold_quantity=rule.threshold_quantity,
        reorder_quantity=rule.reorder_quantity,
        is_active=rule.is_active,
        reason=rule.reason,
        version=rule.version,
        created_by=rule.created_by,
        created_by_name=user_name(rule.created_by),
        updated_by=rule.updated_by,
        updated_by_name=user_name(rule.updated_by),
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def inventory_notification_read(
    db: Session,
    item: InventoryNotification,
) -> InventoryNotificationRead:
    part = db.get(Part, item.part_id)
    warehouse = db.get(Warehouse, item.warehouse_id)
    if not part or not warehouse:
        raise RuntimeError("Low-stock alert references missing tenant inventory master data")
    current_quantity = get_stock_quantity(db, item.part_id, item.warehouse_id)
    rule, effective_threshold, reorder_quantity = effective_stock_threshold(
        db,
        item.organization_id,
        part,
        item.warehouse_id,
        current_quantity=current_quantity,
    )
    replenishment = db.scalar(
        select(ReplenishmentRequest).where(
            ReplenishmentRequest.organization_id == item.organization_id,
            ReplenishmentRequest.notification_id == item.id,
        )
    )

    def user_name(user_id: int | None) -> str | None:
        user = db.get(User, user_id) if user_id else None
        return user.name if user else None

    recovered = current_quantity > effective_threshold
    replenishment_completed = bool(replenishment and replenishment.status == "completed")
    return InventoryNotificationRead(
        id=item.id,
        organization_id=item.organization_id,
        part_id=item.part_id,
        part_number=part.part_number,
        part_name=part.name,
        warehouse_id=item.warehouse_id,
        warehouse_name=warehouse.name,
        work_order_id=item.work_order_id,
        notification_type=item.notification_type,
        message=item.message,
        status=item.status,
        threshold_rule_id=item.threshold_rule_id,
        threshold_quantity=item.threshold_quantity,
        effective_threshold_quantity=effective_threshold,
        reorder_quantity=reorder_quantity,
        threshold_source="override" if rule else "part_default",
        observed_quantity=item.observed_quantity,
        current_quantity=current_quantity,
        recovered=recovered,
        version=item.version,
        acknowledged_by=item.acknowledged_by,
        acknowledged_by_name=user_name(item.acknowledged_by),
        acknowledged_at=item.acknowledged_at,
        acknowledgement_note=item.acknowledgement_note,
        resolved_by=item.resolved_by,
        resolved_by_name=user_name(item.resolved_by),
        resolved_at=item.resolved_at,
        resolution_reason=item.resolution_reason,
        linked_replenishment_id=replenishment.id if replenishment else None,
        linked_replenishment_status=replenishment.status if replenishment else None,
        can_acknowledge=item.status == "open",
        can_resolve=item.status == "acknowledged" and (recovered or replenishment_completed),
        created_at=item.created_at,
        updated_at=item.updated_at,
    )
