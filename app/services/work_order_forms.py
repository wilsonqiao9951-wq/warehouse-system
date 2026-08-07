from __future__ import annotations

import base64
import binascii
from datetime import date
import json
import math
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    WorkOrder,
    WorkOrderFormAction,
    WorkOrderFormField,
    WorkOrderFormTemplate,
)
from app.schemas import (
    WorkOrderFormFieldCreate,
    WorkOrderFormFieldRead,
    WorkOrderFormRead,
    WorkOrderFormTemplateRead,
)


def _json_value(raw: str | None) -> Any:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _json_list(raw: str | None) -> list:
    value = _json_value(raw)
    return value if isinstance(value, list) else []


def form_field_read(field: WorkOrderFormField) -> WorkOrderFormFieldRead:
    return WorkOrderFormFieldRead(
        id=field.id,
        field_key=field.field_key,
        label=field.label,
        field_type=field.field_type,
        help_text=field.help_text,
        placeholder=field.placeholder,
        default_value=_json_value(field.default_value_json),
        options=_json_list(field.options_json),
        required_at_completion=field.required_at_completion,
        requires_photo=field.requires_photo,
        requires_signature=field.requires_signature,
        requires_approval=field.requires_approval,
        triggers_notification=field.triggers_notification,
        affects_inventory=field.affects_inventory,
        include_in_ai_learning=field.include_in_ai_learning,
        sort_order=field.sort_order,
    )


