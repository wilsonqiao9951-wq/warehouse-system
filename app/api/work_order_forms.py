from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rbac import (
    Actor,
    get_current_actor,
    require_bound_device,
    require_roles,
    require_work_order_scope,
    require_work_order_write_scope,
)
from app.models import (
    AuditLog,
    User,
    UserDevice,
    UserRole,
    WorkOrder,
    WorkOrderFormAction,
    WorkOrderFormConflict,
    WorkOrderFormTemplate,
)
from app.schemas import (
    WorkOrderFormActionRead,
    WorkOrderFormActionUpdate,
    WorkOrderFormConflictCreate,
    WorkOrderFormConflictRead,
    WorkOrderFormConflictReceipt,
    WorkOrderFormConflictResolve,
    WorkOrderFormRead,
    WorkOrderFormTemplateCreate,
    WorkOrderFormTemplateRead,
    WorkOrderFormTemplateUpdate,
    WorkOrderFormUpdate,
)
from app.services.work_order_forms import (
    create_form_action_tasks,
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


def _task_capabilities(
    actor: Actor,
    task: WorkOrderFormAction,
) -> tuple[bool, bool]:
    if task.status == "resolved":
        return False, False
    allowed = bool(
        actor.role == UserRole.ADMIN
        or (
            task.action_type == "notification"
            and actor.role == UserRole.MANAGER
        )
        or (
            task.action_type == "inventory_review"
            and actor.role == UserRole.WAREHOUSE
        )
    )
    return allowed and task.status == "pending", allowed


def _user_name(db: Session, user_id: int | None) -> str | None:
    if not user_id:
        return None
    user = db.get(User, user_id)
    return user.name if user else None


def _form_action_read(
    db: Session,
    actor: Actor,
    task: WorkOrderFormAction,
) -> WorkOrderFormActionRead:
    work_order = db.get(WorkOrder, task.work_order_id)
    template = (
        db.get(WorkOrderFormTemplate, task.template_id)
        if task.template_id
        else None
    )
    can_acknowledge, can_resolve = _task_capabilities(actor, task)
    return WorkOrderFormActionRead(
        id=task.id,
        organization_id=task.organization_id,
        work_order_id=task.work_order_id,
        work_order_ticket_number=(
            work_order.ticket_number if work_order else f"#{task.work_order_id}"
        ),
        template_id=task.template_id,
        template_name=template.name if template else None,
        field_key=task.field_key,
        field_label=task.field_label,
        action_type=task.action_type,
        status=task.status,
        triggered_form_version=task.triggered_form_version,
        version=task.version,
        created_by=task.created_by,
        created_by_name=_user_name(db, task.created_by),
        acknowledged_by=task.acknowledged_by,
        acknowledged_by_name=_user_name(db, task.acknowledged_by),
        acknowledged_at=task.acknowledged_at,
        resolved_by=task.resolved_by,
        resolved_by_name=_user_name(db, task.resolved_by),
        resolved_at=task.resolved_at,
        resolution_notes=task.resolution_notes,
        can_acknowledge=can_acknowledge,
        can_resolve=can_resolve,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _stored_values(raw: str | None) -> dict:
    try:
        values = json.loads(raw or "{}")
        return values if isinstance(values, dict) else {}
    except (TypeError, ValueError):
        return {}


def _form_conflict_read(
    db: Session,
    conflict: WorkOrderFormConflict,
) -> WorkOrderFormConflictRead:
    work_order = db.get(WorkOrder, conflict.work_order_id)
    if not work_order:
        raise HTTPException(status_code=404, detail="Work order not found")
    device = db.get(UserDevice, conflict.created_device_id)
    return WorkOrderFormConflictRead(
        id=conflict.id,
        organization_id=conflict.organization_id,
        work_order_id=conflict.work_order_id,
        work_order_ticket_number=work_order.ticket_number,
        client_queue_id=conflict.client_queue_id,
        created_by=conflict.created_by,
        created_by_name=_user_name(db, conflict.created_by),
        created_device_id=conflict.created_device_id,
        created_device_name=device.device_name if device else None,
        claim_version=conflict.claim_version,
        base_form_version=conflict.base_form_version,
        server_form_version=conflict.server_form_version,
        current_server_form_version=work_order.form_version,
        local_values=_stored_values(conflict.local_values_json),
        server_values=_stored_values(conflict.server_values_json),
        current_server_values=work_order_form_values(work_order),
        status=conflict.status,
        version=conflict.version,
        resolved_values=(
            _stored_values(conflict.resolved_values_json)
            if conflict.resolved_values_json is not None
            else None
        ),
        resolved_server_form_version=conflict.resolved_server_form_version,
        resolution_notes=conflict.resolution_notes,
        resolved_by=conflict.resolved_by,
        resolved_by_name=_user_name(db, conflict.resolved_by),
        resolved_at=conflict.resolved_at,
        created_at=conflict.created_at,
        updated_at=conflict.updated_at,
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
        and actor.auth_method in {"bearer", "cookie"}
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
    if not changed_fields:
        return work_order_form_read(db, work_order, can_edit=True)
    work_order.form_data_json = json.dumps(
        merged,
        separators=(",", ":"),
        default=str,
    )
    work_order.form_version += 1
    db.add(work_order)
    action_tasks = create_form_action_tasks(
        db,
        work_order,
        changed_fields=changed_fields,
        fields=fields,
        created_by=actor.user_id,
    )
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
            "action_task_ids": [task.id for task in action_tasks],
        },
    )
    if action_tasks:
        _audit(
            db,
            actor,
            "work_order_form_actions_created",
            "work_order",
            work_order.id,
            {
                "tasks": [
                    {
                        "id": task.id,
                        "field_key": task.field_key,
                        "action_type": task.action_type,
                    }
                    for task in action_tasks
                ]
            },
        )
    db.commit()
    db.refresh(work_order)
    return work_order_form_read(db, work_order, can_edit=True)


@router.post(
    "/work-order-form-conflicts",
    response_model=WorkOrderFormConflictReceipt,
)
def create_work_order_form_conflict(
    payload: WorkOrderFormConflictCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    if actor.role != UserRole.ENGINEER:
        raise HTTPException(
            status_code=403,
            detail="Only the claiming engineer can register an offline form conflict",
        )
    require_bound_device(actor)
    require_work_order_scope(db, actor, payload.work_order_id)
    canonical_local = json.dumps(
        payload.local_values,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    payload_hash = sha256(canonical_local.encode("utf-8")).hexdigest()
    existing = db.scalar(
        select(WorkOrderFormConflict).where(
            WorkOrderFormConflict.client_queue_id == payload.client_queue_id
        )
    )
    if existing:
        if (
            existing.work_order_id != payload.work_order_id
            or existing.created_by != actor.user_id
            or existing.created_device_id != actor.device_record_id
            or existing.claim_version != payload.claim_version
            or existing.base_form_version != payload.base_form_version
            or existing.local_payload_hash != payload_hash
        ):
            raise HTTPException(
                status_code=409,
                detail="Offline queue id was already used for different conflict data",
            )
        return WorkOrderFormConflictReceipt(
            id=existing.id,
            status=existing.status,
            version=existing.version,
        )

    work_order = require_work_order_write_scope(db, actor, payload.work_order_id)
    if payload.claim_version != work_order.claim_version:
        raise HTTPException(
            status_code=409,
            detail="Work order claim changed before conflict registration",
        )
    if payload.base_form_version == work_order.form_version:
        raise HTTPException(
            status_code=409,
            detail="Server form is not in conflict with the offline base version",
        )
    # Validate every local value against the immutable work-order form snapshot
    # before any sensitive evidence is retained for administrator review.
    merge_work_order_form_values(work_order, payload.local_values)
    conflict = WorkOrderFormConflict(
        organization_id=actor.organization_id,
        work_order_id=work_order.id,
        client_queue_id=payload.client_queue_id,
        created_by=actor.user_id,
        created_device_id=actor.device_record_id,
        claim_version=payload.claim_version,
        base_form_version=payload.base_form_version,
        server_form_version=work_order.form_version,
        local_values_json=canonical_local,
        server_values_json=json.dumps(
            work_order_form_values(work_order),
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ),
        local_payload_hash=payload_hash,
    )
    db.add(conflict)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Offline conflict could not be registered safely",
        ) from exc
    _audit(
        db,
        actor,
        "create_work_order_form_conflict",
        "work_order_form_conflict",
        conflict.id,
        {
            "work_order_id": work_order.id,
            "claim_version": payload.claim_version,
            "base_form_version": payload.base_form_version,
            "server_form_version": work_order.form_version,
            "local_field_keys": sorted(payload.local_values),
            "local_payload_hash": payload_hash,
        },
    )
    db.commit()
    db.refresh(conflict)
    return WorkOrderFormConflictReceipt(
        id=conflict.id,
        status=conflict.status,
        version=conflict.version,
    )


@router.get(
    "/work-order-form-conflicts",
    response_model=list[WorkOrderFormConflictRead],
)
def list_work_order_form_conflicts(
    status: str | None = Query(
        default=None,
        pattern="^(pending|kept_server|applied_local|merged)$",
    ),
    work_order_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    stmt = select(WorkOrderFormConflict)
    if status:
        stmt = stmt.where(WorkOrderFormConflict.status == status)
    if work_order_id:
        stmt = stmt.where(WorkOrderFormConflict.work_order_id == work_order_id)
    conflicts = db.scalars(
        stmt.order_by(WorkOrderFormConflict.id.desc()).limit(limit)
    ).all()
    return [_form_conflict_read(db, conflict) for conflict in conflicts]


@router.get(
    "/work-order-form-conflicts/{conflict_id}/status",
    response_model=WorkOrderFormConflictReceipt,
)
def get_work_order_form_conflict_status(
    conflict_id: int,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    conflict = db.get(WorkOrderFormConflict, conflict_id)
    if not conflict:
        raise HTTPException(status_code=404, detail="Work-order form conflict not found")
    if actor.role != UserRole.ADMIN:
        if actor.role != UserRole.ENGINEER:
            raise HTTPException(status_code=403, detail="Conflict status access denied")
        require_bound_device(actor)
        if (
            conflict.created_by != actor.user_id
            or conflict.created_device_id != actor.device_record_id
        ):
            raise HTTPException(status_code=403, detail="Conflict status access denied")
    return WorkOrderFormConflictReceipt(
        id=conflict.id,
        status=conflict.status,
        version=conflict.version,
    )


@router.patch(
    "/work-order-form-conflicts/{conflict_id}",
    response_model=WorkOrderFormConflictRead,
)
def resolve_work_order_form_conflict(
    conflict_id: int,
    payload: WorkOrderFormConflictResolve,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    conflict = db.scalar(
        select(WorkOrderFormConflict)
        .where(WorkOrderFormConflict.id == conflict_id)
        .with_for_update()
    )
    if not conflict:
        raise HTTPException(status_code=404, detail="Work-order form conflict not found")
    if conflict.status != "pending":
        raise HTTPException(status_code=409, detail="Work-order form conflict is already resolved")
    if conflict.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Conflict version is stale")
    work_order = db.scalar(
        select(WorkOrder)
        .where(WorkOrder.id == conflict.work_order_id)
        .with_for_update()
    )
    if not work_order:
        raise HTTPException(status_code=404, detail="Work order not found")
    if work_order.form_version != payload.expected_server_form_version:
        raise HTTPException(
            status_code=409,
            detail="Server form changed again; refresh conflict before resolving",
        )

    resolution_values: dict | None = None
    action_tasks: list[WorkOrderFormAction] = []
    changed_fields: list[str] = []
    if payload.action != "keep_server":
        if work_order.is_locked or work_order.status == "PENDING_APPROVAL":
            raise HTTPException(
                status_code=409,
                detail="Work-order form is frozen; only keeping the server version is allowed",
            )
        if payload.action == "apply_local":
            resolution_values = _stored_values(conflict.local_values_json)
        else:
            if payload.values is None:
                raise HTTPException(
                    status_code=422,
                    detail="Merged resolution values are required",
                )
            resolution_values = payload.values
        previous_values = work_order_form_values(work_order)
        merged = merge_work_order_form_values(work_order, resolution_values)
        changed_fields = sorted(
            key
            for key, value in resolution_values.items()
            if value != previous_values.get(key)
        )
        if changed_fields:
            work_order.form_data_json = json.dumps(
                merged,
                separators=(",", ":"),
                default=str,
            )
            work_order.form_version += 1
            fields = {
                field.field_key: field
                for field in work_order_form_fields(work_order)
            }
            action_tasks = create_form_action_tasks(
                db,
                work_order,
                changed_fields=changed_fields,
                fields=fields,
                created_by=actor.user_id,
            )
            db.add(work_order)

    conflict.status = {
        "keep_server": "kept_server",
        "apply_local": "applied_local",
        "merge": "merged",
    }[payload.action]
    conflict.version += 1
    conflict.resolved_values_json = (
        json.dumps(
            resolution_values,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        if resolution_values is not None
        else None
    )
    conflict.resolved_server_form_version = work_order.form_version
    conflict.resolution_notes = payload.resolution_notes
    conflict.resolved_by = actor.user_id
    conflict.resolved_at = datetime.utcnow()
    db.add(conflict)
    _audit(
        db,
        actor,
        "resolve_work_order_form_conflict",
        "work_order_form_conflict",
        conflict.id,
        {
            "work_order_id": work_order.id,
            "resolution": payload.action,
            "changed_fields": changed_fields,
            "resulting_form_version": work_order.form_version,
            "action_task_ids": [task.id for task in action_tasks],
        },
    )
    if action_tasks:
        _audit(
            db,
            actor,
            "work_order_form_actions_created_from_conflict_resolution",
            "work_order",
            work_order.id,
            {
                "conflict_id": conflict.id,
                "tasks": [
                    {
                        "id": task.id,
                        "field_key": task.field_key,
                        "action_type": task.action_type,
                    }
                    for task in action_tasks
                ],
            },
        )
    db.commit()
    db.refresh(conflict)
    return _form_conflict_read(db, conflict)


@router.get(
    "/work-order-form-actions",
    response_model=list[WorkOrderFormActionRead],
)
def list_form_action_tasks(
    status: str | None = Query(
        default=None,
        pattern="^(pending|acknowledged|resolved)$",
    ),
    action_type: str | None = Query(
        default=None,
        pattern="^(notification|inventory_review)$",
    ),
    work_order_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    stmt = select(WorkOrderFormAction)
    if actor.role == UserRole.WAREHOUSE:
        stmt = stmt.where(
            WorkOrderFormAction.action_type == "inventory_review"
        )
    if status:
        stmt = stmt.where(WorkOrderFormAction.status == status)
    if action_type:
        stmt = stmt.where(WorkOrderFormAction.action_type == action_type)
    if work_order_id:
        stmt = stmt.where(WorkOrderFormAction.work_order_id == work_order_id)
    tasks = db.scalars(
        stmt.order_by(WorkOrderFormAction.id.desc()).limit(limit)
    ).all()
    return [_form_action_read(db, actor, task) for task in tasks]


@router.get(
    "/work-orders/{work_order_id}/form-actions",
    response_model=list[WorkOrderFormActionRead],
)
def list_work_order_form_action_tasks(
    work_order_id: int,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_work_order_scope(db, actor, work_order_id)
    tasks = db.scalars(
        select(WorkOrderFormAction)
        .where(WorkOrderFormAction.work_order_id == work_order_id)
        .order_by(WorkOrderFormAction.id.desc())
    ).all()
    return [_form_action_read(db, actor, task) for task in tasks]


@router.patch(
    "/work-order-form-actions/{task_id}",
    response_model=WorkOrderFormActionRead,
)
def update_form_action_task(
    task_id: int,
    payload: WorkOrderFormActionUpdate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    task = db.scalar(
        select(WorkOrderFormAction)
        .where(WorkOrderFormAction.id == task_id)
        .with_for_update()
    )
    if not task:
        raise HTTPException(status_code=404, detail="Form action task not found")
    if task.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Form action task version is stale")
    can_acknowledge, can_resolve = _task_capabilities(actor, task)
    if payload.action == "acknowledge":
        if not can_acknowledge:
            raise HTTPException(
                status_code=403,
                detail="Role cannot acknowledge this form action task",
            )
        task.status = "acknowledged"
        task.acknowledged_by = actor.user_id
        task.acknowledged_at = datetime.utcnow()
    else:
        if not can_resolve:
            raise HTTPException(
                status_code=403,
                detail="Role cannot resolve this form action task",
            )
        if (
            task.action_type == "inventory_review"
            and len(payload.resolution_notes or "") < 3
        ):
            raise HTTPException(
                status_code=422,
                detail="Inventory review resolution requires notes",
            )
        task.status = "resolved"
        task.resolved_by = actor.user_id
        task.resolved_at = datetime.utcnow()
        task.resolution_notes = payload.resolution_notes
    task.version += 1
    db.add(task)
    _audit(
        db,
        actor,
        f"{payload.action}_work_order_form_action",
        "work_order_form_action",
        task.id,
        {
            "action_type": task.action_type,
            "field_key": task.field_key,
            "work_order_id": task.work_order_id,
            "new_status": task.status,
            "new_version": task.version,
        },
    )
    db.commit()
    db.refresh(task)
    return _form_action_read(db, actor, task)
