from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
from time import perf_counter

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import AGENT_USE, USERS_READ
from app.core.rbac import Actor, get_current_actor, require_permission
from app.models import AuditLog, EnterpriseAgentRun, User, UserRole, WorkOrder
from app.schemas import (
    EnterpriseAgentFilterRead,
    EnterpriseAgentGuardrailsRead,
    EnterpriseAgentOptionsRead,
    EnterpriseAgentRequest,
    EnterpriseAgentResponse,
    EnterpriseAgentRunRead,
)
from app.services.commercial import consume_monthly_usage
from app.services.enterprise_agent import build_enterprise_agent_draft


router = APIRouter(tags=["enterprise-agent"])


_INTENT_OPTIONS = [
    {"value": "daily_brief", "label": "Daily operating brief"},
    {"value": "backlog_risk", "label": "Backlog risk"},
    {"value": "service_quality", "label": "Service quality"},
    {"value": "inventory_risk", "label": "Inventory readiness"},
    {"value": "integration_health", "label": "Integration health"},
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utcnow_naive() -> datetime:
    return _utcnow().replace(tzinfo=None)


def _resolved_period(payload: EnterpriseAgentRequest) -> tuple[date, date]:
    to_date = payload.to_date or _utcnow().date()
    from_date = payload.from_date or (to_date - timedelta(days=29))
    return from_date, to_date


def _json_object(value: str) -> dict:
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


@router.post("/agent/operations", response_model=EnterpriseAgentResponse)
def run_enterprise_operations_agent(
    payload: EnterpriseAgentRequest,
    response: Response,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_permission(actor, AGENT_USE)
    if payload.engineer_id is not None:
        require_permission(actor, USERS_READ)
    response.headers["Cache-Control"] = "no-store"
    from_date, to_date = _resolved_period(payload)
    started = perf_counter()
    consume_monthly_usage(db, actor.organization_id, ai_requests=1)
    draft = build_enterprise_agent_draft(
        db,
        actor.organization_id,
        question=payload.question,
        requested_intent=payload.intent,
        from_date=from_date,
        to_date=to_date,
        engineer_id=payload.engineer_id,
        job_type=payload.job_type,
    )
    duration_ms = max(0, round((perf_counter() - started) * 1000))
    question_digest = sha256(payload.question.encode("utf-8")).hexdigest()
    filters = {
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
        "engineer_id": payload.engineer_id,
        "job_type": payload.job_type.strip() if payload.job_type else None,
    }
    run = EnterpriseAgentRun(
        organization_id=actor.organization_id,
        user_id=actor.user_id,
        intent=draft.intent,
        question_sha256=question_digest,
        question_length=len(payload.question),
        filters_json=json.dumps(filters, separators=(",", ":")),
        tools_json=json.dumps(draft.tools_used, separators=(",", ":")),
        finding_count=len(draft.findings),
        duration_ms=duration_ms,
        status="completed",
        created_at=_utcnow_naive(),
    )
    db.add(run)
    db.flush()
    db.add(
        AuditLog(
            organization_id=actor.organization_id,
            user_id=actor.user_id,
            action="enterprise_agent_run_completed",
            entity_type="enterprise_agent_run",
            entity_id=run.id,
            metadata_json=json.dumps(
                {
                    "actor_role": actor.role.value,
                    "auth_method": actor.auth_method,
                    "intent": draft.intent,
                    "question_sha256": question_digest,
                    "question_length": len(payload.question),
                    "filters": filters,
                    "tools_used": draft.tools_used,
                    "finding_count": len(draft.findings),
                    "duration_ms": duration_ms,
                    "read_only": True,
                    "external_model_called": False,
                },
                separators=(",", ":"),
            ),
            timestamp=_utcnow_naive(),
        )
    )
    db.commit()
    dashboard = draft.analytics.dashboard
    return EnterpriseAgentResponse(
        run_id=run.id,
        generated_at=_utcnow(),
        intent=draft.intent,
        summary=draft.summary,
        priority=draft.priority,
        confidence=draft.confidence,
        filters=EnterpriseAgentFilterRead(
            from_date=from_date,
            to_date=to_date,
            engineer_id=payload.engineer_id,
            job_type=payload.job_type.strip() if payload.job_type else None,
            engineers=(
                dashboard.filters.engineers if USERS_READ in actor.permissions else []
            ),
            job_types=dashboard.filters.job_types,
        ),
        findings=draft.findings,
        tools_used=draft.tools_used,
        limitations=draft.limitations,
        guardrails=EnterpriseAgentGuardrailsRead(),
    )


@router.get("/agent/options", response_model=EnterpriseAgentOptionsRead)
def enterprise_agent_options(
    response: Response,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_permission(actor, AGENT_USE)
    response.headers["Cache-Control"] = "no-store"
    engineers = (
        db.scalars(
            select(User)
            .where(
                User.organization_id == actor.organization_id,
                User.role == UserRole.ENGINEER,
                User.is_active.is_(True),
            )
            .order_by(User.name, User.id)
        ).all()
        if USERS_READ in actor.permissions
        else []
    )
    job_types = sorted(
        {
            value.strip()
            for value in db.scalars(
                select(WorkOrder.job_type).where(
                    WorkOrder.organization_id == actor.organization_id,
                    WorkOrder.job_type.is_not(None),
                    func.length(func.trim(WorkOrder.job_type)) > 0,
                )
            ).all()
            if value and value.strip()
        },
        key=str.casefold,
    )
    return EnterpriseAgentOptionsRead(
        intents=_INTENT_OPTIONS,
        engineers=[
            {"value": str(engineer.id), "label": engineer.name}
            for engineer in engineers
        ],
        job_types=[{"value": value, "label": value} for value in job_types],
    )


@router.get("/agent/runs", response_model=list[EnterpriseAgentRunRead])
def list_enterprise_agent_runs(
    response: Response,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_permission(actor, AGENT_USE)
    response.headers["Cache-Control"] = "no-store"
    rows = db.scalars(
        select(EnterpriseAgentRun)
        .where(EnterpriseAgentRun.organization_id == actor.organization_id)
        .order_by(EnterpriseAgentRun.created_at.desc(), EnterpriseAgentRun.id.desc())
        .limit(limit)
    ).all()
    return [
        EnterpriseAgentRunRead(
            id=row.id,
            user_id=row.user_id,
            intent=row.intent,
            question_sha256=row.question_sha256,
            question_length=row.question_length,
            filters=_json_object(row.filters_json),
            tools_used=_json_list(row.tools_json),
            finding_count=row.finding_count,
            duration_ms=row.duration_ms,
            status=row.status,
            error_code=row.error_code,
            created_at=row.created_at,
        )
        for row in rows
    ]
