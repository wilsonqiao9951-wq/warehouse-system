from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
from ipaddress import ip_address
import json
import secrets
from urllib.parse import urlsplit

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    AuditLog,
    ExternalIntegration,
    ExternalSyncLog,
    ExternalWorkOrderLink,
    WorkOrder,
)
from app.schemas import (
    ExternalIntegrationRead,
    ExternalSyncLogRead,
    ExternalWorkOrderUpsert,
    ExternalWorkOrderUpsertRead,
    WorkOrderCreate,
)
from app.services.commercial import consume_monthly_usage


ALLOWED_WORK_ORDER_FIELDS = {
    "ticket_number",
    "wo_number",
    "schedule_date",
    "outlet_name",
    "store_name",
    "job_type",
    "description",
    "problem_description",
    "address",
    "city",
    "state",
    "zip",
    "contact_phone",
    "machine_type",
    "status",
}

_FIELD_MAX_LENGTHS = {
    "ticket_number": 120,
    "wo_number": 120,
    "outlet_name": 255,
    "store_name": 255,
    "job_type": 120,
    "description": 20_000,
    "problem_description": 20_000,
    "address": 500,
    "city": 120,
    "state": 120,
    "zip": 20,
    "contact_phone": 50,
    "machine_type": 255,
    "status": 50,
}

_SAFE_EXTERNAL_STATUSES = {"open", "scheduled"}
_PROTECTED_WORK_ORDER_STATUSES = {
    "completed",
    "pending_approval",
    "approval_rejected",
}
SUPPORTED_WEBHOOK_EVENTS = {
    "work_order.status_changed",
    "work_order.completed",
    "work_order.part_used",
}


def generate_api_key() -> tuple[str, str, str]:
    prefix = secrets.token_hex(6)
    raw_key = f"opf_{prefix}_{secrets.token_urlsafe(32)}"
    return raw_key, prefix, hash_api_key(raw_key)


def hash_api_key(raw_key: str) -> str:
    return sha256(raw_key.encode("utf-8")).hexdigest()


def api_key_prefix(raw_key: str) -> str | None:
    parts = raw_key.split("_", 2)
    if len(parts) != 3 or parts[0] != "opf" or not parts[1]:
        return None
    return parts[1]


def validate_field_mapping(mapping: dict[str, str]) -> dict[str, str]:
    unknown = sorted(set(mapping) - ALLOWED_WORK_ORDER_FIELDS)
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported work-order mapping fields: {', '.join(unknown)}",
        )
    normalized: dict[str, str] = {}
    for canonical, external_name in mapping.items():
        name = external_name.strip()
        if not name:
            raise HTTPException(
                status_code=422,
                detail=f"External field name for {canonical} cannot be blank",
            )
        if len(name) > 160:
            raise HTTPException(
                status_code=422,
                detail=f"External field name for {canonical} is too long",
            )
        normalized[canonical] = name
    return normalized


def validate_webhook_url(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    parsed = urlsplit(cleaned)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise HTTPException(
            status_code=422,
            detail="Webhook URL must be an HTTPS URL without credentials or fragments",
        )
    hostname = parsed.hostname.casefold().rstrip(".")
    if hostname == "localhost" or hostname.endswith(".localhost") or hostname.endswith(".local"):
        raise HTTPException(
            status_code=422,
            detail="Webhook URL cannot target a local host",
        )
    try:
        address = ip_address(hostname)
    except ValueError:
        address = None
    if address and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        raise HTTPException(
            status_code=422,
            detail="Webhook URL cannot target a private or reserved network",
        )
    return cleaned


def validate_subscribed_events(events: list[str]) -> list[str]:
    unknown = sorted(set(events) - SUPPORTED_WEBHOOK_EVENTS)
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported webhook events: {', '.join(unknown)}",
        )
    return sorted(set(events))


def integration_mapping(integration: ExternalIntegration) -> dict[str, str]:
    try:
        raw = json.loads(integration.field_mapping_json or "{}")
    except json.JSONDecodeError:
        raw = {}
    return validate_field_mapping(raw if isinstance(raw, dict) else {})


