from __future__ import annotations

from datetime import datetime, timezone
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import REPORTS_READ
from app.core.rbac import Actor, get_current_actor, require_permission, require_roles
from app.models import AuditLog, PartUsageBaseline, PartUsageReview, UserRole, WorkOrderPart
from app.schemas import (
    AbnormalUsageRow,
    PartUsageBaselineRead,
    PartUsageEvaluationRead,
    PartUsageReviewAction,
)
from app.services.abnormal_usage import (
    evaluate_part_usage,
    part_usage_baseline_read,
    part_usage_review_read,
)
from app.services.inventory import begin_inventory_write


router = APIRouter(prefix="/reports/abnormal-usage", tags=["abnormal-parts-usage"])


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _audit(
    db: Session,
    actor: Actor,
    action: str,
    entity_type: str,
    entity_id: int | None,
    metadata: dict,
) -> None:
    db.add(
        AuditLog(
            organization_id=actor.organization_id,
            user_id=actor.user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            metadata_json=json.dumps(
                {
                    "actor_role": actor.role.value,
                    "auth_method": actor.auth_method,
                    "device_id": actor.device_id,
                    **metadata,
                },
                default=str,
                separators=(",", ":"),
            ),
            timestamp=_utcnow_naive(),
        )
    )


@router.get("/baselines", response_model=list[PartUsageBaselineRead])
def list_part_usage_baselines(
    response: Response,
    part_id: int | None = Query(default=None, ge=1),
    scope: str | None = Query(
        default=None,
        pattern="^(job_machine_store|job_machine|machine|job|organization)$",
    ),
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_permission(actor, REPORTS_READ)
    response.headers["Cache-Control"] = "no-store"
    query = select(PartUsageBaseline).where(
        PartUsageBaseline.organization_id == actor.organization_id
    )
    if part_id is not None:
        query = query.where(PartUsageBaseline.part_id == part_id)
    if scope is not None:
        query = query.where(PartUsageBaseline.scope == scope)
    rows = db.scalars(
        query.order_by(
            PartUsageBaseline.computed_at.desc(),
            PartUsageBaseline.id.desc(),
        ).limit(limit)
    ).all()
    return [part_usage_baseline_read(db, row) for row in rows]


@router.post("/evaluate", response_model=PartUsageEvaluationRead)
def evaluate_part_usage_history(
    limit: int = Query(default=5_000, ge=1, le=5_000),
    after_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_permission(actor, REPORTS_READ)
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    begin_inventory_write(db)
    query = select(WorkOrderPart).where(
        WorkOrderPart.organization_id == actor.organization_id
    )
    if after_id is not None:
        query = query.where(WorkOrderPart.id > after_id)
    rows = db.scalars(query.order_by(WorkOrderPart.id.asc()).limit(limit + 1)).all()
    truncated = len(rows) > limit
    created = already_evaluated = no_anomaly = 0
    for row in rows[:limit]:
        outcome = evaluate_part_usage(db, actor.organization_id, row)
        created += int(outcome.created)
        already_evaluated += int(outcome.already_evaluated)
        no_anomaly += int(outcome.review is None)
    result = PartUsageEvaluationRead(
        scanned=min(len(rows), limit),
        created=created,
        already_evaluated=already_evaluated,
        no_anomaly=no_anomaly,
        truncated=truncated,
        next_after_id=rows[limit - 1].id if truncated else None,
    )
    _audit(
        db,
        actor,
        "part_usage_history_evaluated",
        "part_usage_review",
        None,
        result.model_dump(),
    )
    db.commit()
    return result


@router.post("/{review_id}/actions", response_model=AbnormalUsageRow)
def act_on_part_usage_review(
    review_id: int,
    payload: PartUsageReviewAction,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_permission(actor, REPORTS_READ)
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    begin_inventory_write(db)
    row = db.scalar(
        select(PartUsageReview)
        .where(
            PartUsageReview.id == review_id,
            PartUsageReview.organization_id == actor.organization_id,
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Part usage review not found")
    normalized_note = payload.note.strip() if payload.note else None
    normalized_reason = payload.reason.strip() if payload.reason else None
    if (
        payload.action == "acknowledge"
        and row.status == "acknowledged"
        and row.acknowledged_by == actor.user_id
        and row.acknowledgement_note == normalized_note
    ):
        return part_usage_review_read(db, row)
    if (
        payload.action in {"confirm", "dismiss"}
        and row.status == ("confirmed" if payload.action == "confirm" else "dismissed")
        and row.reviewed_by == actor.user_id
        and row.decision_reason == normalized_reason
    ):
        return part_usage_review_read(db, row)
    if row.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Part usage review changed; refresh before continuing")

    previous_status = row.status
    now = _utcnow_naive()
    if payload.action == "acknowledge":
        if row.status != "pending":
            raise HTTPException(status_code=409, detail="Only a pending review can be acknowledged")
        row.status = "acknowledged"
        row.acknowledged_by = actor.user_id
        row.acknowledged_at = now
        row.acknowledgement_note = normalized_note
    else:
        if row.status != "acknowledged":
            raise HTTPException(status_code=409, detail="A review must be acknowledged before a decision")
        row.status = "confirmed" if payload.action == "confirm" else "dismissed"
        row.reviewed_by = actor.user_id
        row.reviewed_at = now
        row.decision_reason = normalized_reason
    row.version += 1
    row.updated_at = now
    _audit(
        db,
        actor,
        f"part_usage_review_{payload.action}d",
        "part_usage_review",
        row.id,
        {
            "work_order_id": row.work_order_id,
            "work_order_part_id": row.work_order_part_id,
            "part_id": row.part_id,
            "from_status": previous_status,
            "to_status": row.status,
            "previous_version": payload.expected_version,
            "new_version": row.version,
            "note": normalized_note,
            "reason": normalized_reason,
        },
    )
    db.commit()
    db.refresh(row)
    return part_usage_review_read(db, row)
