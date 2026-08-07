from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from app.core.database import get_db
from app.core.rbac import Actor, get_current_actor, require_roles
from app.models import (
    InventoryTransaction,
    Part,
    StorageLocation,
    TransactionType,
    User,
    UserRole,
    Warehouse,
    WorkOrder,
)
from app.schemas import (
    InventoryLedgerOptionRead,
    InventoryLedgerOptionsRead,
    InventoryLedgerPageRead,
    InventoryLedgerRowRead,
)


router = APIRouter(prefix="/inventory", tags=["inventory-ledger"])


def _utc_naive(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _require_valid_range(from_at: datetime | None, to_at: datetime | None) -> None:
    normalized_from = _utc_naive(from_at)
    normalized_to = _utc_naive(to_at)
    if (
        normalized_from is not None
        and normalized_to is not None
        and normalized_to < normalized_from
    ):
        raise HTTPException(status_code=422, detail="to_at must be on or after from_at")
    if (
        normalized_from is not None
        and normalized_to is not None
        and normalized_to - normalized_from > timedelta(days=366)
    ):
        raise HTTPException(
            status_code=422,
            detail="Inventory ledger range cannot exceed 366 days",
        )


def _conditions(
    actor: Actor,
    *,
    transaction_type: TransactionType | None,
    part_id: int | None,
    warehouse_id: int | None,
    user_id: int | None,
    work_order_id: int | None,
    from_at: datetime | None,
    to_at: datetime | None,
) -> list[Any]:
    conditions: list[Any] = [
        InventoryTransaction.organization_id == actor.organization_id
    ]
    if transaction_type is not None:
        conditions.append(
            InventoryTransaction.transaction_type == transaction_type
        )
    if part_id is not None:
        conditions.append(InventoryTransaction.part_id == part_id)
    if warehouse_id is not None:
        conditions.append(
            or_(
                InventoryTransaction.from_warehouse_id == warehouse_id,
                InventoryTransaction.to_warehouse_id == warehouse_id,
            )
        )
    if user_id is not None:
        conditions.append(InventoryTransaction.user_id == user_id)
    if work_order_id is not None:
        conditions.append(InventoryTransaction.work_order_id == work_order_id)
    normalized_from = _utc_naive(from_at)
    normalized_to = _utc_naive(to_at)
    if normalized_from is not None:
        conditions.append(InventoryTransaction.created_at >= normalized_from)
    if normalized_to is not None:
        conditions.append(InventoryTransaction.created_at <= normalized_to)
    return conditions


def _source(row: InventoryTransaction) -> str:
    if row.replenishment_request_id is not None:
        return "replenishment"
    if row.vehicle_return_request_id is not None:
        return "vehicle_return"
    if row.inventory_count_line_id is not None:
        return "inventory_count"
    if (
        row.transaction_type == TransactionType.WORK_ORDER_USED
        or row.work_order_id is not None
    ):
        return "work_order"
    return "manual"


def _read(values: tuple) -> InventoryLedgerRowRead:
    (
        row,
        part_number,
        part_name,
        from_warehouse_code,
        from_warehouse_name,
        to_warehouse_code,
        to_warehouse_name,
        from_location_code,
        to_location_code,
        work_order_ticket_number,
        user_name,
    ) = values
    return InventoryLedgerRowRead(
        id=row.id,
        transaction_type=row.transaction_type,
        quantity=row.quantity,
        unit_cost=max(0.0, row.unit_cost or 0.0),
        total_cost=round(abs(row.quantity) * max(0.0, row.unit_cost or 0.0), 2),
        part_id=row.part_id,
        part_number=part_number,
        part_name=part_name,
        from_warehouse_id=row.from_warehouse_id,
        from_warehouse_code=from_warehouse_code,
        from_warehouse_name=from_warehouse_name,
        to_warehouse_id=row.to_warehouse_id,
        to_warehouse_code=to_warehouse_code,
        to_warehouse_name=to_warehouse_name,
        from_location_id=row.from_location_id,
        from_location_code=from_location_code,
        to_location_id=row.to_location_id,
        to_location_code=to_location_code,
        work_order_id=row.work_order_id,
        work_order_ticket_number=work_order_ticket_number,
        user_id=row.user_id,
        user_name=user_name,
        source=_source(row),
        replenishment_request_id=row.replenishment_request_id,
        vehicle_return_request_id=row.vehicle_return_request_id,
        inventory_count_line_id=row.inventory_count_line_id,
        movement_stage=row.movement_stage,
        notes=row.notes,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/ledger", response_model=InventoryLedgerPageRead)
def inventory_ledger(
    response: Response,
    transaction_type: TransactionType | None = Query(default=None),
    part_id: int | None = Query(default=None, ge=1),
    warehouse_id: int | None = Query(default=None, ge=1),
    user_id: int | None = Query(default=None, ge=1),
    work_order_id: int | None = Query(default=None, ge=1),
    from_at: datetime | None = Query(default=None),
    to_at: datetime | None = Query(default=None),
    before_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    response.headers["Cache-Control"] = "no-store"
    _require_valid_range(from_at, to_at)
    conditions = _conditions(
        actor,
        transaction_type=transaction_type,
        part_id=part_id,
        warehouse_id=warehouse_id,
        user_id=user_id,
        work_order_id=work_order_id,
        from_at=from_at,
        to_at=to_at,
    )
    total = (
        db.scalar(
            select(func.count(InventoryTransaction.id)).where(*conditions)
        )
        or 0
    )
    page_conditions = [*conditions]
    if before_id is not None:
        page_conditions.append(InventoryTransaction.id < before_id)

    from_warehouse = aliased(Warehouse)
    to_warehouse = aliased(Warehouse)
    from_location = aliased(StorageLocation)
    to_location = aliased(StorageLocation)
    rows = db.execute(
        select(
            InventoryTransaction,
            Part.part_number,
            Part.name,
            from_warehouse.code,
            from_warehouse.name,
            to_warehouse.code,
            to_warehouse.name,
            from_location.code,
            to_location.code,
            WorkOrder.ticket_number,
            User.name,
        )
        .join(
            Part,
            (Part.id == InventoryTransaction.part_id)
            & (Part.organization_id == actor.organization_id),
        )
        .outerjoin(
            from_warehouse,
            (from_warehouse.id == InventoryTransaction.from_warehouse_id)
            & (from_warehouse.organization_id == actor.organization_id),
        )
        .outerjoin(
            to_warehouse,
            (to_warehouse.id == InventoryTransaction.to_warehouse_id)
            & (to_warehouse.organization_id == actor.organization_id),
        )
        .outerjoin(
            from_location,
            (from_location.id == InventoryTransaction.from_location_id)
            & (from_location.organization_id == actor.organization_id),
        )
        .outerjoin(
            to_location,
            (to_location.id == InventoryTransaction.to_location_id)
            & (to_location.organization_id == actor.organization_id),
        )
        .outerjoin(
            WorkOrder,
            (WorkOrder.id == InventoryTransaction.work_order_id)
            & (WorkOrder.organization_id == actor.organization_id),
        )
        .outerjoin(
            User,
            (User.id == InventoryTransaction.user_id)
            & (User.organization_id == actor.organization_id),
        )
        .where(*page_conditions)
        .order_by(InventoryTransaction.id.desc())
        .limit(limit + 1)
    ).all()
    has_more = len(rows) > limit
    items = [_read(row) for row in rows[:limit]]
    return InventoryLedgerPageRead(
        items=items,
        total=total,
        next_before_id=items[-1].id if has_more and items else None,
    )


@router.get("/ledger/options", response_model=InventoryLedgerOptionsRead)
def inventory_ledger_options(
    response: Response,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    response.headers["Cache-Control"] = "no-store"
    common = InventoryTransaction.organization_id == actor.organization_id
    parts = db.execute(
        select(Part.id, Part.part_number, Part.name)
        .join(InventoryTransaction, InventoryTransaction.part_id == Part.id)
        .where(common, Part.organization_id == actor.organization_id)
        .distinct()
        .order_by(Part.part_number.asc(), Part.id.asc())
    ).all()
    warehouses = db.execute(
        select(Warehouse.id, Warehouse.code, Warehouse.name)
        .where(
            Warehouse.organization_id == actor.organization_id,
            or_(
                Warehouse.id.in_(
                    select(InventoryTransaction.from_warehouse_id).where(
                        common,
                        InventoryTransaction.from_warehouse_id.is_not(None),
                    )
                ),
                Warehouse.id.in_(
                    select(InventoryTransaction.to_warehouse_id).where(
                        common,
                        InventoryTransaction.to_warehouse_id.is_not(None),
                    )
                ),
            ),
        )
        .order_by(Warehouse.code.asc(), Warehouse.id.asc())
    ).all()
    users = db.execute(
        select(User.id, User.name)
        .join(InventoryTransaction, InventoryTransaction.user_id == User.id)
        .where(common, User.organization_id == actor.organization_id)
        .distinct()
        .order_by(User.name.asc(), User.id.asc())
    ).all()
    return InventoryLedgerOptionsRead(
        parts=[
            InventoryLedgerOptionRead(
                id=part_id,
                label=f"{part_number} - {part_name}",
            )
            for part_id, part_number, part_name in parts
        ],
        warehouses=[
            InventoryLedgerOptionRead(
                id=warehouse_id,
                label=f"{code} - {name}",
            )
            for warehouse_id, code, name in warehouses
        ],
        users=[
            InventoryLedgerOptionRead(id=user_id, label=name)
            for user_id, name in users
        ],
        transaction_types=list(TransactionType),
    )
