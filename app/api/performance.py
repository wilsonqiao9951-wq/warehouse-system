from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import REPORTS_READ
from app.core.rbac import Actor, get_current_actor, require_permission, require_roles
from app.models import UserRole
from app.schemas import PerformanceDashboardRead
from app.services.performance import build_performance_dashboard


router = APIRouter(prefix="/performance", tags=["employee-performance"])


@router.get("/scorecards", response_model=PerformanceDashboardRead)
def employee_performance_scorecards(
    response: Response,
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    engineer_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    response.headers["Cache-Control"] = "no-store"
    resolved_to = to_date or datetime.now(timezone.utc).date()
    resolved_from = from_date or (resolved_to - timedelta(days=89))

    if actor.role == UserRole.ENGINEER:
        if actor.user_id is None:
            raise HTTPException(status_code=401, detail="Authenticated engineer required")
        if engineer_id is not None and engineer_id != actor.user_id:
            raise HTTPException(status_code=403, detail="Engineers can view only their own scorecard")
        selected_engineer_id = actor.user_id
        can_view_team = False
        can_view_financials = False
    else:
        require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
        require_permission(actor, REPORTS_READ)
        selected_engineer_id = engineer_id
        can_view_team = True
        can_view_financials = True

    return build_performance_dashboard(
        db,
        actor.organization_id,
        from_date=resolved_from,
        to_date=resolved_to,
        selected_engineer_id=selected_engineer_id,
        can_view_team=can_view_team,
        can_view_financials=can_view_financials,
    )
