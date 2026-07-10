from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from openpyxl import Workbook, load_workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import settings
from app.core.rbac import Actor, get_current_actor, require_roles, require_work_order_scope
from app.models import (
    AuditLog,
    InventoryTransaction,
    JobStatus,
    Part,
    QCPicture,
    ReturnEquipment,
    User,
    UserRole,
    Warehouse,
    WorkOrder,
    WorkOrderPart,
)
from app.schemas import (
    AbnormalUsageRow,
    JobStatusCreate,
    JobStatusRead,
    QCPictureCreate,
    QCPictureRead,
    ReturnEquipmentCreate,
    ReturnEquipmentRead,
    InventoryTransactionCreate,
    LowStockAlert,
    WorkOrderFlowAction,
    InventoryTransactionRead,
    AdminWarehouseDashboard,
    EngineerDashboard,
    PartCreate,
    PartRead,
    StockBalance,
    UserCreate,
    UserRead,
    WarehouseCreate,
    WarehouseRead,
    WorkOrderCreate,
    WorkOrderPartCreate,
    WorkOrderPartRead,
    WorkOrderProfit,
    WorkOrderRead,
    WorkOrderUpdate,
    WarehouseSummary,
)
from app.services.inventory import (
    create_transaction,
    get_employee_van_inventory,
    get_stock_balances,
    get_work_order_parts_cost,
    use_part_on_work_order,
)

router = APIRouter()


def _audit(
    db: Session,
    actor: Actor,
    action: str,
    entity_type: str,
    entity_id: int | None = None,
    metadata: dict | None = None,
):
    db.add(
        AuditLog(
            user_id=actor.user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            metadata_json=str(metadata or {}),
            timestamp=datetime.utcnow(),
        )
    )


