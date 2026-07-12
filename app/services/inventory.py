from datetime import datetime
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import InventoryTransaction, Part, ReplenishmentRequest, StorageLocation, TransactionType, User, UserRole, Warehouse, WorkOrder, WorkOrderPart, WorkOrderPartMemory
from app.schemas import InventoryTransactionCreate, LocationStockBalance, StockBalance, WorkOrderPartCreate


def warehouse_is_vehicle(db: Session, warehouse: Warehouse | None) -> bool:
    if not warehouse:
        return False
    if (warehouse.warehouse_type or "").lower() == "van":
        return True
    owner = db.get(User, warehouse.assigned_user_id) if warehouse.assigned_user_id else None
    return bool(owner and owner.role == UserRole.ENGINEER)


def begin_inventory_write(db: Session) -> None:
    """Serialize inventory/state writes on SQLite; PostgreSQL uses row locks."""
    bind = db.get_bind()
    if bind.dialect.name != "sqlite":
        return
    active_lock_transaction = db.info.get("inventory_write_transaction")
    if active_lock_transaction is not None and active_lock_transaction is db.get_transaction():
        return
    if db.new or db.dirty or db.deleted:
        raise RuntimeError("SQLite inventory lock must be acquired before mutating the session")
    db.rollback()
    db.execute(text("BEGIN IMMEDIATE"))
    db.info["inventory_write_transaction"] = db.get_transaction()


def create_transaction(db: Session, payload: InventoryTransactionCreate) -> InventoryTransaction:
    if payload.transaction_type == TransactionType.ADJUSTMENT:
        raise HTTPException(status_code=400, detail="Manual inventory adjustment is not allowed")
    if payload.transaction_type not in {
        TransactionType.INBOUND,
        TransactionType.OUTBOUND,
        TransactionType.TRANSFER,
        TransactionType.DAMAGE,
    }:
        raise HTTPException(
            status_code=400,
            detail="This transaction type requires its authenticated business workflow",
        )

    begin_inventory_write(db)
    part = db.scalar(select(Part).where(Part.id == payload.part_id).with_for_update())
    if not part:
        raise HTTPException(status_code=404, detail="Part not found")
    _validate_transaction_entities(db, payload)

    for warehouse_id in {payload.from_warehouse_id, payload.to_warehouse_id} - {None}:
        warehouse = db.get(Warehouse, warehouse_id)
        if warehouse_is_vehicle(db, warehouse):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Vehicle inventory cannot be changed through the generic transaction endpoint; "
                    "use authenticated replenishment receipt, work-order usage, or the future return workflow"
                ),
            )

    if payload.transaction_type == TransactionType.INBOUND:
        if not payload.to_warehouse_id:
            raise HTTPException(status_code=400, detail="Inbound transaction requires to_warehouse_id")
        if payload.from_warehouse_id or payload.from_location_id:
            raise HTTPException(status_code=400, detail="Inbound transaction cannot have a source")

    if payload.transaction_type in {TransactionType.OUTBOUND, TransactionType.DAMAGE}:
        if not payload.from_warehouse_id:
            raise HTTPException(status_code=400, detail="Outbound or damage transaction requires from_warehouse_id")
        if payload.to_warehouse_id or payload.to_location_id:
            raise HTTPException(status_code=400, detail="Outbound or damage transaction cannot have a destination")

    if payload.transaction_type == TransactionType.TRANSFER:
        if not payload.from_warehouse_id or not payload.to_warehouse_id:
            raise HTTPException(status_code=400, detail="Transfer requires both from_warehouse_id and to_warehouse_id")
        if payload.from_warehouse_id == payload.to_warehouse_id and (
            not payload.from_location_id or not payload.to_location_id or payload.from_location_id == payload.to_location_id
        ):
            raise HTTPException(status_code=400, detail="Transfer warehouses cannot be the same")

    if payload.from_warehouse_id:
        warehouse_available = get_available_stock_quantity(db, payload.part_id, payload.from_warehouse_id)
        current = warehouse_available
        if payload.from_location_id:
            current = min(
                warehouse_available,
                get_location_stock_quantity(db, payload.part_id, payload.from_location_id),
            )
        if current < payload.quantity:
            raise HTTPException(status_code=400, detail=f"Insufficient stock. Available: {current}")

    with _write_transaction(db):
        tx = InventoryTransaction(**payload.model_dump())
        db.add(tx)
        db.flush()
        db.refresh(tx)
        return tx


