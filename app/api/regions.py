from __future__ import annotations

from datetime import datetime
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rbac import Actor, get_current_actor, require_roles
from app.models import (
    AuditLog,
    InventoryRegion,
    InventoryTransaction,
    Part,
    TransactionType,
    UserRole,
    Warehouse,
)
from app.schemas import (
    CrossRegionTransferRead,
    InventoryRegionCreate,
    InventoryRegionRead,
    InventoryRegionSummary,
    InventoryRegionUpdate,
    WarehouseRead,
    WarehouseRegionAssignment,
)
from app.services.inventory import get_stock_balances
from app.services.regions import (
    ensure_default_region,
    normalize_region_code,
    normalize_region_name,
    validate_region_timezone,
)


router = APIRouter(tags=["inventory-regions"])
REGION_ROLES = (UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
REGION_MANAGERS = (UserRole.ADMIN, UserRole.MANAGER)


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
                    "device_record_id": actor.device_record_id,
                    **metadata,
                },
                default=str,
                separators=(",", ":"),
            ),
            timestamp=datetime.utcnow(),
        )
    )


def _require_unique_identity(
    db: Session,
    code: str,
    name: str,
    *,
    exclude_id: int | None = None,
) -> None:
    query = select(InventoryRegion).where(
        or_(InventoryRegion.code == code, InventoryRegion.name == name)
    )
    if exclude_id is not None:
        query = query.where(InventoryRegion.id != exclude_id)
    duplicate = db.scalar(query.limit(1))
    if duplicate:
        field = "code" if duplicate.code == code else "name"
        raise HTTPException(status_code=409, detail=f"Region {field} already exists")


def _region(db: Session, region_id: int) -> InventoryRegion:
    region = db.get(InventoryRegion, region_id)
    if not region:
        raise HTTPException(status_code=404, detail="Inventory region not found")
    return region


@router.get("/inventory/regions", response_model=list[InventoryRegionRead])
def list_inventory_regions(
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, *REGION_ROLES)
    ensure_default_region(db, actor.organization_id)
    db.commit()
    return db.scalars(
        select(InventoryRegion).order_by(
            InventoryRegion.is_default.desc(),
            InventoryRegion.name.asc(),
        )
    ).all()


@router.get(
    "/inventory/regions/summary",
    response_model=list[InventoryRegionSummary],
)
def inventory_region_summary(
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, *REGION_ROLES)
    default_region = ensure_default_region(db, actor.organization_id)
    db.commit()
    regions = db.scalars(select(InventoryRegion).order_by(InventoryRegion.name)).all()
    warehouses = db.scalars(select(Warehouse)).all()
    region_by_warehouse = {
        warehouse.id: warehouse.region_id or default_region.id for warehouse in warehouses
    }
    balances = get_stock_balances(db)
    totals = {region.id: 0 for region in regions}
    low_stock = {region.id: 0 for region in regions}
    for row in balances:
        region_id = region_by_warehouse.get(row.warehouse_id, default_region.id)
        totals[region_id] = totals.get(region_id, 0) + row.quantity
        if row.is_low_stock:
            low_stock[region_id] = low_stock.get(region_id, 0) + 1

    cross_region_counts = {region.id: 0 for region in regions}
    transfers = db.scalars(
        select(InventoryTransaction).where(
            InventoryTransaction.transaction_type == TransactionType.TRANSFER,
            InventoryTransaction.from_warehouse_id.is_not(None),
            InventoryTransaction.to_warehouse_id.is_not(None),
        )
    ).all()
    for transfer in transfers:
        source_region = region_by_warehouse.get(transfer.from_warehouse_id)
        target_region = region_by_warehouse.get(transfer.to_warehouse_id)
        if source_region is None or target_region is None or source_region == target_region:
            continue
        cross_region_counts[source_region] = cross_region_counts.get(source_region, 0) + 1
        cross_region_counts[target_region] = cross_region_counts.get(target_region, 0) + 1

    return [
        InventoryRegionSummary(
            region_id=region.id,
            region_code=region.code,
            region_name=region.name,
            timezone=region.timezone,
            is_default=region.is_default,
            is_active=region.is_active,
            warehouse_count=sum(
                1 for item in warehouses if region_by_warehouse[item.id] == region.id
            ),
            main_warehouse_count=sum(
                1
                for item in warehouses
                if region_by_warehouse[item.id] == region.id
                and (item.warehouse_type or "main").lower() != "van"
            ),
            vehicle_warehouse_count=sum(
                1
                for item in warehouses
                if region_by_warehouse[item.id] == region.id
                and (item.warehouse_type or "main").lower() == "van"
            ),
            total_quantity=totals.get(region.id, 0),
            low_stock_sku_count=low_stock.get(region.id, 0),
            cross_region_transfer_count=cross_region_counts.get(region.id, 0),
        )
        for region in regions
    ]


