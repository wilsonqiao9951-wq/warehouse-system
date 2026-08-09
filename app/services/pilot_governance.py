from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.rbac import Actor
from app.models import (
    AuditLog,
    ExternalIntegration,
    IntegrationParallelReconciliation,
    IntegrationParityContract,
    PilotAttestation,
    PilotCampaign,
    PilotIssue,
    UserRole,
)
from app.schemas import (
    PilotAttestationCreate,
    PilotAttestationRead,
    PilotCampaignRead,
    PilotDecisionCreate,
    PilotIssueRead,
)


PILOT_REQUIRED_ITEMS: dict[str, dict[str, list[str]]] = {
    "admin": {
        "training": [
            "secure_login",
            "tenant_permissions",
            "backup_restore",
            "integration_parallel_run",
            "incident_rollback",
        ],
        "uat": [
            "role_denials",
            "tenant_isolation",
            "authentication_recovery",
            "audit_evidence",
            "parallel_run_matched",
        ],
    },
    "manager": {
        "training": [
            "secure_login",
            "dispatch_read_scope",
            "exception_review",
            "pilot_monitoring",
            "audit_escalation",
        ],
        "uat": [
            "dispatch_filters",
            "shared_progress_review",
            "profit_reporting",
            "abnormal_usage_review",
            "completion_quality_review",
        ],
    },
    "warehouse": {
        "training": [
            "secure_login",
            "inventory_custody",
            "transfer_workflow",
            "low_stock_review",
            "reconciliation",
        ],
        "uat": [
            "pick_ship_receive",
            "vehicle_transfer",
            "inventory_count",
            "location_scan",
            "ledger_reconciliation",
        ],
    },
    "engineer": {
        "training": [
            "secure_login",
            "claim_bound_device",
            "work_order_execution",
            "parts_and_evidence",
            "completion_reauthentication",
            "offline_boundaries",
        ],
        "uat": [
            "shared_visibility_read_only",
            "owner_device_write",
            "start_pause_complete",
            "parts_usage",
            "qc_signature",
            "post_completion_lock",
        ],
    },
}


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _fingerprint(payload: object) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def campaign_or_404(db: Session, organization_id: int, campaign_id: int) -> PilotCampaign:
    row = db.scalar(
        select(PilotCampaign).where(
            PilotCampaign.id == campaign_id,
            PilotCampaign.organization_id == organization_id,
        )
    )
    if not row:
        raise HTTPException(status_code=404, detail="Pilot campaign not found")
    return row


def attestation_read(row: PilotAttestation) -> PilotAttestationRead:
    return PilotAttestationRead(
        id=row.id,
        campaign_id=row.campaign_id,
        user_id=row.user_id,
        role=row.role,
        attestation_type=row.attestation_type,
        result=row.result,
        completed_items=json.loads(row.completed_items_json),
        required_items=PILOT_REQUIRED_ITEMS[row.role][row.attestation_type],
        evidence_fingerprint=row.evidence_fingerprint,
        note=row.note,
        created_at=row.created_at,
    )


