from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import REPORTS_READ
from app.core.rbac import Actor, get_current_actor, require_permission, require_roles
from app.core.security import verify_password
from app.models import AuditLog, User, UserRole
from app.schemas import (
    ProfitSnapshotBackfillRead,
    ProfitSnapshotBackfillRequest,
    ProfitSnapshotDashboardRead,
)
from app.services.profit_snapshots import (
    backfill_profit_snapshots,
    build_profit_snapshot_dashboard,
)


router = APIRouter(prefix="/analytics", tags=["profit-snapshots"])


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _require_account_reauthentication(
    db: Session,
    actor: Actor,
    password: str | None,
) -> None:
    if actor.auth_method == "test":
        return
    if actor.auth_method not in {"bearer", "cookie"} or actor.user_id is None:
        raise HTTPException(status_code=401, detail="Authenticated session required")
    user = db.get(User, actor.user_id)
    if not password or not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Account password verification failed")


@router.get("/profit-snapshots", response_model=ProfitSnapshotDashboardRead)
def profit_snapshot_dashboard(
    response: Response,
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    ranking_limit: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_permission(actor, REPORTS_READ)
    response.headers["Cache-Control"] = "no-store"
    resolved_to = to_date or _today_utc()
    resolved_from = from_date or (resolved_to - timedelta(days=89))
    try:
        return build_profit_snapshot_dashboard(
            db,
            actor.organization_id,
            from_date=resolved_from,
            to_date=resolved_to,
            ranking_limit=ranking_limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/profit-snapshots/backfill", response_model=ProfitSnapshotBackfillRead)
def backfill_profit_snapshot_history(
    payload: ProfitSnapshotBackfillRequest,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_permission(actor, REPORTS_READ)
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    _require_account_reauthentication(db, actor, payload.account_password)
    resolved_to = payload.to_date or _today_utc()
    resolved_from = payload.from_date or (resolved_to - timedelta(days=3659))
    if resolved_to < resolved_from or (resolved_to - resolved_from).days + 1 > 3660:
        raise HTTPException(status_code=422, detail="Profit snapshot backfill range cannot exceed 3660 days")
    scanned, created, existing, conflicts, next_id = backfill_profit_snapshots(
        db,
        actor.organization_id,
        from_date=resolved_from,
        to_date=resolved_to,
        after_work_order_id=payload.after_work_order_id,
        limit=payload.limit,
    )
    db.add(
        AuditLog(
            organization_id=actor.organization_id,
            user_id=actor.user_id,
            action="profit_snapshots_backfilled",
            entity_type="work_order_profit_snapshot",
            metadata_json=json.dumps(
                {
                    "actor_role": actor.role.value,
                    "auth_method": actor.auth_method,
                    "from_date": resolved_from.isoformat(),
                    "to_date": resolved_to.isoformat(),
                    "after_work_order_id": payload.after_work_order_id,
                    "limit": payload.limit,
                    "scanned": scanned,
                    "created": created,
                    "existing": existing,
                    "conflicts": conflicts,
                    "next_after_work_order_id": next_id,
                },
                separators=(",", ":"),
            ),
            timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
        )
    )
    db.commit()
    return ProfitSnapshotBackfillRead(
        scanned=scanned,
        created=created,
        existing=existing,
        conflicts=conflicts,
        next_after_work_order_id=next_id,
    )