def integration_subscribed_events(integration: ExternalIntegration) -> list[str]:
    try:
        raw = json.loads(integration.subscribed_events_json or "[]")
    except json.JSONDecodeError:
        raw = []
    return validate_subscribed_events(raw if isinstance(raw, list) else [])


def integration_read(integration: ExternalIntegration) -> ExternalIntegrationRead:
    return ExternalIntegrationRead(
        id=integration.id,
        organization_id=integration.organization_id,
        name=integration.name,
        provider=integration.provider,
        key_prefix=integration.key_prefix,
        masked_api_key=f"opf_{integration.key_prefix}_...",
        field_mapping=integration_mapping(integration),
        webhook_url=integration.webhook_url,
        subscribed_events=integration_subscribed_events(integration),
        is_active=integration.is_active,
        version=integration.version,
        last_used_at=integration.last_used_at,
        created_by=integration.created_by,
        updated_by=integration.updated_by,
        created_at=integration.created_at,
        updated_at=integration.updated_at,
    )


def sync_log_read(log: ExternalSyncLog) -> ExternalSyncLogRead:
    try:
        changed_fields = json.loads(log.changed_fields_json or "[]")
    except json.JSONDecodeError:
        changed_fields = []
    return ExternalSyncLogRead(
        id=log.id,
        integration_id=log.integration_id,
        direction=log.direction,
        event_type=log.event_type,
        external_id=log.external_id,
        idempotency_key=log.idempotency_key,
        status=log.status,
        attempt_count=log.attempt_count,
        work_order_id=log.work_order_id,
        changed_fields=changed_fields if isinstance(changed_fields, list) else [],
        response_status_code=log.response_status_code,
        error_message=log.error_message,
        next_retry_at=log.next_retry_at,
        last_attempt_at=log.last_attempt_at,
        processed_at=log.processed_at,
        created_at=log.created_at,
        updated_at=log.updated_at,
    )