def issue_read(row: PilotIssue) -> PilotIssueRead:
    return PilotIssueRead(
        id=row.id,
        campaign_id=row.campaign_id,
        severity=row.severity,
        title=row.title,
        detail=row.detail,
        status=row.status,
        version=row.version,
        reported_by=row.reported_by,
        resolved_by=row.resolved_by,
        resolution_reason=row.resolution_reason,
        resolved_at=row.resolved_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _latest_attestations(
    db: Session,
    campaign: PilotCampaign,
) -> list[PilotAttestation]:
    rows = db.scalars(
        select(PilotAttestation)
        .where(
            PilotAttestation.organization_id == campaign.organization_id,
            PilotAttestation.campaign_id == campaign.id,
        )
        .order_by(PilotAttestation.created_at.desc(), PilotAttestation.id.desc())
    ).all()
    latest: dict[tuple[int, str], PilotAttestation] = {}
    for row in rows:
        latest.setdefault((row.user_id, row.attestation_type), row)
    return list(latest.values())


def _campaign_evidence(
    db: Session,
    campaign: PilotCampaign,
) -> tuple[list[PilotAttestation], list[PilotIssue], dict[str, bool], list[str], IntegrationParallelReconciliation | None]:
    attestations = _latest_attestations(db, campaign)
    issues = db.scalars(
        select(PilotIssue)
        .where(
            PilotIssue.organization_id == campaign.organization_id,
            PilotIssue.campaign_id == campaign.id,
        )
        .order_by(PilotIssue.created_at.desc(), PilotIssue.id.desc())
    ).all()
    reconciliation_query = select(IntegrationParallelReconciliation).where(
        IntegrationParallelReconciliation.organization_id == campaign.organization_id
    )
    if campaign.started_at is not None:
        reconciliation_query = reconciliation_query.where(
            IntegrationParallelReconciliation.created_at >= campaign.started_at
        )
    latest_reconciliation = db.scalar(
        reconciliation_query
        .order_by(
            IntegrationParallelReconciliation.created_at.desc(),
            IntegrationParallelReconciliation.id.desc(),
        )
        .limit(1)
    )
    gates: dict[str, bool] = {}
    for role in PILOT_REQUIRED_ITEMS:
        for attestation_type in ("training", "uat"):
            gates[f"{role}_{attestation_type}"] = any(
                row.role == role
                and row.attestation_type == attestation_type
                and row.result == "passed"
                for row in attestations
            )
    gates["no_open_sev1"] = not any(
        issue.status == "open" and issue.severity == "sev1" for issue in issues
    )
    current_contract = None
    current_integration = None
    if latest_reconciliation:
        current_contract = db.scalar(
            select(IntegrationParityContract).where(
                IntegrationParityContract.id == latest_reconciliation.contract_id,
                IntegrationParityContract.organization_id == campaign.organization_id,
            )
        )
        current_integration = db.scalar(
            select(ExternalIntegration).where(
                ExternalIntegration.id == latest_reconciliation.integration_id,
                ExternalIntegration.organization_id == campaign.organization_id,
            )
        )
    gates["parallel_run_matched"] = bool(
        latest_reconciliation
        and latest_reconciliation.status == "matched"
        and current_contract
        and current_contract.readiness_status == "ready"
        and current_contract.source_revision == latest_reconciliation.source_revision
        and current_contract.source_fingerprint == latest_reconciliation.contract_fingerprint
        and current_integration
        and current_integration.is_active
        and current_integration.provider in {"appsheet", "google_sheets"}
    )
    gate_reasons = [
        f"Missing passed {key.replace('_', ' ')} attestation."
        for key, ready in gates.items()
        if key not in {"no_open_sev1", "parallel_run_matched"} and not ready
    ]
    if not gates["no_open_sev1"]:
        gate_reasons.append("One or more severity-1 pilot issues remain open.")
    if not gates["parallel_run_matched"]:
        gate_reasons.append(
            "The latest tenant parallel reconciliation is not matched against the current ready contract."
        )
    gates["go_ready"] = not gate_reasons
    return attestations, issues, gates, gate_reasons, latest_reconciliation


def campaign_read(db: Session, campaign: PilotCampaign, actor: Actor) -> PilotCampaignRead:
    attestations, issues, gates, gate_reasons, reconciliation = _campaign_evidence(db, campaign)
    manager = actor.role in {UserRole.ADMIN, UserRole.MANAGER}
    operational_role = actor.role.value in PILOT_REQUIRED_ITEMS
    visible_attestations = (
        attestations
        if manager
        else [row for row in attestations if row.user_id == actor.user_id]
    )
    visible_issues = issues if manager else [row for row in issues if row.reported_by == actor.user_id]
    return PilotCampaignRead(
        id=campaign.id,
        organization_id=campaign.organization_id,
        name=campaign.name,
        planned_start=campaign.planned_start,
        planned_end=campaign.planned_end,
        status=campaign.status,
        version=campaign.version,
        started_at=campaign.started_at,
        decision_by=campaign.decision_by,
        decided_at=campaign.decided_at,
        decision_reason=campaign.decision_reason,
        decision_fingerprint=campaign.decision_fingerprint,
        created_by=campaign.created_by,
        updated_by=campaign.updated_by,
        created_at=campaign.created_at,
        updated_at=campaign.updated_at,
        required_items=PILOT_REQUIRED_ITEMS,
        latest_attestations=[attestation_read(row) for row in visible_attestations],
        issues=[issue_read(row) for row in visible_issues],
        gates=gates,
        gate_reasons=gate_reasons,
        latest_reconciliation_id=reconciliation.id if reconciliation else None,
        latest_reconciliation_status=reconciliation.status if reconciliation else None,
        can_manage=manager and campaign.status not in {"go", "no_go"},
        can_attest=operational_role and campaign.status in {"active", "decision_pending"},
        can_resolve_issues=manager and campaign.status in {"active", "decision_pending"},
        can_decide=actor.role == UserRole.ADMIN and campaign.status == "decision_pending",
    )


def record_attestation(
    db: Session,
    campaign: PilotCampaign,
    actor: Actor,
    payload: PilotAttestationCreate,
) -> tuple[PilotAttestation, bool]:
    if campaign.status not in {"active", "decision_pending"}:
        raise HTTPException(status_code=409, detail="Pilot attestations require an active campaign")
    role = actor.role.value
    if role not in PILOT_REQUIRED_ITEMS or actor.user_id is None:
        raise HTTPException(status_code=403, detail="This account cannot attest pilot evidence")
    required = set(PILOT_REQUIRED_ITEMS[role][payload.attestation_type])
    completed = set(payload.completed_items)
    if not completed.issubset(required):
        raise HTTPException(status_code=422, detail="Attestation contains unknown checklist items")
    if payload.result == "passed" and completed != required:
        raise HTTPException(status_code=422, detail="Every required checklist item must be completed to pass")
    evidence_payload = {
        "campaign_id": campaign.id,
        "user_id": actor.user_id,
        "role": role,
        "attestation_type": payload.attestation_type,
        "result": payload.result,
        "completed_items": sorted(completed),
        "note": payload.note,
    }
    evidence_fingerprint = _fingerprint(evidence_payload)
    existing = db.scalar(
        select(PilotAttestation).where(
            PilotAttestation.organization_id == campaign.organization_id,
            PilotAttestation.campaign_id == campaign.id,
            PilotAttestation.user_id == actor.user_id,
            PilotAttestation.attestation_type == payload.attestation_type,
            PilotAttestation.evidence_fingerprint == evidence_fingerprint,
        )
    )
    if existing:
        return existing, False
    row = PilotAttestation(
        organization_id=campaign.organization_id,
        campaign_id=campaign.id,
        user_id=actor.user_id,
        role=role,
        attestation_type=payload.attestation_type,
        result=payload.result,
        completed_items_json=_canonical_json(sorted(completed)),
        evidence_fingerprint=evidence_fingerprint,
        note=payload.note,
        created_at=datetime.utcnow(),
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(PilotAttestation).where(
                PilotAttestation.organization_id == campaign.organization_id,
                PilotAttestation.campaign_id == campaign.id,
                PilotAttestation.user_id == actor.user_id,
                PilotAttestation.attestation_type == payload.attestation_type,
                PilotAttestation.evidence_fingerprint == evidence_fingerprint,
            )
        )
        if existing:
            return existing, False
        raise
    return row, True


def decision_snapshot(
    db: Session,
    campaign: PilotCampaign,
    payload: PilotDecisionCreate,
) -> tuple[dict, str, bool]:
    attestations, issues, gates, gate_reasons, reconciliation = _campaign_evidence(db, campaign)
    if payload.decision == "go" and not gates["go_ready"]:
        raise HTTPException(status_code=409, detail={"message": "Pilot is not ready for Go", "reasons": gate_reasons})
    snapshot = {
        "campaign_id": campaign.id,
        "campaign_version": campaign.version,
        "decision": payload.decision,
        "gates": gates,
        "attestations": sorted([
            {
                "id": row.id,
                "user_id": row.user_id,
                "role": row.role,
                "type": row.attestation_type,
                "result": row.result,
                "fingerprint": row.evidence_fingerprint,
            }
            for row in attestations
        ], key=lambda item: item["id"]),
        "open_issue_counts": {
            severity: sum(1 for row in issues if row.status == "open" and row.severity == severity)
            for severity in ("sev1", "sev2", "sev3")
        },
        "latest_reconciliation_id": reconciliation.id if reconciliation else None,
        "latest_reconciliation_status": reconciliation.status if reconciliation else None,
    }
    return snapshot, _fingerprint(snapshot), gates["go_ready"]


def add_audit(
    db: Session,
    actor: Actor,
    action: str,
    campaign_id: int,
    metadata: dict,
) -> None:
    db.add(
        AuditLog(
            organization_id=actor.organization_id,
            user_id=actor.user_id,
            action=action,
            entity_type="pilot_campaign",
            entity_id=campaign_id,
            metadata_json=_canonical_json({"actor_role": actor.role.value, **metadata}),
            timestamp=datetime.utcnow(),
        )
    )


def open_issue_count(db: Session, campaign: PilotCampaign) -> int:
    return db.scalar(
        select(func.count(PilotIssue.id)).where(
            PilotIssue.organization_id == campaign.organization_id,
            PilotIssue.campaign_id == campaign.id,
            PilotIssue.status == "open",
        )
    ) or 0
