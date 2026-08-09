from __future__ import annotations

from datetime import datetime
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rbac import Actor, get_current_actor, require_roles
from app.core.security import verify_password
from app.models import PilotCampaign, PilotIssue, User, UserRole
from app.schemas import (
    PilotAttestationCreate,
    PilotCampaignCreate,
    PilotCampaignRead,
    PilotCampaignTransition,
    PilotDecisionCreate,
    PilotIssueCreate,
    PilotIssueResolve,
)
from app.services.pilot_governance import (
    add_audit,
    campaign_or_404,
    campaign_read,
    decision_snapshot,
    record_attestation,
)


router = APIRouter(prefix="/pilot")
OPERATIONAL_ROLES = (
    UserRole.ADMIN,
    UserRole.MANAGER,
    UserRole.WAREHOUSE,
    UserRole.ENGINEER,
)


def _reauthenticate(db: Session, actor: Actor, password: str) -> None:
    if actor.user_id is None:
        raise HTTPException(status_code=401, detail="Authenticated user required")
    if actor.auth_method == "test":
        return
    if actor.auth_method not in {"bearer", "cookie"}:
        raise HTTPException(status_code=401, detail="Authenticated session required")
    user = db.get(User, actor.user_id)
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Account password verification failed")


@router.get("/campaigns", response_model=list[PilotCampaignRead])
def list_pilot_campaigns(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, *OPERATIONAL_ROLES)
    rows = db.scalars(
        select(PilotCampaign)
        .where(PilotCampaign.organization_id == actor.organization_id)
        .order_by(PilotCampaign.created_at.desc(), PilotCampaign.id.desc())
        .limit(limit)
    ).all()
    return [campaign_read(db, row, actor) for row in rows]


