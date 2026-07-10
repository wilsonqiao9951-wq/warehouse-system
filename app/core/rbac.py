from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException
from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

from app.core.config import settings
from app.core.database import get_db
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


TENANT_MODELS = (
    User,
    Warehouse,
    Part,
    WorkOrder,
    InventoryTransaction,
    WorkOrderPart,
    QCPicture,
    JobStatus,
    ReturnEquipment,
    AuditLog,
)


@event.listens_for(Session, "do_orm_execute")
def _apply_tenant_read_scope(execute_state) -> None:
    organization_id = execute_state.session.info.get("organization_id")
    if not organization_id or not execute_state.is_select:
        return
    statement = execute_state.statement
    for model in TENANT_MODELS:
        statement = statement.options(
            with_loader_criteria(
                model,
                lambda entity: entity.organization_id == organization_id,
                include_aliases=True,
            )
        )
    execute_state.statement = statement


@event.listens_for(Session, "before_flush")
def _apply_tenant_write_scope(session: Session, _flush_context, _instances) -> None:
    organization_id = session.info.get("organization_id")
    if not organization_id:
        return
    for item in session.new:
        if not hasattr(item, "organization_id"):
            continue
        item_organization_id = getattr(item, "organization_id")
        if item_organization_id is None:
            setattr(item, "organization_id", organization_id)
        elif item_organization_id != organization_id:
            raise ValueError("Cross-organization writes are not allowed")


@dataclass
class Actor:
    user_id: int | None
    role: UserRole
    organization_id: int


def get_current_actor(
    db: Session = Depends(get_db),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
) -> Actor:
    if not settings.rbac_enforce:
        db.info["organization_id"] = 1
        return Actor(user_id=None, role=UserRole.ADMIN, organization_id=1)

    if not x_user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-Id header")
    try:
        user_id = int(x_user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid X-User-Id header") from exc

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    db.info["organization_id"] = user.organization_id
    return Actor(user_id=user.id, role=user.role, organization_id=user.organization_id)


def require_roles(actor: Actor, *roles: UserRole) -> None:
    if actor.role == UserRole.ADMIN:
        return
    if actor.role not in roles:
        raise HTTPException(status_code=403, detail="Insufficient permissions")


def require_work_order_scope(db: Session, actor: Actor, work_order_id: int) -> None:
    work_order = db.get(WorkOrder, work_order_id)
    if not work_order:
        raise HTTPException(status_code=404, detail="Work order not found")
    if work_order.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Work order not found")
    if actor.role in {UserRole.ADMIN, UserRole.MANAGER}:
        return
    if actor.role == UserRole.ENGINEER:
        if not actor.user_id or actor.user_id not in {work_order.assigned_user_id, work_order.engineer_id}:
            raise HTTPException(status_code=403, detail="Access denied for this work order")
        return
    if actor.role == UserRole.WAREHOUSE:
        return
    raise HTTPException(status_code=403, detail="Access denied for this work order")