@router.get(
    "/inventory/regions/cross-region-transfers",
    response_model=list[CrossRegionTransferRead],
)
def list_cross_region_transfers(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, *REGION_ROLES)
    default_region = ensure_default_region(db, actor.organization_id)
    db.commit()
    regions = {item.id: item for item in db.scalars(select(InventoryRegion)).all()}
    warehouses = {item.id: item for item in db.scalars(select(Warehouse)).all()}
    parts = {item.id: item for item in db.scalars(select(Part)).all()}
    rows: list[CrossRegionTransferRead] = []
    transactions = db.scalars(
        select(InventoryTransaction)
        .where(
            InventoryTransaction.transaction_type == TransactionType.TRANSFER,
            InventoryTransaction.from_warehouse_id.is_not(None),
            InventoryTransaction.to_warehouse_id.is_not(None),
        )
        .order_by(InventoryTransaction.id.desc())
    ).all()
    for transaction in transactions:
        source = warehouses.get(transaction.from_warehouse_id)
        target = warehouses.get(transaction.to_warehouse_id)
        part = parts.get(transaction.part_id)
        if not source or not target or not part:
            continue
        source_region_id = source.region_id or default_region.id
        target_region_id = target.region_id or default_region.id
        if source_region_id == target_region_id:
            continue
        source_region = regions.get(source_region_id)
        target_region = regions.get(target_region_id)
        if not source_region or not target_region:
            continue
        rows.append(
            CrossRegionTransferRead(
                transaction_id=transaction.id,
                created_at=transaction.created_at,
                part_id=part.id,
                part_number=part.part_number,
                part_name=part.name,
                quantity=transaction.quantity,
                from_warehouse_id=source.id,
                from_warehouse_name=source.name,
                from_region_id=source_region.id,
                from_region_name=source_region.name,
                to_warehouse_id=target.id,
                to_warehouse_name=target.name,
                to_region_id=target_region.id,
                to_region_name=target_region.name,
            )
        )
        if len(rows) >= limit:
            break
    return rows


@router.post(
    "/inventory/regions",
    response_model=InventoryRegionRead,
    status_code=201,
)
def create_inventory_region(
    payload: InventoryRegionCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, *REGION_MANAGERS)
    ensure_default_region(db, actor.organization_id)
    code = normalize_region_code(payload.code)
    name = normalize_region_name(payload.name)
    timezone_name = validate_region_timezone(payload.timezone)
    if payload.is_default and not payload.is_active:
        raise HTTPException(status_code=422, detail="The default region must be active")
    _require_unique_identity(db, code, name)
    now = datetime.utcnow()
    if payload.is_default:
        current_default = db.scalar(
            select(InventoryRegion).where(InventoryRegion.is_default.is_(True))
        )
        if current_default:
            current_default.is_default = False
            current_default.version += 1
            current_default.updated_at = now
            db.add(current_default)
    region = InventoryRegion(
        organization_id=actor.organization_id,
        code=code,
        name=name,
        timezone=timezone_name,
        is_default=payload.is_default,
        is_active=payload.is_active,
        created_at=now,
        updated_at=now,
    )
    db.add(region)
    db.flush()
    _audit(
        db,
        actor,
        "create_inventory_region",
        "inventory_region",
        region.id,
        {
            "code": region.code,
            "name": region.name,
            "timezone": region.timezone,
            "is_default": region.is_default,
        },
    )
    db.commit()
    db.refresh(region)
    return region


