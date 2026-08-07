from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import StringIO
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.permissions import AUDIT_EXPORT, AUDIT_READ
from app.core.rbac import Actor, get_current_actor, require_permission
from app.core.security import verify_password
from app.models import AuditLog, User
from app.schemas import (
    AuditLogExportRequest,
    AuditLogPageRead,
    AuditLogRead,
    AuditLogSummaryBucket,
    AuditLogSummaryRead,
)


router = APIRouter(tags=["audit-logs"])


def _now_utc_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _utc_naive(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _utc_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _utc_iso(value: datetime | None) -> str:
    normalized = _utc_aware(value)
    return normalized.isoformat().replace("+00:00", "Z") if normalized else ""


def _conditions(
    actor: Actor,
    *,
    action: str | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    user_id: int | None = None,
    from_at: datetime | None = None,
    to_at: datetime | None = None,
) -> list[Any]:
    conditions: list[Any] = [AuditLog.organization_id == actor.organization_id]
    if action:
        conditions.append(AuditLog.action == action.strip())
    if entity_type:
        conditions.append(AuditLog.entity_type == entity_type.strip())
    if entity_id is not None:
        conditions.append(AuditLog.entity_id == entity_id)
    if user_id is not None:
        conditions.append(AuditLog.user_id == user_id)
    normalized_from = _utc_naive(from_at)
    normalized_to = _utc_naive(to_at)
    if normalized_from is not None:
        conditions.append(AuditLog.timestamp >= normalized_from)
    if normalized_to is not None:
        conditions.append(AuditLog.timestamp <= normalized_to)
    return conditions


def _metadata(value: str | None) -> tuple[dict[str, Any], bool]:
    if not value:
        return {}, True
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {"legacy_raw": value}, False
    if isinstance(parsed, dict):
        return parsed, True
    return {"value": parsed}, True


def _read(row: AuditLog, user_name: str | None) -> AuditLogRead:
    metadata, metadata_valid = _metadata(row.metadata_json)
    return AuditLogRead(
        id=row.id,
        organization_id=row.organization_id,
        user_id=row.user_id,
        user_name=user_name,
        action=row.action,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        timestamp=_utc_aware(row.timestamp),
        metadata=metadata,
        metadata_valid=metadata_valid,
    )


def _require_valid_range(from_at: datetime | None, to_at: datetime | None) -> None:
    normalized_from = _utc_naive(from_at)
    normalized_to = _utc_naive(to_at)
    if normalized_from is not None and normalized_to is not None and normalized_to < normalized_from:
        raise HTTPException(status_code=422, detail="to_at must be on or after from_at")


def _require_account_reauthentication(db: Session, actor: Actor, password: str | None) -> None:
    if actor.auth_method == "test":
        return
    if actor.auth_method not in {"bearer", "cookie"} or actor.user_id is None:
        raise HTTPException(status_code=401, detail="Authenticated session required")
    user = db.get(User, actor.user_id)
    if not password or not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Account password verification failed")


def _safe_csv_cell(value: object) -> object:
    if value is None:
        return ""
    if not isinstance(value, str):
        return value
    if value and (value[0] in "=+-@" or value[0] in "\t\r\n"):
        return f"'{value}"
    return value


@router.get("/audit-logs")
def list_audit_logs(
    response: Response,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    """Compatibility list retained for existing API consumers."""
    require_permission(actor, AUDIT_READ)
    response.headers["Cache-Control"] = "no-store"
    rows = db.scalars(
        select(AuditLog)
        .where(AuditLog.organization_id == actor.organization_id)
        .order_by(AuditLog.id.desc())
        .offset(skip)
        .limit(limit)
    ).all()
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


@router.get("/audit-logs/search", response_model=AuditLogPageRead)
def search_audit_logs(
    response: Response,
    action: str | None = Query(default=None, max_length=120),
    entity_type: str | None = Query(default=None, max_length=120),
    entity_id: int | None = Query(default=None, ge=1),
    user_id: int | None = Query(default=None, ge=1),
    from_at: datetime | None = Query(default=None),
    to_at: datetime | None = Query(default=None),
    before_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_permission(actor, AUDIT_READ)
    response.headers["Cache-Control"] = "no-store"
    _require_valid_range(from_at, to_at)
    conditions = _conditions(
        actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=user_id,
        from_at=from_at,
        to_at=to_at,
    )
    total = db.scalar(select(func.count(AuditLog.id)).where(*conditions)) or 0
    page_conditions = [*conditions]
    if before_id is not None:
        page_conditions.append(AuditLog.id < before_id)
    rows = db.execute(
        select(AuditLog, User.name)
        .outerjoin(User, User.id == AuditLog.user_id)
        .where(*page_conditions)
        .order_by(AuditLog.id.desc())
        .limit(limit + 1)
    ).all()
    has_more = len(rows) > limit
    visible = rows[:limit]
    items = [_read(row, user_name) for row, user_name in visible]
    return AuditLogPageRead(
        items=items,
        total=total,
        next_before_id=items[-1].id if has_more and items else None,
    )


@router.get("/audit-logs/summary", response_model=AuditLogSummaryRead)
def summarize_audit_logs(
    response: Response,
    days: int = Query(default=30, ge=1, le=365),
    action: str | None = Query(default=None, max_length=120),
    entity_type: str | None = Query(default=None, max_length=120),
    entity_id: int | None = Query(default=None, ge=1),
    user_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_permission(actor, AUDIT_READ)
    response.headers["Cache-Control"] = "no-store"
    conditions = _conditions(
        actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=user_id,
        from_at=_now_utc_naive() - timedelta(days=days),
    )
    aggregate = db.execute(
        select(
            func.count(AuditLog.id),
            func.count(func.distinct(AuditLog.user_id)),
            func.max(AuditLog.timestamp),
        ).where(*conditions)
    ).one()

    def buckets(column: Any) -> list[AuditLogSummaryBucket]:
        count = func.count(AuditLog.id)
        rows = db.execute(
            select(column, count)
            .where(*conditions)
            .group_by(column)
            .order_by(count.desc(), column.asc())
            .limit(10)
        ).all()
        return [
            AuditLogSummaryBucket(value=str(value), count=row_count)
            for value, row_count in rows
        ]

    return AuditLogSummaryRead(
        window_days=days,
        total_events=aggregate[0] or 0,
        unique_actors=aggregate[1] or 0,
        latest_event_at=_utc_aware(aggregate[2]),
        by_action=buckets(AuditLog.action),
        by_entity_type=buckets(AuditLog.entity_type),
    )


@router.post("/audit-logs/export")
def export_audit_logs(
    payload: AuditLogExportRequest,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_permission(actor, AUDIT_EXPORT)
    _require_account_reauthentication(db, actor, payload.account_password)
    conditions = _conditions(
        actor,
        action=payload.action,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        user_id=payload.user_id,
        from_at=payload.from_at,
        to_at=payload.to_at,
    )
    row_count = db.scalar(select(func.count(AuditLog.id)).where(*conditions)) or 0
    if row_count > max(1, settings.max_audit_export_rows):
        raise HTTPException(
            status_code=413,
            detail=(
                f"Audit export contains {row_count} rows; narrow the filters below "
                f"the {settings.max_audit_export_rows} row limit"
            ),
        )
    rows = db.execute(
        select(AuditLog, User.name)
        .outerjoin(User, User.id == AuditLog.user_id)
        .where(*conditions)
        .order_by(AuditLog.id.asc())
    ).all()
    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        [
            "id",
            "timestamp_utc",
            "user_id",
            "user_name",
            "action",
            "entity_type",
            "entity_id",
            "metadata_json",
        ]
    )
    for row, user_name in rows:
        writer.writerow(
            [
                _safe_csv_cell(row.id),
                _safe_csv_cell(_utc_iso(row.timestamp)),
                _safe_csv_cell(row.user_id),
                _safe_csv_cell(user_name),
                _safe_csv_cell(row.action),
                _safe_csv_cell(row.entity_type),
                _safe_csv_cell(row.entity_id),
                _safe_csv_cell(row.metadata_json),
            ]
        )
    content = "\ufeff" + output.getvalue()
    digest = sha256(content.encode("utf-8")).hexdigest()
    generated_at = _now_utc_naive()
    db.add(
        AuditLog(
            organization_id=actor.organization_id,
            user_id=actor.user_id,
            action="audit_log_exported",
            entity_type="audit_log_export",
            metadata_json=json.dumps(
                {
                    "actor_role": actor.role.value,
                    "auth_method": actor.auth_method,
                    "format": "csv",
                    "row_count": row_count,
                    "sha256": digest,
                    "generated_at": _utc_iso(generated_at),
                    "filters": {
                        "action": payload.action,
                        "entity_type": payload.entity_type,
                        "entity_id": payload.entity_id,
                        "user_id": payload.user_id,
                        "from_at": payload.from_at,
                        "to_at": payload.to_at,
                    },
                },
                default=str,
                separators=(",", ":"),
            ),
            timestamp=generated_at,
        )
    )
    db.commit()
    filename = f"openpartsflow-audit-{generated_at.strftime('%Y%m%dT%H%M%SZ')}.csv"
    return StreamingResponse(
        iter([content]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-SHA256": digest,
            "X-Record-Count": str(row_count),
        },
    )
