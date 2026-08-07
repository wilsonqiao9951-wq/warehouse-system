from __future__ import annotations

import csv
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from io import StringIO
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.permissions import REPORTS_EXPORT, REPORTS_READ
from app.core.rbac import Actor, get_current_actor, require_permission
from app.core.security import verify_password
from app.models import AuditLog, User
from app.schemas import AnalyticsExportRequest, EnterpriseAnalyticsRead
from app.services.analytics import build_enterprise_analytics


router = APIRouter(tags=["enterprise-analytics"])


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _require_account_reauthentication(
    db: Session,
    actor: Actor,
    password: str | None,
) -> None:
    if actor.auth_method == "test":
        return
    if actor.auth_method != "bearer" or actor.user_id is None:
        raise HTTPException(status_code=401, detail="Bearer authentication required")
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


def _utc_iso(value: datetime | None) -> str:
    if value is None:
        return ""
    normalized = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return normalized.isoformat().replace("+00:00", "Z")


def _resolved_period(from_date: date | None, to_date: date | None) -> tuple[date, date]:
    resolved_to = to_date or _now_utc().date()
    resolved_from = from_date or (resolved_to - timedelta(days=89))
    return resolved_from, resolved_to


@router.get("/analytics/operations", response_model=EnterpriseAnalyticsRead)
def enterprise_operations_analytics(
    response: Response,
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    engineer_id: int | None = Query(default=None, gt=0),
    job_type: str | None = Query(default=None, max_length=120),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_permission(actor, REPORTS_READ)
    response.headers["Cache-Control"] = "no-store"
    resolved_from, resolved_to = _resolved_period(from_date, to_date)
    return build_enterprise_analytics(
        db,
        actor.organization_id,
        from_date=resolved_from,
        to_date=resolved_to,
        engineer_id=engineer_id,
        job_type=job_type,
    ).dashboard


@router.post("/analytics/operations/export")
def export_enterprise_operations_analytics(
    payload: AnalyticsExportRequest,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_permission(actor, REPORTS_EXPORT)
    _require_account_reauthentication(db, actor, payload.account_password)
    bundle = build_enterprise_analytics(
        db,
        actor.organization_id,
        from_date=payload.from_date,
        to_date=payload.to_date,
        engineer_id=payload.engineer_id,
        job_type=payload.job_type,
    )
    row_count = len(bundle.detail_rows)
    if row_count > max(1, settings.max_analytics_export_rows):
        raise HTTPException(
            status_code=413,
            detail=(
                f"Analytics export contains {row_count} rows; narrow the filters below "
                f"the {settings.max_analytics_export_rows} row limit"
            ),
        )
    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    columns = [
        "work_order_id",
        "ticket_number",
        "completed_at_utc",
        "engineer_id",
        "engineer_name",
        "job_type",
        "first_time_fix",
        "is_rework",
        "repair_duration_minutes",
        "revenue",
        "labor_cost",
        "parts_cost",
        "gross_contribution",
    ]
    writer.writerow(columns)
    for row in bundle.detail_rows:
        writer.writerow(
            [
                _safe_csv_cell(row["work_order_id"]),
                _safe_csv_cell(row["ticket_number"]),
                _safe_csv_cell(_utc_iso(row["completed_at"])),
                _safe_csv_cell(row["engineer_id"]),
                _safe_csv_cell(row["engineer_name"]),
                _safe_csv_cell(row["job_type"]),
                _safe_csv_cell(row["first_time_fix"]),
                _safe_csv_cell(row["is_rework"]),
                _safe_csv_cell(row["repair_duration_minutes"]),
                _safe_csv_cell(round(row["revenue"], 2)),
                _safe_csv_cell(round(row["labor_cost"], 2)),
                _safe_csv_cell(round(row["parts_cost"], 2)),
                _safe_csv_cell(round(row["contribution"], 2)),
            ]
        )
    content = "\ufeff" + output.getvalue()
    digest = sha256(content.encode("utf-8")).hexdigest()
    generated_at = _now_utc()
    db.add(
        AuditLog(
            organization_id=actor.organization_id,
            user_id=actor.user_id,
            action="enterprise_analytics_exported",
            entity_type="enterprise_analytics_export",
            metadata_json=json.dumps(
                {
                    "actor_role": actor.role.value,
                    "auth_method": actor.auth_method,
                    "format": "csv",
                    "row_count": row_count,
                    "sha256": digest,
                    "generated_at": _utc_iso(generated_at),
                    "filters": {
                        "from_date": payload.from_date,
                        "to_date": payload.to_date,
                        "engineer_id": payload.engineer_id,
                        "job_type": payload.job_type,
                    },
                },
                default=str,
                separators=(",", ":"),
            ),
            timestamp=generated_at.replace(tzinfo=None),
        )
    )
    db.commit()
    filename = f"openpartsflow-operations-{generated_at.strftime('%Y%m%dT%H%M%SZ')}.csv"
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