def template_read(
    template: WorkOrderFormTemplate,
    *,
    can_edit: bool,
) -> WorkOrderFormTemplateRead:
    return WorkOrderFormTemplateRead(
        id=template.id,
        organization_id=template.organization_id,
        name=template.name,
        industry=template.industry,
        description=template.description,
        applicable_machine_type=template.applicable_machine_type,
        applicable_job_type=template.applicable_job_type,
        default_work_order_status=template.default_work_order_status,
        is_active=template.is_active,
        version=template.version,
        fields=[form_field_read(field) for field in template.fields],
        created_by=template.created_by,
        updated_by=template.updated_by,
        can_edit=can_edit,
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


def replace_template_fields(
    template: WorkOrderFormTemplate,
    fields: list[WorkOrderFormFieldCreate],
    *,
    db: Session | None = None,
) -> None:
    template.fields.clear()
    if db is not None and template.id is not None:
        # Flush orphan deletes before inserting replacement rows that may reuse
        # the same (template_id, field_key) unique key.
        db.flush()
    for index, field in enumerate(fields):
        data = field.model_dump()
        default_value = data.pop("default_value")
        options = data.pop("options")
        validated_default = (
            _validated_value(
                WorkOrderFormFieldRead(
                    id=None,
                    default_value=default_value,
                    options=options,
                    **{key: value for key, value in data.items() if key != "sort_order"},
                    sort_order=field.sort_order,
                ),
                default_value,
            )
            if default_value is not None
            else None
        )
        template.fields.append(
            WorkOrderFormField(
                organization_id=template.organization_id,
                default_value_json=(
                    json.dumps(validated_default, separators=(",", ":"))
                    if validated_default is not None
                    else None
                ),
                options_json=json.dumps(options, separators=(",", ":")),
                sort_order=field.sort_order if "sort_order" in field.model_fields_set else index,
                **{key: value for key, value in data.items() if key != "sort_order"},
            )
        )


def _matches(expected: str | None, actual: str | None) -> bool:
    if not expected:
        return True
    return (expected.strip().casefold() == (actual or "").strip().casefold())


def template_for_assignment(
    db: Session,
    *,
    template_id: int,
    machine_type: str | None,
    job_type: str | None,
) -> WorkOrderFormTemplate:
    template = db.scalar(
        select(WorkOrderFormTemplate).where(
            WorkOrderFormTemplate.id == template_id,
            WorkOrderFormTemplate.is_active.is_(True),
        )
    )
    if not template:
        raise HTTPException(status_code=400, detail="Active work-order form template not found")
    if not _matches(template.applicable_machine_type, machine_type):
        raise HTTPException(
            status_code=409,
            detail="Work-order form template does not apply to this machine type",
        )
    if not _matches(template.applicable_job_type, job_type):
        raise HTTPException(
            status_code=409,
            detail="Work-order form template does not apply to this job type",
        )
    return template


def snapshot_template(template: WorkOrderFormTemplate) -> tuple[str, str]:
    fields = [
        form_field_read(field).model_dump(mode="json")
        for field in template.fields
    ]
    defaults = {
        field["field_key"]: field["default_value"]
        for field in fields
        if field.get("default_value") is not None
    }
    return (
        json.dumps(fields, separators=(",", ":"), default=str),
        json.dumps(defaults, separators=(",", ":"), default=str),
    )


def work_order_form_fields(work_order: WorkOrder) -> list[WorkOrderFormFieldRead]:
    if not work_order.form_schema_json:
        return []
    try:
        raw = json.loads(work_order.form_schema_json)
    except json.JSONDecodeError:
        raw = []
    if not isinstance(raw, list):
        return []
    fields: list[WorkOrderFormFieldRead] = []
    for value in raw:
        try:
            fields.append(WorkOrderFormFieldRead.model_validate(value))
        except Exception:
            continue
    return sorted(fields, key=lambda field: (field.sort_order, field.field_key))


def work_order_form_values(work_order: WorkOrder) -> dict[str, Any]:
    try:
        raw = json.loads(work_order.form_data_json or "{}")
    except json.JSONDecodeError:
        raw = {}
    return raw if isinstance(raw, dict) else {}


def _missing(value: Any, *, present: bool) -> bool:
    if not present or value is None:
        return True
    return isinstance(value, str) and not value.strip()


def missing_required_fields(
    fields: list[WorkOrderFormFieldRead],
    values: dict[str, Any],
) -> list[str]:
    return [
        field.field_key
        for field in fields
        if (
            field.required_at_completion
            or field.requires_photo
            or field.requires_signature
        )
        and _missing(values.get(field.field_key), present=field.field_key in values)
    ]


def _validated_value(
    field: WorkOrderFormFieldRead,
    value: Any,
) -> Any:
    if value is None:
        return None
    if field.field_type == "signature":
        if not isinstance(value, str):
            raise HTTPException(
                status_code=422,
                detail=f"{field.field_key} must be a PNG signature",
            )
        cleaned = value.strip()
        if not cleaned:
            return ""
        if not cleaned.startswith("data:image/png;base64,") or len(cleaned) > 250_000:
            raise HTTPException(
                status_code=422,
                detail=f"{field.field_key} must be a PNG signature under 250 KiB",
            )
        try:
            decoded = base64.b64decode(cleaned.split(",", 1)[1], validate=True)
        except (ValueError, binascii.Error) as exc:
            raise HTTPException(
                status_code=422,
                detail=f"{field.field_key} contains invalid signature data",
            ) from exc
        if not decoded.startswith(b"\x89PNG\r\n\x1a\n"):
            raise HTTPException(
                status_code=422,
                detail=f"{field.field_key} is not a PNG signature",
            )
        return cleaned
    if field.field_type == "photo":
        if not isinstance(value, str):
            raise HTTPException(
                status_code=422,
                detail=f"{field.field_key} must be a photo URL",
            )
        cleaned = value.strip()
        if not cleaned:
            return ""
        parsed = urlparse(cleaned)
        is_upload = cleaned.startswith("/uploads/")
        is_web_url = parsed.scheme in {"http", "https"} and bool(parsed.netloc)
        if len(cleaned) > 1_000 or not (is_upload or is_web_url):
            raise HTTPException(
                status_code=422,
                detail=f"{field.field_key} must be an uploaded or HTTP(S) photo URL",
            )
        return cleaned
    if field.field_type in {
        "text",
        "textarea",
        "select",
    }:
        if not isinstance(value, str):
            raise HTTPException(
                status_code=422,
                detail=f"{field.field_key} must be text",
            )
        cleaned = value.strip()
        maximum = 20_000 if field.field_type == "textarea" else 1_000
        if len(cleaned) > maximum:
            raise HTTPException(
                status_code=422,
                detail=f"{field.field_key} exceeds {maximum} characters",
            )
        if field.field_type == "select" and cleaned and cleaned not in field.options:
            raise HTTPException(
                status_code=422,
                detail=f"{field.field_key} is not an allowed option",
            )
        return cleaned
    if field.field_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise HTTPException(
                status_code=422,
                detail=f"{field.field_key} must be a number",
            )
        numeric = float(value)
        if not math.isfinite(numeric) or abs(numeric) > 1_000_000_000_000:
            raise HTTPException(
                status_code=422,
                detail=f"{field.field_key} is outside the allowed numeric range",
            )
        return value
    if field.field_type == "boolean":
        if not isinstance(value, bool):
            raise HTTPException(
                status_code=422,
                detail=f"{field.field_key} must be true or false",
            )
        return value
    if field.field_type == "date":
        if not isinstance(value, str):
            raise HTTPException(
                status_code=422,
                detail=f"{field.field_key} must be an ISO date",
            )
        if not value.strip():
            return ""
        try:
            return date.fromisoformat(value.strip()).isoformat()
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"{field.field_key} must be an ISO date",
            ) from exc
    raise HTTPException(status_code=422, detail=f"Unsupported field {field.field_key}")