@router.patch(
    "/inventory/regions/{region_id}",
    response_model=InventoryRegionRead,
)
def update_inventory_region(
    region_id: int,
    payload: InventoryRegionUpdate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, *REGION_MANAGERS)
    region = _region(db, region_id)
    if region.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Inventory region has changed; refresh and retry")
    updates = payload.model_dump(exclude_unset=True, exclude={"expected_version"})
    code = normalize_region_code(updates.get("code", region.code))
    name = normalize_region_name(updates.get("name", region.name))
    timezone_name = validate_region_timezone(updates.get("timezone", region.timezone))
    target_default = updates.get("is_default", region.is_default)
    target_active = updates.get("is_active", region.is_active)
    if region.is_default and not target_default:
        raise HTTPException(status_code=409, detail="Choose another default region before removing this default")
    if target_default and not target_active:
        raise HTTPException(status_code=422, detail="The default region must be active")
    if not target_active and db.scalar(
        select(Warehouse.id).where(Warehouse.region_id == region.id).limit(1)
    ):
        raise HTTPException(status_code=409, detail="Move warehouses before deactivating this region")
    _require_unique_identity(db, code, name, exclude_id=region.id)
    before = {
        "code": region.code,
        "name": region.name,
        "timezone": region.timezone,
        "is_default": region.is_default,
        "is_active": region.is_active,
        "version": region.version,
    }
    now = datetime.utcnow()
    if target_default and not region.is_default:
        current_default = db.scalar(
            select(InventoryRegion).where(
                InventoryRegion.is_default.is_(True),
                InventoryRegion.id != region.id,
            )
        )
        if current_default:
            current_default.is_default = False
            current_default.version += 1
            current_default.updated_at = now
            db.add(current_default)
    region.code = code
    region.name = name
    region.timezone = timezone_name
    region.is_default = target_default
    region.is_active = target_active
    region.version += 1
    region.updated_at = now
    db.add(region)
    _audit(
        db,
        actor,
        "update_inventory_region",
        "inventory_region",
        region.id,
        {
            "before": before,
            "after": {
                "code": region.code,
                "name": region.name,
                "timezone": region.timezone,
                "is_default": region.is_default,
                "is_active": region.is_active,
                "version": region.version,
            },
        },
    )
    db.commit()
    db.refresh(region)
    return region


@router.put(
    "/warehouses/{warehouse_id}/region",
    response_model=WarehouseRead,
)
def assign_warehouse_region(
    warehouse_id: int,
    payload: WarehouseRegionAssignment,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, *REGION_MANAGERS)
    warehouse = db.get(Warehouse, warehouse_id)
    if not warehouse:
        raise HTTPException(status_code=404, detail="Warehouse not found")
    region = _region(db, payload.region_id)
    if not region.is_active:
        raise HTTPException(status_code=409, detail="Warehouse cannot be assigned to an inactive region")
    if warehouse.region_id != payload.expected_region_id:
        raise HTTPException(status_code=409, detail="Warehouse region has changed; refresh and retry")
    reason = payload.reason.strip()
    if len(reason) < 3:
        raise HTTPException(status_code=422, detail="Assignment reason must contain at least 3 characters")
    previous_region_id = warehouse.region_id
    warehouse.region_id = region.id
    warehouse.updated_at = datetime.utcnow()
    db.add(warehouse)
    _audit(
        db,
        actor,
        "assign_warehouse_region",
        "warehouse",
        warehouse.id,
        {
            "warehouse_name": warehouse.name,
            "previous_region_id": previous_region_id,
            "region_id": region.id,
            "region_name": region.name,
            "reason": reason,
        },
    )
    db.commit()
    db.refresh(warehouse)
    return warehouse