def _image_extension(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in {
        b"heic", b"heix", b"hevc", b"hevx", b"mif1",
    }:
        return ".heic"
    return None


@router.post("/uploads/work-order-parts")
async def upload_work_order_part_photo(
    work_order_id: int = Form(..., ge=1),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_work_order_scope(db, actor, work_order_id)

    data = await file.read(settings.max_image_upload_bytes + 1)
    if len(data) > settings.max_image_upload_bytes:
        raise HTTPException(status_code=413, detail="Image exceeds the configured upload limit")
    ext = _image_extension(data)
    if not ext:
        raise HTTPException(status_code=400, detail="Unsupported or invalid image file")

    target_dir = Path("uploads/work-order-parts")
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}{ext}"
    target_path = target_dir / filename

    target_path.write_bytes(data)
    return {"url": f"/uploads/work-order-parts/{filename}"}


@router.post("/users", response_model=UserRead)
def create_user(payload: UserCreate, db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)):
    require_roles(actor, UserRole.ADMIN)
    item = User(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/users", response_model=list[UserRead])
def list_users(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    return db.scalars(select(User).order_by(User.id.desc()).offset(skip).limit(limit)).all()


@router.post("/warehouses", response_model=WarehouseRead)
def create_warehouse(payload: WarehouseCreate, db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    item = Warehouse(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/warehouses", response_model=list[WarehouseRead])
def list_warehouses(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    return db.scalars(select(Warehouse).order_by(Warehouse.id.desc()).offset(skip).limit(limit)).all()


@router.post("/parts", response_model=PartRead)
def create_part(payload: PartCreate, db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    item = Part(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/parts", response_model=list[PartRead])
def list_parts(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE, UserRole.ENGINEER)
    return db.scalars(select(Part).order_by(Part.id.desc()).offset(skip).limit(limit)).all()


@router.post("/work-orders", response_model=WorkOrderRead)
def create_work_order(payload: WorkOrderCreate, db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    data = payload.model_dump()
    if not data.get("ticket_number"):
        data["ticket_number"] = data.get("wo_number")
    if not data.get("wo_number"):
        data["wo_number"] = data.get("ticket_number")
    if not data.get("store_name") and data.get("outlet_name"):
        data["store_name"] = data["outlet_name"]
    if not data.get("outlet_name") and data.get("store_name"):
        data["outlet_name"] = data["store_name"]
    if not data.get("problem_description") and data.get("description"):
        data["problem_description"] = data["description"]
    if not data.get("description") and data.get("problem_description"):
        data["description"] = data["problem_description"]
    if not data.get("engineer_id") and data.get("assigned_user_id"):
        data["engineer_id"] = data["assigned_user_id"]
    if not data.get("assigned_user_id") and data.get("engineer_id"):
        data["assigned_user_id"] = data["engineer_id"]
    item = WorkOrder(**data)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/work-orders", response_model=list[WorkOrderRead])
def list_work_orders(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    technician_id: int | None = Query(default=None, ge=1),
    status: str | None = Query(default=None),
    city: str | None = Query(default=None),
    job_type: str | None = Query(default=None),
    q: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    stmt = select(WorkOrder).order_by(WorkOrder.id.desc())
    if actor.role == UserRole.ENGINEER and actor.user_id:
        stmt = stmt.where((WorkOrder.assigned_user_id == actor.user_id) | (WorkOrder.engineer_id == actor.user_id))
    elif actor.role not in {UserRole.ADMIN, UserRole.MANAGER}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if technician_id:
        stmt = stmt.where((WorkOrder.assigned_user_id == technician_id) | (WorkOrder.engineer_id == technician_id))
    if status:
        stmt = stmt.where(func.lower(WorkOrder.status) == status.lower())
    if city:
        stmt = stmt.where(func.lower(WorkOrder.city) == city.lower())
    if job_type:
        stmt = stmt.where(func.lower(WorkOrder.job_type) == job_type.lower())
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            (func.lower(WorkOrder.ticket_number).like(like))
            | (func.lower(func.coalesce(WorkOrder.wo_number, "")).like(like))
            | (func.lower(func.coalesce(WorkOrder.outlet_name, "")).like(like))
            | (func.lower(func.coalesce(WorkOrder.address, "")).like(like))
        )
    if date_from:
        stmt = stmt.where(WorkOrder.schedule_date >= date_from)
    if date_to:
        stmt = stmt.where(WorkOrder.schedule_date <= date_to)
    return db.scalars(stmt.offset(skip).limit(limit)).all()


@router.patch("/work-orders/{work_order_id}", response_model=WorkOrderRead)
def update_work_order(
    work_order_id: int,
    payload: WorkOrderUpdate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_work_order_scope(db, actor, work_order_id)
    item = db.get(WorkOrder, work_order_id)
    if not item:
        raise HTTPException(status_code=404, detail="Work order not found")
    if item.is_locked:
        raise HTTPException(status_code=400, detail="Work order is locked and cannot be edited")

    updates = payload.model_dump(exclude_unset=True)
    if actor.role == UserRole.ENGINEER:
        blocked = {"revenue", "labor_cost", "assigned_user_id", "engineer_id", "assistant_id"}
        for key in blocked:
            updates.pop(key, None)
    if "ticket_number" in updates and "wo_number" not in updates:
        updates["wo_number"] = updates["ticket_number"]
    if "wo_number" in updates and "ticket_number" not in updates:
        updates["ticket_number"] = updates["wo_number"]
    if "outlet_name" in updates and "store_name" not in updates:
        updates["store_name"] = updates["outlet_name"]
    if "store_name" in updates and "outlet_name" not in updates:
        updates["outlet_name"] = updates["store_name"]
    if "description" in updates and "problem_description" not in updates:
        updates["problem_description"] = updates["description"]
    if "problem_description" in updates and "description" not in updates:
        updates["description"] = updates["problem_description"]
    if "engineer_id" in updates and "assigned_user_id" not in updates:
        updates["assigned_user_id"] = updates["engineer_id"]
    if "assigned_user_id" in updates and "engineer_id" not in updates:
        updates["engineer_id"] = updates["assigned_user_id"]

    for key, value in updates.items():
        setattr(item, key, value)

    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.post("/work-orders/{work_order_id}/start", response_model=WorkOrderRead)
def start_work_order(
    work_order_id: int,
    payload: WorkOrderFlowAction,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_work_order_scope(db, actor, work_order_id)
    item = db.get(WorkOrder, work_order_id)
    if not item:
        raise HTTPException(status_code=404, detail="Work order not found")
    if item.is_locked:
        raise HTTPException(status_code=400, detail="Work order is locked and cannot be started")
    item.status = "IN_PROGRESS"
    item.started_at = item.started_at or datetime.utcnow()
    db.add(item)
    db.add(JobStatus(work_order_id=work_order_id, status="IN_PROGRESS", timestamp=datetime.utcnow()))
    _audit(db, actor, "start_job", "work_order", work_order_id)
    db.commit()
    db.refresh(item)
    return item


@router.post("/work-orders/{work_order_id}/complete", response_model=WorkOrderRead)
def complete_work_order(
    work_order_id: int,
    payload: WorkOrderFlowAction,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_work_order_scope(db, actor, work_order_id)
    item = db.get(WorkOrder, work_order_id)
    if not item:
        raise HTTPException(status_code=404, detail="Work order not found")
    if item.is_locked:
        raise HTTPException(status_code=400, detail="Work order already completed")
    _ = get_work_order_parts_cost(db, work_order_id)
    item.status = "COMPLETED"
    item.completed_at = datetime.utcnow()
    item.is_locked = True
    db.add(item)
    db.add(JobStatus(work_order_id=work_order_id, status="COMPLETED", timestamp=datetime.utcnow()))
    _audit(db, actor, "complete_job", "work_order", work_order_id, {"parts_cost": get_work_order_parts_cost(db, work_order_id)})
    db.commit()
    db.refresh(item)
    return item


@router.post("/inventory/transactions", response_model=InventoryTransactionRead)
def add_inventory_transaction(
    payload: InventoryTransactionCreate, db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    tx = create_transaction(db, payload)
    if str(payload.transaction_type).lower().endswith("transfer"):
        _audit(
            db,
            actor,
            "inventory_transfer",
            "inventory_transaction",
            tx.id,
            {"part_id": payload.part_id, "qty": payload.quantity, "from": payload.from_warehouse_id, "to": payload.to_warehouse_id},
        )
        db.commit()
    return tx


@router.get("/inventory/transactions", response_model=list[InventoryTransactionRead])
def list_inventory_transactions(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    return db.scalars(
        select(InventoryTransaction).order_by(InventoryTransaction.id.desc()).offset(skip).limit(limit)
    ).all()


@router.get("/inventory/balances", response_model=list[StockBalance])
def inventory_balances(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    rows = get_stock_balances(db)
    return rows[skip : skip + limit]


@router.get("/employees/{user_id}/van-inventory", response_model=list[StockBalance])
def employee_van_inventory(
    user_id: int,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    if actor.role == UserRole.ENGINEER and actor.user_id != user_id:
        raise HTTPException(status_code=403, detail="Can only view own van inventory")
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.ENGINEER)
    rows = get_employee_van_inventory(db, user_id)
    return rows[skip : skip + limit]


@router.post(
    "/work-order-parts",
    response_model=WorkOrderPartRead,
    deprecated=True,
    summary="Deprecated: use /work-orders/{work_order_id}/use-part",
)
def add_work_order_part(payload: WorkOrderPartCreate, db: Session = Depends(get_db)):
    return use_part_on_work_order(db, payload)


@router.post(
    "/work-orders/{work_order_id}/use-part",
    response_model=WorkOrderPartRead,
    summary="Use a part on work order",
)
def use_part_for_work_order(
    work_order_id: int,
    payload: WorkOrderPartCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_work_order_scope(db, actor, work_order_id)
    if payload.work_order_id != work_order_id:
        raise HTTPException(status_code=400, detail="Path work order ID must match payload work_order_id")
    usage = use_part_on_work_order(db, payload)
    _audit(db, actor, "use_part", "work_order_part", usage.id, {"work_order_id": work_order_id, "part_id": payload.part_id, "qty": payload.quantity})
    db.commit()
    return usage


@router.get("/work-order-parts", response_model=list[WorkOrderPartRead])
def list_work_order_parts(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    stmt = select(WorkOrderPart).order_by(WorkOrderPart.id.desc())
    if actor.role == UserRole.ENGINEER and actor.user_id:
        stmt = stmt.where(WorkOrderPart.user_id == actor.user_id)
    elif actor.role not in {UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return db.scalars(stmt.offset(skip).limit(limit)).all()


@router.post("/qc-pictures", response_model=QCPictureRead)
def create_qc_picture(
    payload: QCPictureCreate, db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)
):
    require_work_order_scope(db, actor, payload.work_order_id)
    if not db.get(WorkOrder, payload.work_order_id):
        raise HTTPException(status_code=404, detail="Work order not found")
    if payload.uploaded_by and not db.get(User, payload.uploaded_by):
        raise HTTPException(status_code=404, detail="User not found")
    item = QCPicture(**payload.model_dump())
    db.add(item)
    _audit(db, actor, "upload_qc_picture", "qc_picture", None, {"work_order_id": payload.work_order_id})
    db.commit()
    db.refresh(item)
    return item


@router.get("/qc-pictures", response_model=list[QCPictureRead])
def list_qc_pictures(
    work_order_id: int | None = Query(default=None, ge=1),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    stmt = select(QCPicture).order_by(QCPicture.id.desc())
    if work_order_id:
        require_work_order_scope(db, actor, work_order_id)
        stmt = stmt.where(QCPicture.work_order_id == work_order_id)
    elif actor.role == UserRole.ENGINEER:
        raise HTTPException(status_code=403, detail="work_order_id is required for technician scope")
    return db.scalars(stmt.offset(skip).limit(limit)).all()


@router.post("/job-status", response_model=JobStatusRead)
def create_job_status(
    payload: JobStatusCreate, db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)
):
    require_work_order_scope(db, actor, payload.work_order_id)
    if not db.get(WorkOrder, payload.work_order_id):
        raise HTTPException(status_code=404, detail="Work order not found")
    work_order = db.get(WorkOrder, payload.work_order_id)
    if work_order and work_order.is_locked:
        raise HTTPException(status_code=400, detail="Work order is locked and cannot be edited")
    data = payload.model_dump()
    if not data.get("timestamp"):
        data["timestamp"] = datetime.utcnow()
    item = JobStatus(**data)
    db.add(item)
    _audit(db, actor, "update_status", "job_status", None, {"work_order_id": payload.work_order_id, "status": data.get("status")})
    db.commit()
    db.refresh(item)
    return item


@router.get("/job-status", response_model=list[JobStatusRead])
def list_job_status(
    work_order_id: int | None = Query(default=None, ge=1),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    stmt = select(JobStatus).order_by(JobStatus.id.desc())
    if work_order_id:
        require_work_order_scope(db, actor, work_order_id)
        stmt = stmt.where(JobStatus.work_order_id == work_order_id)
    elif actor.role == UserRole.ENGINEER:
        raise HTTPException(status_code=403, detail="work_order_id is required for technician scope")
    return db.scalars(stmt.offset(skip).limit(limit)).all()


@router.post("/return-equipments", response_model=ReturnEquipmentRead)
def create_return_equipment(
    payload: ReturnEquipmentCreate, db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)
):
    require_work_order_scope(db, actor, payload.work_order_id)
    if not db.get(WorkOrder, payload.work_order_id):
        raise HTTPException(status_code=404, detail="Work order not found")
    work_order = db.get(WorkOrder, payload.work_order_id)
    if work_order and work_order.is_locked:
        raise HTTPException(status_code=400, detail="Work order is locked and cannot be edited")
    item = ReturnEquipment(**payload.model_dump())
    db.add(item)
    _audit(
        db,
        actor,
        "return_equipment",
        "return_equipment",
        None,
        {"work_order_id": payload.work_order_id, "equipment_type": payload.equipment_type, "quantity": payload.quantity},
    )
    db.commit()
    db.refresh(item)
    return item


@router.get("/audit-logs")
def list_audit_logs(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).offset(skip).limit(limit)).all()
    return [
        {
            "id": row.id,
            "user_id": row.user_id,
            "action": row.action,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "timestamp": row.timestamp.isoformat() if row.timestamp else None,
            "metadata": row.metadata_json,
        }
        for row in rows
    ]


@router.get("/return-equipments", response_model=list[ReturnEquipmentRead])
def list_return_equipments(
    work_order_id: int | None = Query(default=None, ge=1),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    stmt = select(ReturnEquipment).order_by(ReturnEquipment.id.desc())
    if work_order_id:
        require_work_order_scope(db, actor, work_order_id)
        stmt = stmt.where(ReturnEquipment.work_order_id == work_order_id)
    elif actor.role == UserRole.ENGINEER:
        raise HTTPException(status_code=403, detail="work_order_id is required for technician scope")
    return db.scalars(stmt.offset(skip).limit(limit)).all()


@router.get("/work-orders/{work_order_id}/profit", response_model=WorkOrderProfit)
def work_order_profit(work_order_id: int, db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    work_order = db.get(WorkOrder, work_order_id)
    if not work_order:
        raise HTTPException(status_code=404, detail="Work order not found")

    parts_cost = get_work_order_parts_cost(db, work_order_id)
    return WorkOrderProfit(
        work_order_id=work_order_id,
        ticket_number=work_order.ticket_number,
        wo_number=work_order.wo_number,
        revenue=work_order.revenue,
        labor_cost=work_order.labor_cost,
        parts_cost=parts_cost,
        profit=work_order.revenue - work_order.labor_cost - parts_cost,
    )


@router.get("/export/inventory.xlsx")
def export_inventory_excel(db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    balances = get_stock_balances(db)
    wb = Workbook()
    ws = wb.active
    ws.title = "Inventory Balance"
    ws.append(["Part ID", "Part Number", "Part Name", "Warehouse ID", "Warehouse", "Quantity", "Safety Stock", "Low Stock"])
    for row in balances:
        ws.append([
            row.part_id,
            row.part_number,
            row.part_name,
            row.warehouse_id,
            row.warehouse_name,
            row.quantity,
            row.safety_stock,
            "YES" if row.is_low_stock else "NO",
        ])

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=inventory.xlsx"},
    )


@router.get("/export/parts.xlsx")
def export_parts_excel(db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    rows = db.scalars(select(Part).order_by(Part.id.asc())).all()
    wb = Workbook()
    ws = wb.active
    ws.title = "Parts"
    ws.append(["part_number", "name", "unit", "default_cost", "safety_stock", "supplier", "notes"])
    for row in rows:
        ws.append([row.part_number, row.name, row.unit, row.default_cost, row.safety_stock, row.supplier, row.notes])

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=parts.xlsx"},
    )


@router.post("/import/parts.xlsx")
async def import_parts_excel(
    file: UploadFile = File(...), db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Please upload an .xlsx file")

    content = await file.read()
    wb = load_workbook(filename=BytesIO(content), data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    created = 0
    updated = 0

    for row in rows:
        if not row or not row[0]:
            continue
        part_number = str(row[0]).strip()
        name = str(row[1]).strip() if row[1] else part_number
        unit = str(row[2]).strip() if row[2] else "pcs"
        default_cost = float(row[3] or 0)
        safety_stock = int(row[4] or 0)
        supplier = str(row[5]).strip() if row[5] else None
        notes = str(row[6]).strip() if row[6] else None

        item = db.scalar(select(Part).where(Part.part_number == part_number))
        if item:
            item.name = name
            item.unit = unit
            item.default_cost = default_cost
            item.safety_stock = safety_stock
            item.supplier = supplier
            item.notes = notes
            updated += 1
        else:
            db.add(
                Part(
                    part_number=part_number,
                    name=name,
                    unit=unit,
                    default_cost=default_cost,
                    safety_stock=safety_stock,
                    supplier=supplier,
                    notes=notes,
                )
            )
            created += 1
    db.commit()
    return {"created": created, "updated": updated}


@router.get("/export/work-orders.xlsx")
def export_work_orders_excel(db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    rows = db.scalars(select(WorkOrder).order_by(WorkOrder.id.asc())).all()
    wb = Workbook()
    ws = wb.active
    ws.title = "WorkOrders"
    ws.append(
        [
            "wo_number",
            "ticket_number",
            "schedule_date",
            "outlet_name",
            "job_type",
            "description",
            "address",
            "city",
            "state",
            "zip",
            "contact_phone",
            "status",
            "revenue",
            "labor_cost",
            "assigned_user_id",
            "engineer_id",
        ]
    )
    for row in rows:
        ws.append(
            [
                row.wo_number,
                row.ticket_number,
                row.schedule_date.isoformat() if row.schedule_date else None,
                row.outlet_name,
                row.job_type,
                row.description,
                row.address,
                row.city,
                row.state,
                row.zip,
                row.contact_phone,
                row.status,
                row.revenue,
                row.labor_cost,
                row.assigned_user_id,
                row.engineer_id,
            ]
        )

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=work-orders.xlsx"},
    )


@router.post("/import/work-orders.xlsx")
async def import_work_orders_excel(
    file: UploadFile = File(...), db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Please upload an .xlsx file")

    content = await file.read()
    wb = load_workbook(filename=BytesIO(content), data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    created = 0
    updated = 0

    for row in rows:
        if not row:
            continue
        wo_number = str(row[0]).strip() if row[0] else None
        ticket_number = str(row[1]).strip() if row[1] else None
        if not wo_number and not ticket_number:
            continue
        if not ticket_number:
            ticket_number = wo_number
        if not wo_number:
            wo_number = ticket_number

        item = db.scalar(select(WorkOrder).where(WorkOrder.ticket_number == ticket_number))
        if not item and wo_number:
            item = db.scalar(select(WorkOrder).where(WorkOrder.wo_number == wo_number))

        schedule_date = None
        if row[2]:
            if isinstance(row[2], datetime):
                schedule_date = row[2].date()
            else:
                schedule_date = datetime.fromisoformat(str(row[2])).date()

        payload = {
            "wo_number": wo_number,
            "ticket_number": ticket_number,
            "schedule_date": schedule_date,
            "outlet_name": str(row[3]).strip() if row[3] else None,
            "store_name": str(row[3]).strip() if row[3] else None,
            "job_type": str(row[4]).strip() if row[4] else None,
            "description": str(row[5]).strip() if row[5] else None,
            "problem_description": str(row[5]).strip() if row[5] else None,
            "address": str(row[6]).strip() if row[6] else None,
            "city": str(row[7]).strip() if row[7] else None,
            "state": str(row[8]).strip() if row[8] else None,
            "zip": str(row[9]).strip() if row[9] else None,
            "contact_phone": str(row[10]).strip() if row[10] else None,
            "status": str(row[11]).strip() if row[11] else "open",
            "revenue": float(row[12] or 0),
            "labor_cost": float(row[13] or 0),
            "assigned_user_id": int(row[14]) if row[14] else None,
            "engineer_id": int(row[15]) if row[15] else None,
        }
        if payload["assigned_user_id"] and not payload["engineer_id"]:
            payload["engineer_id"] = payload["assigned_user_id"]
        if payload["engineer_id"] and not payload["assigned_user_id"]:
            payload["assigned_user_id"] = payload["engineer_id"]

        if item:
            for key, value in payload.items():
                setattr(item, key, value)
            updated += 1
        else:
            db.add(WorkOrder(**payload))
            created += 1

    db.commit()
    return {"created": created, "updated": updated}


@router.get("/dashboard/engineers/{user_id}", response_model=EngineerDashboard)
def engineer_dashboard(
    user_id: int,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.ENGINEER)
    if actor.role == UserRole.ENGINEER and actor.user_id != user_id:
        raise HTTPException(status_code=403, detail="Technicians can only view their own dashboard")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    open_work_orders = db.scalar(
        select(func.count(WorkOrder.id)).where(
            WorkOrder.assigned_user_id == user_id,
            WorkOrder.status != "completed",
        )
    )
    completed_work_orders = db.scalar(
        select(func.count(WorkOrder.id)).where(
            WorkOrder.assigned_user_id == user_id,
            WorkOrder.status == "completed",
        )
    )
    van_inventory = get_employee_van_inventory(db, user_id)
    low_stock_items = sum(1 for item in van_inventory if item.is_low_stock)

    return EngineerDashboard(
        user_id=user.id,
        user_name=user.name,
        open_work_orders=open_work_orders or 0,
        completed_work_orders=completed_work_orders or 0,
        van_low_stock_items=low_stock_items,
        van_inventory=van_inventory,
    )


@router.get("/dashboard/admin/warehouses", response_model=AdminWarehouseDashboard)
def admin_warehouse_dashboard(
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    warehouses = db.scalars(select(Warehouse).order_by(Warehouse.id.asc())).all()
    all_balances = get_stock_balances(db)
    total_parts = db.scalar(select(func.count(Part.id))) or 0

    warehouse_rows: list[WarehouseSummary] = []
    total_low_stock = 0
    for warehouse in warehouses:
        rows = [balance for balance in all_balances if balance.warehouse_id == warehouse.id]
        low_stock_items = sum(1 for row in rows if row.is_low_stock)
        total_low_stock += low_stock_items

        warehouse_rows.append(
            WarehouseSummary(
                warehouse_id=warehouse.id,
                warehouse_name=warehouse.name,
                assigned_user_id=warehouse.assigned_user_id,
                assigned_user_name=warehouse.assigned_user.name if warehouse.assigned_user else None,
                total_sku=sum(1 for row in rows if row.quantity > 0),
                total_quantity=sum(row.quantity for row in rows),
                low_stock_items=low_stock_items,
            )
        )

    return AdminWarehouseDashboard(
        total_warehouses=len(warehouse_rows),
        total_parts=total_parts,
        total_low_stock_items=total_low_stock,
        warehouses=warehouse_rows,
    )


@router.get("/inventory/low-stock-alerts", response_model=list[LowStockAlert])
def low_stock_alerts(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    rows = get_stock_balances(db)
    alerts = [
        LowStockAlert(
            part_id=row.part_id,
            part_number=row.part_number,
            part_name=row.part_name,
            warehouse_id=row.warehouse_id,
            warehouse_name=row.warehouse_name,
            quantity=row.quantity,
            min_stock=max(row.safety_stock, db.get(Part, row.part_id).min_stock if db.get(Part, row.part_id) else 0),
        )
        for row in rows
        if row.is_low_stock
    ]
    return alerts[skip : skip + limit]


@router.get("/reports/abnormal-usage", response_model=list[AbnormalUsageRow])
def abnormal_usage_report(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    work_orders = db.scalars(select(WorkOrder).order_by(WorkOrder.id.asc())).all()
    if not work_orders:
        return []
    costs = sorted([get_work_order_parts_cost(db, wo.id) for wo in work_orders if get_work_order_parts_cost(db, wo.id) > 0])
    if costs:
        idx = min(len(costs) - 1, int(0.9 * (len(costs) - 1)))
        p90_cost = costs[idx]
    else:
        p90_cost = 0.0

    tech_avgs: dict[int, float] = {}
    tech_map: dict[int, list[float]] = {}
    for wo in work_orders:
        if not wo.engineer_id:
            continue
        tech_map.setdefault(wo.engineer_id, []).append(get_work_order_parts_cost(db, wo.id))
    for tech_id, arr in tech_map.items():
        tech_avgs[tech_id] = (sum(arr) / len(arr)) if arr else 0.0

    repeated_part_flags: dict[int, set[int]] = {}
    usage_rows = db.scalars(select(WorkOrderPart).order_by(WorkOrderPart.created_at.asc())).all()
    for row in usage_rows:
        if not row.user_id:
            continue
        repeated_part_flags.setdefault(row.user_id, set())
        # repeated same part usage in short period (7 days)
        recent_count = sum(
            1
            for r in usage_rows
            if r.user_id == row.user_id
            and r.part_id == row.part_id
            and r.created_at >= (row.created_at - timedelta(days=7))
            and r.created_at <= row.created_at
        )
        if recent_count >= 3:
            repeated_part_flags[row.user_id].add(row.work_order_id)

    results: list[AbnormalUsageRow] = []
    for wo in work_orders:
        parts_cost = get_work_order_parts_cost(db, wo.id)
        reasons: list[str] = []
        if parts_cost >= p90_cost and parts_cost > 0:
            reasons.append("Parts cost above 90th percentile")
        if wo.engineer_id and tech_avgs.get(wo.engineer_id, 0) > 0 and parts_cost > tech_avgs[wo.engineer_id] * 1.8:
            reasons.append("Technician parts usage above historical average")
        if wo.engineer_id and wo.id in repeated_part_flags.get(wo.engineer_id, set()):
            reasons.append("Repeated same-part usage in short period")
        if reasons:
            results.append(
                AbnormalUsageRow(
                    work_order_id=wo.id,
                    ticket_number=wo.ticket_number,
                    engineer_id=wo.engineer_id,
                    parts_cost=parts_cost,
                    revenue=wo.revenue,
                    severity="high" if len(reasons) > 1 else "medium",
                    reason="; ".join(reasons),
                )
            )
    return results[skip : skip + limit]


@router.get("/pilot/checklist")
def pilot_checklist(db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    low_stock = low_stock_alerts(db=db, actor=actor)
    abnormal = abnormal_usage_report(db=db, actor=actor)
    return {
        "system_health": "ok",
        "total_users": db.scalar(select(func.count(User.id))) or 0,
        "total_work_orders": db.scalar(select(func.count(WorkOrder.id))) or 0,
        "total_parts": db.scalar(select(func.count(Part.id))) or 0,
        "total_inventory_transactions": db.scalar(select(func.count(InventoryTransaction.id))) or 0,
        "low_stock_alert_count": len(low_stock),
        "abnormal_usage_alert_count": len(abnormal),
    }