def merge_work_order_form_values(
    work_order: WorkOrder,
    updates: dict[str, Any],
) -> dict[str, Any]:
    fields = work_order_form_fields(work_order)
    by_key = {field.field_key: field for field in fields}
    unknown = sorted(set(updates) - set(by_key))
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown work-order form fields: {', '.join(unknown)}",
        )
    merged = work_order_form_values(work_order)
    for key, value in updates.items():
        merged[key] = _validated_value(by_key[key], value)
    encoded = json.dumps(merged, separators=(",", ":"), default=str)
    if len(encoded.encode("utf-8")) > 262_144:
        raise HTTPException(status_code=422, detail="Form values cannot exceed 256 KiB")
    return merged


def create_form_action_tasks(
    db: Session,
    work_order: WorkOrder,
    *,
    changed_fields: list[str],
    fields: dict[str, WorkOrderFormFieldRead],
    created_by: int | None,
) -> list[WorkOrderFormAction]:
    tasks: list[WorkOrderFormAction] = []
    for field_key in changed_fields:
        field = fields[field_key]
        action_types: list[str] = []
        if field.triggers_notification:
            action_types.append("notification")
        if field.affects_inventory:
            action_types.append("inventory_review")
        for action_type in action_types:
            task = WorkOrderFormAction(
                organization_id=work_order.organization_id,
                work_order_id=work_order.id,
                template_id=work_order.form_template_id,
                field_key=field.field_key,
                field_label=field.label,
                action_type=action_type,
                triggered_form_version=work_order.form_version,
                created_by=created_by,
            )
            db.add(task)
            tasks.append(task)
    if tasks:
        db.flush()
    return tasks


def work_order_form_read(
    db: Session,
    work_order: WorkOrder,
    *,
    can_edit: bool,
    include_sensitive_values: bool = True,
) -> WorkOrderFormRead:
    fields = work_order_form_fields(work_order)
    values = work_order_form_values(work_order)
    visible_values = dict(values)
    if not include_sensitive_values:
        for field in fields:
            if field.field_type == "signature" and field.field_key in visible_values:
                visible_values[field.field_key] = None
    template = (
        db.get(WorkOrderFormTemplate, work_order.form_template_id)
        if work_order.form_template_id
        else None
    )
    return WorkOrderFormRead(
        work_order_id=work_order.id,
        template_id=work_order.form_template_id,
        template_name=template.name if template else None,
        template_version=work_order.form_template_version,
        form_version=work_order.form_version,
        fields=fields,
        values=visible_values,
        missing_required_fields=missing_required_fields(fields, values),
        can_edit=can_edit,
        is_frozen=work_order.is_locked or work_order.status == "PENDING_APPROVAL",
    )


def validate_work_order_form_completion(work_order: WorkOrder) -> None:
    fields = work_order_form_fields(work_order)
    missing = missing_required_fields(fields, work_order_form_values(work_order))
    if missing:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Configured work-order form is incomplete",
                "missing": [f"custom_form.{key}" for key in missing],
            },
        )


def work_order_form_requires_approval(work_order: WorkOrder) -> bool:
    return any(field.requires_approval for field in work_order_form_fields(work_order))
