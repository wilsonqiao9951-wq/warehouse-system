from __future__ import annotations

from datetime import datetime
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rbac import (
    Actor,
    get_current_actor,
    require_roles,
    require_work_order_scope,
    require_work_order_write_scope,
)
from app.models import (
    AuditLog,
    UserRole,
    WorkOrder,
    WorkOrderFormTemplate,
)
from app.schemas import (
    WorkOrderFormRead,
    WorkOrderFormTemplateCreate,
    WorkOrderFormTemplateRead,
    WorkOrderFormTemplateUpdate,
    WorkOrderFormUpdate,
)
from app.services.work_order_forms import (
    merge_work_order_form_values,
    replace_template_fields,
    template_read,
    work_order_form_fields,
    work_order_form_read,
    work_order_form_values,
)


router = APIRouter()


def _template_or_404(
    db: Session,
    template_id: int,
) -> WorkOrderFormTemplate:
    template = db.get(WorkOrderFormTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Work-order form template not found")
    return template


def _audit(
    db: Session,
    actor: Actor,
    action: str,
    entity_type: str,
    entity_id: int | None,
    metadata: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            organization_id=actor.organization_id,
            user_id=actor.user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            metadata_json=json.dumps(
                {"actor_role": actor.role.value, **(metadata or {})},
                separators=(",", ":"),
                default=str,
            ),
            timestamp=datetime.utcnow(),
        )
    )


@router.get(
    "/work-order-form-templates",
    response_model=list[WorkOrderFormTemplateRead],
)
def list_work_order_form_templates(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    stmt = select(WorkOrderFormTemplate)
    if not include_inactive:
        stmt = stmt.where(WorkOrderFormTemplate.is_active.is_(True))
    templates = db.scalars(
        stmt.order_by(
            WorkOrderFormTemplate.is_active.desc(),
            WorkOrderFormTemplate.name,
            WorkOrderFormTemplate.id,
        )
    ).all()
    return [
        template_read(template, can_edit=actor.role == UserRole.ADMIN)
        for template in templates
    ]


@router.get(
    "/work-order-form-templates/{template_id}",
    response_model=WorkOrderFormTemplateRead,
)
def get_work_order_form_template(
    template_id: int,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    return template_read(
        _template_or_404(db, template_id),
        can_edit=actor.role == UserRole.ADMIN,
    )


@router.post(
    "/work-order-form-templates",
    response_model=WorkOrderFormTemplateRead,
)
def create_work_order_form_template(
    payload: WorkOrderFormTemplateCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    template = WorkOrderFormTemplate(
        organization_id=actor.organization_id,
        name=payload.name.strip(),
        industry=(payload.industry or "").strip() or None,
        description=(payload.description or "").strip() or None,
        applicable_machine_type=(payload.applicable_machine_type or "").strip() or None,
        applicable_job_type=(payload.applicable_job_type or "").strip() or None,
        default_work_order_status=payload.default_work_order_status,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    replace_template_fields(template, payload.fields)
    db.add(template)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A work-order form template with this name already exists",
        ) from exc
    _audit(
        db,
        actor,
        "create_work_order_form_template",
        "work_order_form_template",
        template.id,
        {"field_keys": [field.field_key for field in payload.fields]},
    )
    db.commit()
    db.refresh(template)
    return template_read(template, can_edit=True)


@router.patch(
    "/work-order-form-templates/{template_id}",
    response_model=WorkOrderFormTemplateRead,
)
def update_work_order_form_template(
    template_id: int,
    payload: WorkOrderFormTemplateUpdate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    template = _template_or_404(db, template_id)
    if template.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Template version is stale")
    changed_fields: list[str] = []
    for field in (
        "name",
        "industry",
        "description",
        "applicable_machine_type",
        "applicable_job_type",
        "default_work_order_status",
        "is_active",
    ):
        if field not in payload.model_fields_set:
            continue
        value = getattr(payload, field)
        if field in {"name", "default_work_order_status"} and value is None:
            raise HTTPException(status_code=422, detail=f"{field} cannot be null")
        if isinstance(value, str):
            value = value.strip() or None
        setattr(template, field, value)
        changed_fields.append(field)
    if payload.fields is not None:
        try:
            replace_template_fields(template, payload.fields, db=db)
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="Template name or field key conflicts with an existing definition",
            ) from exc
        changed_fields.append("fields")
    template.version += 1
    template.updated_by = actor.user_id
    db.add(template)
    _audit(
        db,
        actor,
        "update_work_order_form_template",
        "work_order_form_template",
        template.id,
        {
            "changed_fields": sorted(changed_fields),
            "new_version": template.version,
        },
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A work-order form template with this name already exists",
        ) from exc
    db.refresh(template)
    return template_read(template, can_edit=True)


def _can_edit_form(actor: Actor, work_order: WorkOrder) -> bool:
    if work_order.is_locked or work_order.status == "PENDING_APPROVAL":
        return False
    if actor.role == UserRole.ADMIN:
        return True
    return bool(
        actor.role == UserRole.ENGINEER
        and actor.auth_method == "bearer"
        and actor.device_verified
        and work_order.claimed_by_id == actor.user_id
        and work_order.claimed_device_id == actor.device_record_id
    )


@router.get(
    "/work-orders/{work_order_id}/form",
    response_model=WorkOrderFormRead,
)
def get_work_order_form(
    work_order_id: int,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_work_order_scope(db, actor, work_order_id)
    work_order = db.get(WorkOrder, work_order_id)
    if not work_order:
        raise HTTPException(status_code=404, detail="Work order not found")
    can_edit = _can_edit_form(actor, work_order)
    return work_order_form_read(
        db,
        work_order,
        can_edit=can_edit,
        include_sensitive_values=bool(
            can_edit
            or actor.role in {UserRole.ADMIN, UserRole.MANAGER}
            or actor.auth_method == "test"
        ),
    )


@router.patch(
    "/work-orders/{work_order_id}/form",
    response_model=WorkOrderFormRead,
)
def update_work_order_form(
    work_order_id: int,
    payload: WorkOrderFormUpdate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    work_order = require_work_order_write_scope(db, actor, work_order_id)
    if work_order.is_locked or work_order.status == "PENDING_APPROVAL":
        raise HTTPException(status_code=409, detail="Work-order form is frozen")
    if work_order.form_version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Work-order form version is stale")
    previous_values = work_order_form_values(work_order)
    merged = merge_work_order_form_values(work_order, payload.values)
    fields = {field.field_key: field for field in work_order_form_fields(work_order)}
    changed_fields = sorted(
        key
        for key, value in payload.values.items()
        if value != previous_values.get(key)
    )
    work_order.form_data_json = json.dumps(
        merged,
        separators=(",", ":"),
        default=str,
    )
    work_order.form_version += 1
    db.add(work_order)
    _audit(
        db,
        actor,
        "update_work_order_form",
        "work_order",
        work_order.id,
        {
            "changed_fields": changed_fields,
            "form_version": work_order.form_version,
            "ai_learning_fields": [
                key
                for key in changed_fields
                if fields[key].include_in_ai_learning
            ],
            "inventory_declared_fields": [
                key for key in changed_fields if fields[key].affects_inventory
            ],
        },
    )
    notification_fields = [
        key for key in changed_fields if fields[key].triggers_notification
    ]
    if notification_fields:
        _audit(
            db,
            actor,
            "work_order_form_notification_triggered",
            "work_order",
            work_order.id,
            {"field_keys": notification_fields},
        )
    db.commit()
    db.refresh(work_order)
    return work_order_form_read(db, work_order, can_edit=True)