def use_part_on_work_order(db: Session, payload: WorkOrderPartCreate) -> WorkOrderPart:
    begin_inventory_write(db)
    part = db.scalar(select(Part).where(Part.id == payload.part_id).with_for_update())
    if not part:
        raise HTTPException(status_code=404, detail="Part not found")
    _validate_work_order_usage_entities(db, payload)
    work_order = db.get(WorkOrder, payload.work_order_id)
    if work_order and work_order.is_locked:
        raise HTTPException(status_code=400, detail="Work order is locked and cannot be edited")

    current = get_available_stock_quantity(db, payload.part_id, payload.warehouse_id)
    if current < payload.quantity:
        raise HTTPException(status_code=400, detail=f"Insufficient stock. Available: {current}")

    with _write_transaction(db):
        usage = WorkOrderPart(**payload.model_dump(), total_cost=payload.quantity * payload.unit_cost)
        db.add(usage)
        db.flush()

        tx = InventoryTransaction(
            part_id=payload.part_id,
            transaction_type=TransactionType.WORK_ORDER_USED,
            quantity=payload.quantity,
            from_warehouse_id=payload.warehouse_id,
            to_warehouse_id=None,
            work_order_id=payload.work_order_id,
            user_id=payload.user_id,
            unit_cost=payload.unit_cost,
            notes=f"Used on work order #{payload.work_order_id}. {payload.notes or ''}".strip(),
        )
        db.add(tx)
        db.flush()
        memory = db.scalar(select(WorkOrderPartMemory).where(
            WorkOrderPartMemory.machine_type == (work_order.machine_type if work_order else None),
            WorkOrderPartMemory.job_type == (work_order.job_type if work_order else None),
            WorkOrderPartMemory.part_id == payload.part_id,
        ))
        if memory:
            memory.usage_count += 1
            memory.total_quantity += payload.quantity
            memory.last_used_at = datetime.utcnow()
        else:
            db.add(WorkOrderPartMemory(
                machine_type=work_order.machine_type if work_order else None,
                job_type=work_order.job_type if work_order else None,
                part_id=payload.part_id,
                total_quantity=payload.quantity,
            ))
        db.refresh(usage)
        return usage


def get_stock_quantity(db: Session, part_id: int, warehouse_id: int) -> int:
    transactions = db.scalars(
        select(InventoryTransaction).where(InventoryTransaction.part_id == part_id)
    ).all()

    quantity = 0
    for tx in transactions:
        if tx.to_warehouse_id == warehouse_id:
            quantity += tx.quantity
        if tx.from_warehouse_id == warehouse_id:
            quantity -= tx.quantity
    return quantity


def get_reserved_replenishment_quantity(
    db: Session,
    part_id: int,
    warehouse_id: int,
    exclude_request_id: int | None = None,
) -> int:
    stmt = select(func.coalesce(func.sum(ReplenishmentRequest.quantity), 0)).where(
        ReplenishmentRequest.part_id == part_id,
        ReplenishmentRequest.source_warehouse_id == warehouse_id,
        ReplenishmentRequest.status == "picking",
    )
    if exclude_request_id is not None:
        stmt = stmt.where(ReplenishmentRequest.id != exclude_request_id)
    return int(db.scalar(stmt) or 0)


def get_available_stock_quantity(db: Session, part_id: int, warehouse_id: int) -> int:
    return get_stock_quantity(db, part_id, warehouse_id) - get_reserved_replenishment_quantity(
        db, part_id, warehouse_id
    )


def get_location_stock_quantity(db: Session, part_id: int, location_id: int) -> int:
    transactions = db.scalars(select(InventoryTransaction).where(InventoryTransaction.part_id == part_id)).all()
    return sum(
        (tx.quantity if tx.to_location_id == location_id else 0)
        - (tx.quantity if tx.from_location_id == location_id else 0)
        for tx in transactions
    )