@router.post("/campaigns", response_model=PilotCampaignRead)
def create_pilot_campaign(
    payload: PilotCampaignCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    if actor.user_id is None:
        raise HTTPException(status_code=401, detail="Authenticated user required")
    now = datetime.utcnow()
    row = PilotCampaign(
        organization_id=actor.organization_id,
        name=payload.name,
        planned_start=payload.planned_start,
        planned_end=payload.planned_end,
        status="draft",
        version=0,
        created_by=actor.user_id,
        updated_by=actor.user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    add_audit(
        db,
        actor,
        "create_pilot_campaign",
        row.id,
        {
            "status": row.status,
            "planned_start": row.planned_start.isoformat(),
            "planned_end": row.planned_end.isoformat(),
        },
    )
    db.commit()
    db.refresh(row)
    return campaign_read(db, row, actor)


@router.get("/campaigns/{campaign_id}", response_model=PilotCampaignRead)
def get_pilot_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, *OPERATIONAL_ROLES)
    return campaign_read(db, campaign_or_404(db, actor.organization_id, campaign_id), actor)


@router.post("/campaigns/{campaign_id}/transitions", response_model=PilotCampaignRead)
def transition_pilot_campaign(
    campaign_id: int,
    payload: PilotCampaignTransition,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    _reauthenticate(db, actor, payload.account_password)
    row = db.scalar(
        select(PilotCampaign)
        .where(
            PilotCampaign.id == campaign_id,
            PilotCampaign.organization_id == actor.organization_id,
        )
        .with_for_update()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Pilot campaign not found")
    if row.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Pilot campaign version changed")
    allowed = {
        "draft": {"active"},
        "active": {"decision_pending"},
        "decision_pending": {"active"},
    }
    if payload.target_status not in allowed.get(row.status, set()):
        raise HTTPException(status_code=409, detail="Invalid pilot campaign transition")
    previous_status = row.status
    row.status = payload.target_status
    row.version += 1
    row.updated_by = actor.user_id
    row.updated_at = datetime.utcnow()
    if previous_status == "draft":
        row.started_at = row.updated_at
    add_audit(
        db,
        actor,
        "transition_pilot_campaign",
        row.id,
        {
            "previous_status": previous_status,
            "new_status": row.status,
            "new_version": row.version,
            "reason": payload.reason,
        },
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Another pilot campaign is already active")
    db.refresh(row)
    return campaign_read(db, row, actor)


@router.post("/campaigns/{campaign_id}/attestations", response_model=PilotCampaignRead)
def create_pilot_attestation(
    campaign_id: int,
    payload: PilotAttestationCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, *OPERATIONAL_ROLES)
    _reauthenticate(db, actor, payload.account_password)
    campaign = campaign_or_404(db, actor.organization_id, campaign_id)
    row, created = record_attestation(db, campaign, actor, payload)
    if created:
        add_audit(
            db,
            actor,
            "record_pilot_attestation",
            campaign.id,
            {
                "attestation_id": row.id,
                "attestation_type": row.attestation_type,
                "result": row.result,
                "evidence_fingerprint": row.evidence_fingerprint,
            },
        )
        db.commit()
    return campaign_read(db, campaign_or_404(db, actor.organization_id, campaign_id), actor)


@router.post("/campaigns/{campaign_id}/issues", response_model=PilotCampaignRead)
def create_pilot_issue(
    campaign_id: int,
    payload: PilotIssueCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, *OPERATIONAL_ROLES)
    campaign = campaign_or_404(db, actor.organization_id, campaign_id)
    if campaign.status not in {"active", "decision_pending"}:
        raise HTTPException(status_code=409, detail="Pilot issues require an active campaign")
    if actor.user_id is None:
        raise HTTPException(status_code=401, detail="Authenticated user required")
    now = datetime.utcnow()
    row = PilotIssue(
        organization_id=actor.organization_id,
        campaign_id=campaign.id,
        severity=payload.severity,
        title=payload.title,
        detail=payload.detail,
        status="open",
        version=0,
        reported_by=actor.user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    add_audit(
        db,
        actor,
        "create_pilot_issue",
        campaign.id,
        {"issue_id": row.id, "severity": row.severity, "status": row.status},
    )
    db.commit()
    return campaign_read(db, campaign, actor)


@router.post(
    "/campaigns/{campaign_id}/issues/{issue_id}/resolve",
    response_model=PilotCampaignRead,
)
def resolve_pilot_issue(
    campaign_id: int,
    issue_id: int,
    payload: PilotIssueResolve,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    _reauthenticate(db, actor, payload.account_password)
    campaign = campaign_or_404(db, actor.organization_id, campaign_id)
    row = db.scalar(
        select(PilotIssue)
        .where(
            PilotIssue.id == issue_id,
            PilotIssue.campaign_id == campaign.id,
            PilotIssue.organization_id == actor.organization_id,
        )
        .with_for_update()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Pilot issue not found")
    if row.status == "resolved":
        if row.resolved_by == actor.user_id and row.resolution_reason == payload.resolution_reason:
            return campaign_read(db, campaign, actor)
        raise HTTPException(status_code=409, detail="Pilot issue is already resolved")
    if row.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Pilot issue version changed")
    row.status = "resolved"
    row.version += 1
    row.resolved_by = actor.user_id
    row.resolution_reason = payload.resolution_reason
    row.resolved_at = datetime.utcnow()
    row.updated_at = row.resolved_at
    add_audit(
        db,
        actor,
        "resolve_pilot_issue",
        campaign.id,
        {"issue_id": row.id, "severity": row.severity, "new_version": row.version},
    )
    db.commit()
    return campaign_read(db, campaign, actor)


@router.post("/campaigns/{campaign_id}/decision", response_model=PilotCampaignRead)
def decide_pilot_campaign(
    campaign_id: int,
    payload: PilotDecisionCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    _reauthenticate(db, actor, payload.account_password)
    row = db.scalar(
        select(PilotCampaign)
        .where(
            PilotCampaign.id == campaign_id,
            PilotCampaign.organization_id == actor.organization_id,
        )
        .with_for_update()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Pilot campaign not found")
    if row.status in {"go", "no_go"}:
        if row.status == payload.decision and row.decision_by == actor.user_id and row.decision_reason == payload.reason:
            return campaign_read(db, row, actor)
        raise HTTPException(status_code=409, detail="Pilot decision is already final")
    if row.status != "decision_pending":
        raise HTTPException(status_code=409, detail="Pilot must be pending decision")
    if row.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Pilot campaign version changed")
    snapshot, fingerprint, go_ready = decision_snapshot(db, row, payload)
    now = datetime.utcnow()
    row.status = payload.decision
    row.version += 1
    row.updated_by = actor.user_id
    row.updated_at = now
    row.decision_by = actor.user_id
    row.decided_at = now
    row.decision_reason = payload.reason
    row.decision_snapshot_json = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    row.decision_fingerprint = fingerprint
    add_audit(
        db,
        actor,
        "decide_pilot_campaign",
        row.id,
        {
            "decision": row.status,
            "new_version": row.version,
            "go_ready": go_ready,
            "decision_fingerprint": fingerprint,
        },
    )
    db.commit()
    db.refresh(row)
    return campaign_read(db, row, actor)
