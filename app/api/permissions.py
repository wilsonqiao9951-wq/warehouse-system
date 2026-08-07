from __future__ import annotations

from datetime import datetime
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import (
    ALL_PERMISSION_CODES,
    PERMISSION_BY_CODE,
    PERMISSIONS,
    default_permission_codes,
    effective_permission_codes,
)
from app.core.rbac import Actor, get_current_actor, require_roles
from app.models import AuditLog, User, UserPermissionGrant, UserRole
from app.schemas import (
    PermissionDefinitionRead,
    PermissionOverrideRead,
    PermissionOverrideUpdate,
    UserPermissionMatrixRead,
)


router = APIRouter(tags=["permissions"])


def _definitions() -> list[PermissionDefinitionRead]:
    return [
        PermissionDefinitionRead(
            code=item.code,
            name=item.name,
            description=item.description,
            default_roles=sorted(item.default_roles, key=lambda role: role.value),
            sensitive=item.sensitive,
        )
        for item in PERMISSIONS
    ]


def _target_user(db: Session, actor: Actor, user_id: int) -> User:
    user = db.get(User, user_id)
    if not user or user.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def _grant_rows(db: Session, user_id: int) -> list[UserPermissionGrant]:
    return list(
        db.scalars(
            select(UserPermissionGrant)
            .where(UserPermissionGrant.user_id == user_id)
            .order_by(UserPermissionGrant.permission_code)
        ).all()
    )


def _matrix(db: Session, user: User) -> UserPermissionMatrixRead:
    rows = _grant_rows(db, user.id)
    overrides = {row.permission_code: row.effect == "allow" for row in rows}
    return UserPermissionMatrixRead(
        user_id=user.id,
        role=user.role,
        role_permissions=sorted(default_permission_codes(user.role)),
        effective_permissions=sorted(effective_permission_codes(user.role, overrides)),
        overrides=[
            PermissionOverrideRead(
                permission_code=row.permission_code,
                effect=row.effect,
                reason=row.reason,
                granted_by_id=row.granted_by_id,
                updated_at=row.updated_at,
            )
            for row in rows
            if row.permission_code in ALL_PERMISSION_CODES
        ],
        definitions=_definitions(),
    )


@router.get("/permissions/catalog", response_model=list[PermissionDefinitionRead])
def permission_catalog(
    _actor: Actor = Depends(get_current_actor),
):
    return _definitions()


@router.get("/permissions/me", response_model=UserPermissionMatrixRead)
def my_permissions(
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    if actor.user_id is None:
        return UserPermissionMatrixRead(
            user_id=0,
            role=actor.role,
            role_permissions=sorted(default_permission_codes(actor.role)),
            effective_permissions=sorted(actor.permissions),
            overrides=[],
            definitions=_definitions(),
        )
    return _matrix(db, _target_user(db, actor, actor.user_id))


@router.get(
    "/users/{user_id}/permissions",
    response_model=UserPermissionMatrixRead,
)
def user_permissions(
    user_id: int,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    return _matrix(db, _target_user(db, actor, user_id))


@router.put(
    "/users/{user_id}/permissions/{permission_code}",
    response_model=UserPermissionMatrixRead,
)
def set_user_permission(
    user_id: int,
    permission_code: str,
    payload: PermissionOverrideUpdate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    target = _target_user(db, actor, user_id)
    definition = PERMISSION_BY_CODE.get(permission_code)
    if not definition:
        raise HTTPException(status_code=404, detail="Permission not found")
    if target.role == UserRole.ADMIN:
        raise HTTPException(
            status_code=409,
            detail="Administrator permissions are role-controlled and cannot be overridden",
        )
    row = db.scalar(
        select(UserPermissionGrant).where(
            UserPermissionGrant.user_id == target.id,
            UserPermissionGrant.permission_code == permission_code,
        )
    )
    previous_effect = row.effect if row else "inherit"
    now = datetime.utcnow()
    if payload.effect == "inherit":
        if row:
            db.delete(row)
    elif row:
        row.effect = payload.effect
        row.reason = payload.reason.strip()
        row.granted_by_id = actor.user_id
        row.updated_at = now
        db.add(row)
    else:
        db.add(
            UserPermissionGrant(
                organization_id=actor.organization_id,
                user_id=target.id,
                permission_code=permission_code,
                effect=payload.effect,
                reason=payload.reason.strip(),
                granted_by_id=actor.user_id,
                created_at=now,
                updated_at=now,
            )
        )
    db.add(
        AuditLog(
            organization_id=actor.organization_id,
            user_id=actor.user_id,
            action="change_user_permission",
            entity_type="user_permission",
            entity_id=target.id,
            metadata_json=json.dumps(
                {
                    "permission_code": permission_code,
                    "permission_name": definition.name,
                    "previous_effect": previous_effect,
                    "new_effect": payload.effect,
                    "reason": payload.reason.strip(),
                    "target_user_id": target.id,
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
    )
    db.commit()
    return _matrix(db, target)