def get_location_stock_balances(db: Session, warehouse_id: int | None = None) -> list[LocationStockBalance]:
    locations_query = select(StorageLocation).order_by(StorageLocation.code.asc())
    if warehouse_id is not None:
        locations_query = locations_query.where(StorageLocation.warehouse_id == warehouse_id)
    locations = db.scalars(locations_query).all()
    parts = db.scalars(select(Part)).all()
    warehouses = {item.id: item for item in db.scalars(select(Warehouse)).all()}
    return [
        LocationStockBalance(
            part_id=part.id, part_number=part.part_number, part_name=part.name,
            warehouse_id=location.warehouse_id, warehouse_name=warehouses[location.warehouse_id].name,
            location_id=location.id, location_code=location.code, location_name=location.name,
            quantity=get_location_stock_quantity(db, part.id, location.id),
        )
        for location in locations for part in parts
    ]


def get_stock_balances(db: Session) -> list[StockBalance]:
    parts = db.scalars(select(Part)).all()
    warehouses = db.scalars(select(Warehouse)).all()

    results: list[StockBalance] = []
    for part in parts:
        for warehouse in warehouses:
            qty = get_stock_quantity(db, part.id, warehouse.id)
            results.append(
                StockBalance(
                    part_id=part.id,
                    part_number=part.part_number,
                    part_name=part.name,
                    warehouse_id=warehouse.id,
                    warehouse_name=warehouse.name,
                    quantity=qty,
                    safety_stock=part.safety_stock,
                    is_low_stock=qty <= max(part.safety_stock, part.min_stock),
                )
            )
    return results


def get_work_order_parts_cost(db: Session, work_order_id: int) -> float:
    rows = db.scalars(select(WorkOrderPart).where(WorkOrderPart.work_order_id == work_order_id)).all()
    return sum(row.quantity * row.unit_cost for row in rows)


def get_employee_van_inventory(db: Session, user_id: int) -> list[StockBalance]:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    vans = db.scalars(select(Warehouse).where(Warehouse.assigned_user_id == user_id)).all()
    if not vans:
        return []

    parts = db.scalars(select(Part)).all()
    results: list[StockBalance] = []
    for van in vans:
        for part in parts:
            qty = get_stock_quantity(db, part.id, van.id)
            results.append(
                StockBalance(
                    part_id=part.id,
                    part_number=part.part_number,
                    part_name=part.name,
                    warehouse_id=van.id,
                    warehouse_name=van.name,
                    quantity=qty,
                    safety_stock=part.safety_stock,
                    is_low_stock=qty <= part.safety_stock,
                )
            )
    return results


def _validate_transaction_entities(db: Session, payload: InventoryTransactionCreate) -> None:
    if not db.get(Part, payload.part_id):
        raise HTTPException(status_code=404, detail="Part not found")

    if payload.from_warehouse_id and not db.get(Warehouse, payload.from_warehouse_id):
        raise HTTPException(status_code=404, detail="Source warehouse not found")

    if payload.to_warehouse_id and not db.get(Warehouse, payload.to_warehouse_id):
        raise HTTPException(status_code=404, detail="Destination warehouse not found")

    for field, warehouse_id in (("from_location_id", payload.from_warehouse_id), ("to_location_id", payload.to_warehouse_id)):
        location_id = getattr(payload, field)
        if location_id:
            location = db.get(StorageLocation, location_id)
            if not location:
                raise HTTPException(status_code=404, detail=f"{field} not found")
            if location.warehouse_id != warehouse_id:
                raise HTTPException(status_code=400, detail=f"{field} does not belong to the selected warehouse")

    if payload.user_id and not db.get(User, payload.user_id):
        raise HTTPException(status_code=404, detail="User not found")

    if payload.work_order_id and not db.get(WorkOrder, payload.work_order_id):
        raise HTTPException(status_code=404, detail="Work order not found")


def _validate_work_order_usage_entities(db: Session, payload: WorkOrderPartCreate) -> None:
    if not db.get(WorkOrder, payload.work_order_id):
        raise HTTPException(status_code=404, detail="Work order not found")
    if not db.get(Part, payload.part_id):
        raise HTTPException(status_code=404, detail="Part not found")
    if not db.get(Warehouse, payload.warehouse_id):
        raise HTTPException(status_code=404, detail="Warehouse not found")
    if payload.user_id and not db.get(User, payload.user_id):
        raise HTTPException(status_code=404, detail="User not found")


def _write_transaction(db: Session):
    if db.in_transaction():
        return db.begin_nested()
    return db.begin()
