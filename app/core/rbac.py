from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models import User, UserRole, WorkOrder


@dataclass
class Actor:
    user_id: int | None
    role: UserRole


def get_current_actor(
    db: Session = Depends(get_db),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
) -> Actor:
    if not settings.rbac_enforce:
        return Actor(user_id=None, role=UserRole.ADMIN)

    if not x_user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-Id header")
    try:
        user_id = int(x_user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid X-User-Id header") from exc

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return Actor(user_id=user.id, role=user.role)


def require_roles(actor: Actor, *roles: UserRole) -> None:
    if actor.role == UserRole.ADMIN:
        return
    if actor.role not in roles:
        raise HTTPException(status_code=403, detail="Insufficient permissions")


def require_work_order_scope(db: Session, actor: Actor, work_order_id: int) -> None:
    if actor.role in {UserRole.ADMIN, UserRole.MANAGER}:
        return
    work_order = db.get(WorkOrder, work_order_id)
    if not work_order:
        raise HTTPException(status_code=404, detail="Work order not found")
    if actor.role == UserRole.ENGINEER:
        if not actor.user_id or actor.user_id not in {work_order.assigned_user_id, work_order.engineer_id}:
            raise HTTPException(status_code=403, detail="Access denied for this work order")
        return
    if actor.role == UserRole.WAREHOUSE:
        return
    raise HTTPException(status_code=403, detail="Access denied for this work order")
