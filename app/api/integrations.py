from __future__ import annotations

from datetime import datetime
import json
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rbac import Actor, get_current_actor, require_roles
from app.models import (
    AuditLog,
    ExternalIntegration,
    ExternalSyncLog,
    Organization,
    UserRole,
)
from app.schemas import (
    ExternalIntegrationCreate,
    ExternalIntegrationRead,
    ExternalIntegrationRotate,
    ExternalIntegrationSecretRead,
    ExternalIntegrationUpdate,
    ExternalSyncLogRead,
    ExternalWorkOrderUpsert,
    ExternalWorkOrderUpsertRead,
)
from app.services.integrations import (
    api_key_prefix,
    generate_api_key,
    hash_api_key,
    integration_read,
    sync_log_read,
    upsert_external_work_order,
    validate_field_mapping,
)


router = APIRouter()


def _integration_or_404(db: Session, integration_id: int) -> ExternalIntegration:
    integration = db.get(ExternalIntegration, integration_id)
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    return integration


def _audit_integration(
    db: Session,
    actor: Actor,
    action: str,
    integration: ExternalIntegration,
    metadata: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            organization_id=actor.organization_id,
            user_id=actor.user_id,
            action=action,
            entity_type="external_integration",
            entity_id=integration.id,
            metadata_json=json.dumps(
                {
                    "actor_role": actor.role.value,
                    "provider": integration.provider,
                    **(metadata or {}),
                },
                separators=(",", ":"),
            ),
            timestamp=datetime.utcnow(),
        )
    )


def get_external_integration(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> ExternalIntegration:
    provided_key = x_api_key or ""
    if len(provided_key) > 200:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    prefix = api_key_prefix(provided_key)
    candidate = (
        db.scalar(
            select(ExternalIntegration).where(
                ExternalIntegration.key_prefix == prefix,
            )
        )
        if prefix
        else None
    )
    expected_hash = candidate.api_key_hash if candidate else "0" * 64
    key_matches = secrets.compare_digest(hash_api_key(provided_key), expected_hash)
    if not candidate or not key_matches or not candidate.is_active:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    organization = db.get(Organization, candidate.organization_id)
    if not organization or not organization.is_active:
        raise HTTPException(status_code=403, detail="Organization is inactive")
    db.info["organization_id"] = candidate.organization_id
    return candidate


@router.get(
    "/integrations",
    response_model=list[ExternalIntegrationRead],
)
def list_integrations(
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    rows = db.scalars(
        select(ExternalIntegration).order_by(
            ExternalIntegration.is_active.desc(),
            ExternalIntegration.name,
            ExternalIntegration.id,
        )
    ).all()
    return [integration_read(row) for row in rows]


@router.post(
    "/integrations",
    response_model=ExternalIntegrationSecretRead,
)
def create_integration(
    payload: ExternalIntegrationCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    mapping = validate_field_mapping(payload.field_mapping)
    raw_key, prefix, key_hash = generate_api_key()
    integration = ExternalIntegration(
        organization_id=actor.organization_id,
        name=payload.name.strip(),
        provider=payload.provider,
        key_prefix=prefix,
        api_key_hash=key_hash,
        field_mapping_json=json.dumps(mapping, separators=(",", ":")),
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    db.add(integration)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="An integration with this name already exists",
        ) from exc
    _audit_integration(db, actor, "create_external_integration", integration)
    db.commit()
    db.refresh(integration)
    return ExternalIntegrationSecretRead(
        integration=integration_read(integration),
        api_key=raw_key,
    )


@router.patch(
    "/integrations/{integration_id}",
    response_model=ExternalIntegrationRead,
)
def update_integration(
    integration_id: int,
    payload: ExternalIntegrationUpdate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    integration = _integration_or_404(db, integration_id)
    if integration.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Integration version is stale")
    changed_fields: list[str] = []
    if payload.name is not None:
        integration.name = payload.name.strip()
        changed_fields.append("name")
    if payload.field_mapping is not None:
        integration.field_mapping_json = json.dumps(
            validate_field_mapping(payload.field_mapping),
            separators=(",", ":"),
        )
        changed_fields.append("field_mapping")
    if payload.is_active is not None:
        integration.is_active = payload.is_active
        changed_fields.append("is_active")
    integration.version += 1
    integration.updated_by = actor.user_id
    db.add(integration)
    _audit_integration(
        db,
        actor,
        "update_external_integration",
        integration,
        {
            "changed_fields": sorted(changed_fields),
            "new_version": integration.version,
        },
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="An integration with this name already exists",
        ) from exc
    db.refresh(integration)
    return integration_read(integration)


@router.post(
    "/integrations/{integration_id}/rotate-key",
    response_model=ExternalIntegrationSecretRead,
)
def rotate_integration_key(
    integration_id: int,
    payload: ExternalIntegrationRotate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    integration = _integration_or_404(db, integration_id)
    if integration.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Integration version is stale")
    raw_key, prefix, key_hash = generate_api_key()
    previous_prefix = integration.key_prefix
    integration.key_prefix = prefix
    integration.api_key_hash = key_hash
    integration.version += 1
    integration.updated_by = actor.user_id
    db.add(integration)
    _audit_integration(
        db,
        actor,
        "rotate_external_integration_key",
        integration,
        {
            "previous_key_prefix": previous_prefix,
            "new_key_prefix": prefix,
            "new_version": integration.version,
        },
    )
    db.commit()
    db.refresh(integration)
    return ExternalIntegrationSecretRead(
        integration=integration_read(integration),
        api_key=raw_key,
    )


@router.get(
    "/integrations/{integration_id}/sync-logs",
    response_model=list[ExternalSyncLogRead],
)
def list_integration_sync_logs(
    integration_id: int,
    status: str | None = Query(
        default=None,
        pattern="^(processing|processed|failed)$",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    _integration_or_404(db, integration_id)
    stmt = select(ExternalSyncLog).where(
        ExternalSyncLog.integration_id == integration_id
    )
    if status:
        stmt = stmt.where(ExternalSyncLog.status == status)
    rows = db.scalars(
        stmt.order_by(
            ExternalSyncLog.created_at.desc(),
            ExternalSyncLog.id.desc(),
        ).limit(limit)
    ).all()
    return [sync_log_read(row) for row in rows]


@router.post(
    "/external/v1/work-orders",
    response_model=ExternalWorkOrderUpsertRead,
)
def external_work_order_upsert(
    payload: ExternalWorkOrderUpsert,
    idempotency_key: str = Header(
        min_length=8,
        max_length=160,
        alias="X-Idempotency-Key",
    ),
    db: Session = Depends(get_db),
    integration: ExternalIntegration = Depends(get_external_integration),
):
    cleaned_idempotency_key = idempotency_key.strip()
    if len(cleaned_idempotency_key) < 8:
        raise HTTPException(
            status_code=422,
            detail="X-Idempotency-Key must contain at least 8 non-space characters",
        )
    return upsert_external_work_order(
        db,
        integration,
        payload,
        cleaned_idempotency_key,
    )
