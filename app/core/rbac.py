from dataclasses import dataclass
from hashlib import sha256
import secrets

from fastapi import Depends, Header, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import event, select
from sqlalchemy.orm import Session, with_loader_criteria

from app.core.config import settings
from app.core.database import get_db
from app.core.security import decode_access_token
from app.models import (
    AuditLog,
    CompletionPolicy,
    Customer,
    Equipment,
    ImportBatch,
    InventoryNotification,
    InventoryTransaction,
    JobStatus,
    Organization,
    Part,
    PartMachineAssociation,
    QCPicture,
    ReplenishmentRequest,
    ReturnEquipment,
    StorageLocation,
    User,
    UserDevice,
    UserInvitation,
    UserRole,
    Warehouse,
    WorkOrder,
    WorkOrderPart,
    WorkOrderPartMemory,
    WorkOrderVoiceNote,
)


TENANT_MODELS = (
    CompletionPolicy,
    Customer,
    Equipment,
    User,
    UserDevice,
    Warehouse,
    StorageLocation,
    Part,
    PartMachineAssociation,
    WorkOrder,
    InventoryTransaction,
    WorkOrderPart,
    WorkOrderPartMemory,
    QCPicture,
    JobStatus,
    ReturnEquipment,
    AuditLog,
    InventoryNotification,
    ReplenishmentRequest,
    ImportBatch,
    UserInvitation,
    WorkOrderVoiceNote,
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


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
    is_platform_admin: bool = False
    auth_method: str = "none"
    device_id: str | None = None
    device_record_id: int | None = None
    device_verified: bool = False
    claim_version: int | None = None


def get_current_actor(
    db: Session = Depends(get_db),
    token: str | None = Depends(oauth2_scheme),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_device_token: str | None = Header(default=None, alias="X-Device-Token"),
    x_claim_version: int | None = Header(default=None, alias="X-Claim-Version"),
) -> Actor:
    if not settings.rbac_enforce:
        db.info["organization_id"] = 1
        return Actor(user_id=None, role=UserRole.ADMIN, organization_id=1, is_platform_admin=True, auth_method="test")

    token_organization_id: int | None = None
    token_device_id: str | None = None
    auth_method = "none"
    if token:
        try:
            user_id, token_organization_id, token_device_id = decode_access_token(token)
            auth_method = "bearer"
        except ValueError as exc:
            raise HTTPException(
                status_code=401,
                detail=str(exc),
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
    elif settings.legacy_header_auth and x_user_id:
        try:
            user_id = int(x_user_id)
            auth_method = "legacy_header"
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid X-User-Id header") from exc
    else:
        raise HTTPException(
            status_code=401,
            detail="Bearer authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found")
    if token_organization_id is not None and token_organization_id != user.organization_id:
        raise HTTPException(status_code=401, detail="Token organization is invalid")
    organization = db.get(Organization, user.organization_id)
    if not organization or (not organization.is_active and not user.is_platform_admin):
        raise HTTPException(status_code=403, detail="Organization is inactive")
    db.info["organization_id"] = user.organization_id
    device = None
    device_verified = False
    if token_device_id:
        device = db.scalar(select(UserDevice).where(
            UserDevice.organization_id == user.organization_id,
            UserDevice.user_id == user.id,
            UserDevice.device_id == token_device_id,
            UserDevice.is_active.is_(True),
            UserDevice.revoked_at.is_(None),
        ))
        if device and x_device_token:
            device_verified = secrets.compare_digest(device.device_token_hash, sha256(x_device_token.encode("utf-8")).hexdigest())
        if not device_verified:
            raise HTTPException(status_code=401, detail="Registered device authentication failed")
    return Actor(
        user_id=user.id,
        role=user.role,
        organization_id=user.organization_id,
        is_platform_admin=user.is_platform_admin,
        auth_method=auth_method,
        device_id=token_device_id,
        device_record_id=device.id if device else None,
        device_verified=device_verified,
        claim_version=x_claim_version,
    )


def require_roles(actor: Actor, *roles: UserRole) -> None:
    if actor.role == UserRole.ADMIN:
        return
    if actor.role not in roles:
        raise HTTPException(status_code=403, detail="Insufficient permissions")


def require_platform_admin(actor: Actor) -> None:
    if not actor.is_platform_admin:
        raise HTTPException(status_code=403, detail="Platform administrator access required")


def require_work_order_scope(db: Session, actor: Actor, work_order_id: int) -> None:
    work_order = db.get(WorkOrder, work_order_id)
    if not work_order:
        raise HTTPException(status_code=404, detail="Work order not found")
    if work_order.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="Work order not found")
    if actor.role in {UserRole.ADMIN, UserRole.MANAGER}:
        return
    if actor.role == UserRole.ENGINEER:
        return
    if actor.role == UserRole.WAREHOUSE:
        return
    raise HTTPException(status_code=403, detail="Access denied for this work order")


def require_bound_device(actor: Actor) -> None:
    if (
        actor.auth_method != "bearer"
        or not actor.user_id
        or not actor.device_verified
        or not actor.device_record_id
    ):
        raise HTTPException(status_code=401, detail="Authenticated registered device required")


def require_work_order_write_scope(db: Session, actor: Actor, work_order_id: int) -> WorkOrder:
    require_work_order_scope(db, actor, work_order_id)
    work_order = db.get(WorkOrder, work_order_id)
    if not work_order:
        raise HTTPException(status_code=404, detail="Work order not found")
    if actor.role == UserRole.ADMIN:
        return work_order
    if actor.role == UserRole.MANAGER:
        raise HTTPException(status_code=403, detail="Managers must use approval or claim-management workflows")
    return require_work_order_execution_scope(db, actor, work_order_id)


def require_work_order_execution_scope(db: Session, actor: Actor, work_order_id: int) -> WorkOrder:
    """Authorize field edits by the claim owner or an audited administrator.

    Administrators use their own audited identity. Every engineer request must
    use the same registered device and claim generation that won the work order.
    """
    require_work_order_scope(db, actor, work_order_id)
    work_order = db.scalar(
        select(WorkOrder).where(WorkOrder.id == work_order_id).with_for_update()
    )
    if not work_order:
        raise HTTPException(status_code=404, detail="Work order not found")
    if actor.role == UserRole.ADMIN:
        return work_order
    return _require_engineer_claim_owner(actor, work_order)


def require_work_order_owner_scope(db: Session, actor: Actor, work_order_id: int) -> WorkOrder:
    """Require the actual claiming engineer for completion attribution."""
    require_work_order_scope(db, actor, work_order_id)
    work_order = db.scalar(
        select(WorkOrder).where(WorkOrder.id == work_order_id).with_for_update()
    )
    if not work_order:
        raise HTTPException(status_code=404, detail="Work order not found")
    if actor.auth_method == "test" and actor.role == UserRole.ADMIN:
        return work_order
    return _require_engineer_claim_owner(actor, work_order)


def _require_engineer_claim_owner(actor: Actor, work_order: WorkOrder) -> WorkOrder:
    if actor.role != UserRole.ENGINEER:
        raise HTTPException(status_code=403, detail="Only the claiming engineer can modify this work order")
    require_bound_device(actor)
    if work_order.claimed_by_id != actor.user_id:
        raise HTTPException(status_code=403, detail="Work order is claimed by another engineer")
    if work_order.claimed_device_id != actor.device_record_id:
        raise HTTPException(status_code=403, detail="Work order is bound to another registered device")
    if actor.claim_version is None:
        raise HTTPException(status_code=428, detail="X-Claim-Version is required for work order changes")
    if actor.claim_version != work_order.claim_version:
        raise HTTPException(status_code=409, detail="Work order claim has changed; refresh before continuing")
    return work_order