def _request_hash(payload: ExternalWorkOrderUpsert) -> str:
    serialized = json.dumps(
        payload.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return sha256(serialized.encode("utf-8")).hexdigest()


def _default_ticket(integration: ExternalIntegration, external_id: str) -> str:
    digest = sha256(external_id.encode("utf-8")).hexdigest()[:20]
    return f"EXT-{integration.id}-{digest}"


def _mapped_work_order_data(
    integration: ExternalIntegration,
    payload: ExternalWorkOrderUpsert,
    *,
    creating: bool,
) -> dict:
    mapping = integration_mapping(integration)
    canonical: dict[str, object] = {}
    for field in ALLOWED_WORK_ORDER_FIELDS:
        external_name = mapping.get(field, field)
        if external_name in payload.data:
            canonical[field] = payload.data[external_name]

    for field, maximum in _FIELD_MAX_LENGTHS.items():
        value = canonical.get(field)
        if value is None or field == "schedule_date":
            continue
        if not isinstance(value, str):
            value = str(value)
        value = value.strip()
        if len(value) > maximum:
            raise HTTPException(
                status_code=422,
                detail=f"Mapped {field} exceeds {maximum} characters",
            )
        canonical[field] = value or None
    if canonical.get("schedule_date") == "":
        canonical["schedule_date"] = None

    if "status" in canonical:
        status = str(canonical["status"] or "").strip().casefold()
        if status not in _SAFE_EXTERNAL_STATUSES:
            raise HTTPException(
                status_code=409,
                detail="External systems may set only open or scheduled status",
            )
        canonical["status"] = status
    elif creating:
        canonical["status"] = "open"

    identifiers_supplied = "ticket_number" in canonical or "wo_number" in canonical
    if identifiers_supplied and not (
        canonical.get("ticket_number") or canonical.get("wo_number")
    ):
        raise HTTPException(
            status_code=422,
            detail="Mapped ticket_number or wo_number cannot be blank",
        )
    if creating and not canonical.get("ticket_number") and not canonical.get("wo_number"):
        canonical["ticket_number"] = _default_ticket(integration, payload.external_id)
    if canonical.get("ticket_number") and not canonical.get("wo_number"):
        canonical["wo_number"] = canonical["ticket_number"]
    if canonical.get("wo_number") and not canonical.get("ticket_number"):
        canonical["ticket_number"] = canonical["wo_number"]
    if "outlet_name" in canonical and "store_name" not in canonical:
        canonical["store_name"] = canonical["outlet_name"]
    if "store_name" in canonical and "outlet_name" not in canonical:
        canonical["outlet_name"] = canonical["store_name"]
    if "description" in canonical and "problem_description" not in canonical:
        canonical["problem_description"] = canonical["description"]
    if "problem_description" in canonical and "description" not in canonical:
        canonical["description"] = canonical["problem_description"]

    validation_payload = dict(canonical)
    if not creating and not (
        validation_payload.get("ticket_number") or validation_payload.get("wo_number")
    ):
        validation_payload["ticket_number"] = "validation-placeholder"
    try:
        validated = WorkOrderCreate.model_validate(validation_payload)
    except ValidationError as exc:
        first_error = exc.errors(include_url=False)[0]
        location = ".".join(str(item) for item in first_error.get("loc", ()))
        message = first_error.get("msg", "invalid value")
        raise HTTPException(
            status_code=422,
            detail=f"Invalid mapped work-order field {location}: {message}",
        ) from exc
    validated_data = validated.model_dump()
    return {
        field: validated_data[field]
        for field in canonical
        if field in validated_data
    }


def _mark_failed(
    db: Session,
    log_id: int,
    detail: str,
) -> None:
    db.rollback()
    log = db.get(ExternalSyncLog, log_id)
    if not log:
        return
    log.status = "failed"
    log.error_message = detail[:4000]
    log.processed_at = datetime.utcnow()
    db.add(log)
    db.commit()


def _create_processing_log(
    db: Session,
    integration: ExternalIntegration,
    payload: ExternalWorkOrderUpsert,
    idempotency_key: str,
    request_hash: str,
) -> tuple[ExternalSyncLog, ExternalWorkOrderUpsertRead | None]:
    existing = db.scalar(
        select(ExternalSyncLog).where(
            ExternalSyncLog.integration_id == integration.id,
            ExternalSyncLog.idempotency_key == idempotency_key,
        )
    )
    if existing:
        if not secrets.compare_digest(existing.request_hash, request_hash):
            raise HTTPException(
                status_code=409,
                detail="Idempotency key was already used with different data",
            )
        if existing.status == "processed" and existing.response_json:
            response = ExternalWorkOrderUpsertRead.model_validate_json(
                existing.response_json
            )
            return existing, response.model_copy(update={"replayed": True})
        if (
            existing.status == "processing"
            and datetime.utcnow() - existing.updated_at < timedelta(minutes=5)
        ):
            raise HTTPException(
                status_code=409,
                detail="A request with this idempotency key is already processing",
            )
        existing.status = "processing"
        existing.error_message = None
        existing.processed_at = None
        existing.attempt_count += 1
        log = existing
    else:
        log = ExternalSyncLog(
            organization_id=integration.organization_id,
            integration_id=integration.id,
            direction="inbound",
            event_type="work_order_upsert",
            external_id=payload.external_id.strip(),
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            status="processing",
            attempt_count=1,
        )
        db.add(log)
    integration.last_used_at = datetime.utcnow()
    db.add(integration)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = db.scalar(
            select(ExternalSyncLog).where(
                ExternalSyncLog.integration_id == integration.id,
                ExternalSyncLog.idempotency_key == idempotency_key,
            )
        )
        if (
            concurrent
            and secrets.compare_digest(concurrent.request_hash, request_hash)
            and concurrent.status == "processed"
            and concurrent.response_json
        ):
            response = ExternalWorkOrderUpsertRead.model_validate_json(
                concurrent.response_json
            )
            return concurrent, response.model_copy(update={"replayed": True})
        raise HTTPException(
            status_code=409,
            detail="A request with this idempotency key is already processing",
        )
    db.refresh(log)
    return log, None


def upsert_external_work_order(
    db: Session,
    integration: ExternalIntegration,
    payload: ExternalWorkOrderUpsert,
    idempotency_key: str,
) -> ExternalWorkOrderUpsertRead:
    external_id = payload.external_id.strip()
    request_hash = _request_hash(payload)
    log, replay = _create_processing_log(
        db,
        integration,
        payload,
        idempotency_key,
        request_hash,
    )
    if replay:
        return replay

    try:
        link = db.scalar(
            select(ExternalWorkOrderLink).where(
                ExternalWorkOrderLink.integration_id == integration.id,
                ExternalWorkOrderLink.external_id == external_id,
            )
        )
        work_order = db.get(WorkOrder, link.work_order_id) if link else None
        creating = link is None
        if link and not work_order:
            raise HTTPException(
                status_code=409,
                detail="The linked work order no longer exists",
            )
        if work_order and (
            work_order.is_locked
            or work_order.claimed_by_id is not None
            or work_order.status.strip().casefold() in _PROTECTED_WORK_ORDER_STATUSES
        ):
            raise HTTPException(
                status_code=409,
                detail="External updates are blocked after a work order is claimed or frozen",
            )

        mapped = _mapped_work_order_data(
            integration,
            payload,
            creating=creating,
        )
        consume_monthly_usage(
            db,
            integration.organization_id,
            api_requests=1,
        )
        changed_fields: list[str] = []
        if creating:
            work_order = WorkOrder(
                organization_id=integration.organization_id,
                **mapped,
            )
            db.add(work_order)
            db.flush()
            link = ExternalWorkOrderLink(
                organization_id=integration.organization_id,
                integration_id=integration.id,
                external_id=external_id,
                work_order_id=work_order.id,
                last_inbound_at=datetime.utcnow(),
            )
            db.add(link)
            changed_fields = sorted(mapped)
            result = "created"
        else:
            for field, value in mapped.items():
                if getattr(work_order, field) != value:
                    setattr(work_order, field, value)
                    changed_fields.append(field)
            link.last_inbound_at = datetime.utcnow()
            db.add_all((work_order, link))
            result = "updated"

        response = ExternalWorkOrderUpsertRead(
            integration_id=integration.id,
            external_id=external_id,
            work_order_id=work_order.id,
            ticket_number=work_order.ticket_number,
            result=result,
            changed_fields=sorted(changed_fields),
        )
        log.status = "processed"
        log.work_order_id = work_order.id
        log.changed_fields_json = json.dumps(
            response.changed_fields,
            separators=(",", ":"),
        )
        log.response_json = response.model_dump_json()
        log.error_message = None
        log.processed_at = datetime.utcnow()
        db.add(log)
        db.add(
            AuditLog(
                organization_id=integration.organization_id,
                user_id=None,
                action=f"external_work_order_{result}",
                entity_type="work_order",
                entity_id=work_order.id,
                metadata_json=json.dumps(
                    {
                        "integration_id": integration.id,
                        "provider": integration.provider,
                        "external_id": external_id,
                        "idempotency_key": idempotency_key,
                        "changed_fields": response.changed_fields,
                    },
                    separators=(",", ":"),
                ),
                timestamp=datetime.utcnow(),
            )
        )
        db.commit()
        return response
    except HTTPException as exc:
        _mark_failed(db, log.id, str(exc.detail))
        raise
    except IntegrityError as exc:
        _mark_failed(
            db,
            log.id,
            "A mapped work-order identifier conflicts with an existing record",
        )
        raise HTTPException(
            status_code=409,
            detail="A mapped work-order identifier conflicts with an existing record",
        ) from exc
    except Exception:
        _mark_failed(
            db,
            log.id,
            "Unexpected integration processing error",
        )
        raise
