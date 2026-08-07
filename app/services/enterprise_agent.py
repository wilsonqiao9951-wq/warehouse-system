from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import re
import unicodedata

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    ExternalSyncLog,
    InventoryNotification,
    ReplenishmentRequest,
    WorkOrder,
)
from app.schemas import (
    EnterpriseAgentEvidenceRead,
    EnterpriseAgentFindingRead,
    EnterpriseAgentIntent,
)
from app.services.analytics import AnalyticsBundle, build_enterprise_analytics


@dataclass(frozen=True)
class EnterpriseAgentDraft:
    intent: EnterpriseAgentIntent
    summary: str
    priority: str
    confidence: float
    analytics: AnalyticsBundle
    findings: list[EnterpriseAgentFindingRead]
    tools_used: list[str]
    limitations: list[str]


_INTENT_TERMS: tuple[tuple[EnterpriseAgentIntent, tuple[str, ...]], ...] = (
    (
        "integration_health",
        (
            "integration",
            "webhook",
            "sync",
            "delivery",
            "api failure",
            "集成",
            "接口",
            "同步",
            "回调",
        ),
    ),
    (
        "inventory_risk",
        (
            "inventory",
            "stock",
            "part",
            "warehouse",
            "replenishment",
            "库存",
            "零件",
            "仓库",
            "缺货",
            "补货",
        ),
    ),
    (
        "service_quality",
        (
            "quality",
            "first time fix",
            "rework",
            "repair time",
            "service outcome",
            "质量",
            "一次修复",
            "返工",
            "维修时长",
        ),
    ),
    (
        "backlog_risk",
        (
            "backlog",
            "overdue",
            "open work",
            "open job",
            "queue",
            "积压",
            "逾期",
            "未完成",
            "工单风险",
        ),
    ),
)


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def resolve_enterprise_agent_intent(
    question: str,
    requested_intent: EnterpriseAgentIntent | None,
) -> EnterpriseAgentIntent:
    if requested_intent is not None:
        return requested_intent
    normalized = unicodedata.normalize("NFKC", question).casefold()
    normalized = re.sub(r"\s+", " ", normalized)
    for intent, terms in _INTENT_TERMS:
        if any(term in normalized for term in terms):
            return intent
    return "daily_brief"


def _evidence(
    code: str,
    label: str,
    value: int | float | str,
    unit: str,
    source: str,
    definition: str,
) -> EnterpriseAgentEvidenceRead:
    return EnterpriseAgentEvidenceRead(
        code=code,
        label=label,
        value=value,
        unit=unit,
        source=source,
        definition=definition,
    )


def _finding(
    code: str,
    severity: str,
    title: str,
    summary: str,
    recommendation: str,
    evidence: list[EnterpriseAgentEvidenceRead],
    *links: str,
) -> EnterpriseAgentFindingRead:
    return EnterpriseAgentFindingRead(
        code=code,
        severity=severity,
        title=title,
        summary=summary,
        recommendation=recommendation,
        evidence=evidence,
        links=list(links),
    )


def _kpi_map(analytics: AnalyticsBundle) -> dict[str, object]:
    return {item.code: item for item in analytics.dashboard.kpis}


def _dimension_conditions(
    organization_id: int,
    engineer_id: int | None,
    job_type: str | None,
) -> list[object]:
    conditions: list[object] = [WorkOrder.organization_id == organization_id]
    if engineer_id is not None:
        conditions.append(
            func.coalesce(
                WorkOrder.completed_by_id,
                WorkOrder.engineer_id,
                WorkOrder.assigned_user_id,
            )
            == engineer_id
        )
    if job_type:
        conditions.append(func.lower(WorkOrder.job_type) == job_type.casefold())
    return conditions


def _backlog_snapshot(
    db: Session,
    organization_id: int,
    *,
    to_date: date,
    engineer_id: int | None,
    job_type: str | None,
) -> dict[str, int]:
    period_end = datetime.combine(to_date + timedelta(days=1), time.min)
    conditions = [
        *_dimension_conditions(organization_id, engineer_id, job_type),
        WorkOrder.created_at < period_end,
        or_(WorkOrder.completed_at.is_(None), WorkOrder.completed_at >= period_end),
        func.lower(WorkOrder.status).notin_({"cancelled", "canceled"}),
    ]
    rows = list(db.scalars(select(WorkOrder).where(*conditions)).all())
    return {
        "backlog": len(rows),
        "aged_over_7_days": sum(
            1 for row in rows if row.created_at < period_end - timedelta(days=7)
        ),
        "overdue_schedule": sum(
            1 for row in rows if row.schedule_date is not None and row.schedule_date <= to_date
        ),
        "currently_unclaimed": sum(1 for row in rows if row.claimed_by_id is None),
        "currently_paused": sum(1 for row in rows if row.status.casefold() == "paused"),
    }


def _inventory_snapshot(
    db: Session,
    organization_id: int,
    analytics: AnalyticsBundle,
) -> dict[str, int | float]:
    active_replenishment_statuses = {"requested", "picking", "shipped", "received"}
    return {
        "low_stock_skus": sum(
            region.low_stock_sku_count for region in analytics.dashboard.regions
        ),
        "stock_value": round(
            sum(region.stock_value for region in analytics.dashboard.regions), 2
        ),
        "open_notifications": int(
            db.scalar(
                select(func.count(InventoryNotification.id)).where(
                    InventoryNotification.organization_id == organization_id,
                    InventoryNotification.status == "open",
                )
            )
            or 0
        ),
        "active_replenishments": int(
            db.scalar(
                select(func.count(ReplenishmentRequest.id)).where(
                    ReplenishmentRequest.organization_id == organization_id,
                    ReplenishmentRequest.status.in_(active_replenishment_statuses),
                )
            )
            or 0
        ),
        "reconciliation_required": int(
            db.scalar(
                select(func.count(ReplenishmentRequest.id)).where(
                    ReplenishmentRequest.organization_id == organization_id,
                    ReplenishmentRequest.requires_reconciliation.is_(True),
                )
            )
            or 0
        ),
    }


def _integration_snapshot(db: Session, organization_id: int) -> dict[str, int]:
    stale_cutoff = _utcnow_naive() - timedelta(
        minutes=max(1, settings.operations_stale_processing_minutes)
    )
    base = (
        ExternalSyncLog.organization_id == organization_id,
        ExternalSyncLog.direction == "outbound",
    )
    return {
        "failed": int(
            db.scalar(
                select(func.count(ExternalSyncLog.id)).where(
                    *base,
                    ExternalSyncLog.status == "failed",
                )
            )
            or 0
        ),
        "pending": int(
            db.scalar(
                select(func.count(ExternalSyncLog.id)).where(
                    *base,
                    ExternalSyncLog.status == "pending",
                )
            )
            or 0
        ),
        "stale_processing": int(
            db.scalar(
                select(func.count(ExternalSyncLog.id)).where(
                    *base,
                    ExternalSyncLog.status == "processing",
                    ExternalSyncLog.updated_at < stale_cutoff,
                )
            )
            or 0
        ),
    }


def _throughput_finding(analytics: AnalyticsBundle) -> EnterpriseAgentFindingRead:
    kpis = _kpi_map(analytics)
    created = kpis["work_orders_created"]
    completed = kpis["completed_work_orders"]
    contribution = kpis["gross_contribution"]
    return _finding(
        "period_throughput",
        "info",
        "Selected-period throughput",
        f"{int(completed.value or 0)} work orders completed from {int(created.value or 0)} created in the selected period.",
        "Use the Analytics workspace to drill into engineer and job-type outcomes before changing staffing or scheduling.",
        [
            _evidence(
                "work_orders_created",
                "Created",
                int(created.value or 0),
                "work_orders",
                "work_orders.created_at",
                created.definition,
            ),
            _evidence(
                "completed_work_orders",
                "Completed",
                int(completed.value or 0),
                "work_orders",
                "work_orders.completed_at",
                completed.definition,
            ),
            _evidence(
                "gross_contribution",
                "Gross contribution",
                round(float(contribution.value or 0), 2),
                "currency",
                "work_orders + work_order_parts",
                contribution.definition,
            ),
        ],
        "/analytics",
    )


def _backlog_finding(snapshot: dict[str, int]) -> EnterpriseAgentFindingRead:
    backlog = snapshot["backlog"]
    aged = snapshot["aged_over_7_days"]
    overdue = snapshot["overdue_schedule"]
    severity = "critical" if overdue >= 5 or aged >= 10 else "warning" if backlog else "info"
    summary = (
        f"Period-end backlog is {backlog}; {aged} were older than seven days and "
        f"{overdue} had reached their scheduled date."
    )
    recommendation = (
        "Review overdue and aged work orders, then assign or reschedule through the normal owner-controlled work-order workflow."
        if backlog
        else "No period-end backlog exception is visible for the selected filters."
    )
    return _finding(
        "backlog_exposure",
        severity,
        "Backlog exposure",
        summary,
        recommendation,
        [
            _evidence(
                "period_end_backlog",
                "Backlog",
                backlog,
                "work_orders",
                "work_orders",
                "Created before period end and not completed by period end; currently cancelled rows are excluded.",
            ),
            _evidence(
                "aged_over_7_days",
                "Older than seven days",
                aged,
                "work_orders",
                "work_orders.created_at",
                "Backlog work orders created more than seven days before the selected period end.",
            ),
            _evidence(
                "overdue_schedule",
                "Scheduled date reached",
                overdue,
                "work_orders",
                "work_orders.schedule_date",
                "Backlog work orders with schedule_date on or before the selected period end date.",
            ),
            _evidence(
                "currently_unclaimed",
                "Currently unclaimed",
                snapshot["currently_unclaimed"],
                "work_orders",
                "work_orders.claimed_by_id",
                "Current claim state among rows in the period-end backlog set; historical claim snapshots are unavailable.",
            ),
        ],
        "/work-orders",
    )


def _quality_findings(analytics: AnalyticsBundle) -> list[EnterpriseAgentFindingRead]:
    kpis = _kpi_map(analytics)
    ftf = kpis["first_time_fix_rate"]
    rework = kpis["rework_rate"]
    duration = kpis["average_repair_hours"]
    ftf_value = float(ftf.value) if ftf.value is not None else None
    rework_value = float(rework.value or 0)
    if rework_value >= 25 or (ftf_value is not None and ftf_value < 65):
        severity = "critical"
    elif rework_value >= 15 or (ftf_value is not None and ftf_value < 80):
        severity = "warning"
    else:
        severity = "info"
    evidence = [
        _evidence(
            "first_time_fix_rate",
            "First-time-fix rate",
            round(ftf_value, 1) if ftf_value is not None else "not available",
            "percent",
            "work_orders.first_time_fix",
            ftf.definition,
        ),
        _evidence(
            "rework_rate",
            "Rework rate",
            round(rework_value, 1),
            "percent",
            "work_orders.is_rework",
            rework.definition,
        ),
        _evidence(
            "average_repair_hours",
            "Average repair hours",
            round(float(duration.value), 1) if duration.value is not None else "not available",
            "hours",
            "work_orders.repair_duration_minutes",
            duration.definition,
        ),
    ]
    findings = [
        _finding(
            "service_outcomes",
            severity,
            "Service outcome quality",
            (
                f"First-time-fix is {ftf_value:.1f}% and rework is {rework_value:.1f}%."
                if ftf_value is not None
                else f"First-time-fix is not yet measurable; rework is {rework_value:.1f}%."
            ),
            "Inspect the job-type and engineer evidence, then improve forms, knowledge, or coaching without editing locked completion records.",
            evidence,
            "/analytics",
            "/knowledge-base",
        )
    ]
    quality = analytics.dashboard.data_quality
    if quality.warnings:
        findings.append(
            _finding(
                "evidence_coverage",
                "warning",
                "Evidence coverage limits confidence",
                " ".join(quality.warnings),
                "Increase completion-field coverage before treating rate differences as conclusive.",
                [
                    _evidence(
                        "first_time_fix_coverage",
                        "First-time-fix coverage",
                        round(quality.first_time_fix_coverage * 100, 1),
                        "percent",
                        "work_orders.first_time_fix",
                        "Completed work orders with an explicit first-time-fix label.",
                    ),
                    _evidence(
                        "repair_duration_coverage",
                        "Repair-duration coverage",
                        round(quality.repair_duration_coverage * 100, 1),
                        "percent",
                        "work_orders.repair_duration_minutes",
                        "Completed work orders with server-recorded repair duration.",
                    ),
                ],
                "/analytics",
            )
        )
    return findings


def _inventory_finding(snapshot: dict[str, int | float]) -> EnterpriseAgentFindingRead:
    low_stock = int(snapshot["low_stock_skus"])
    reconciliation = int(snapshot["reconciliation_required"])
    severity = "critical" if reconciliation or low_stock >= 10 else "warning" if low_stock else "info"
    return _finding(
        "inventory_readiness",
        severity,
        "Inventory readiness",
        (
            f"{low_stock} warehouse-SKU balances are at or below threshold, "
            f"{int(snapshot['open_notifications'])} notifications are open, and "
            f"{reconciliation} replenishment records require administrator reconciliation."
        ),
        (
            "Review alerts and advance stock only through the existing approval, warehouse-custody, and engineer-receipt workflows."
            if low_stock or reconciliation
            else "No current low-stock or reconciliation exception is visible."
        ),
        [
            _evidence(
                "low_stock_skus",
                "Low-stock warehouse-SKUs",
                low_stock,
                "warehouse_sku_balances",
                "inventory_transactions + parts",
                "Current ledger balance at or below the part's configured minimum/safety threshold for each warehouse.",
            ),
            _evidence(
                "open_notifications",
                "Open inventory notifications",
                int(snapshot["open_notifications"]),
                "notifications",
                "inventory_notifications",
                "Current inventory notifications with status=open.",
            ),
            _evidence(
                "active_replenishments",
                "Active replenishments",
                int(snapshot["active_replenishments"]),
                "requests",
                "replenishment_requests",
                "Requests in requested, picking, shipped, or received state.",
            ),
            _evidence(
                "stock_value",
                "Current stock value",
                float(snapshot["stock_value"]),
                "currency",
                "inventory_transactions + parts",
                "Current ledger quantity multiplied by each part's current default cost.",
            ),
        ],
        "/regions",
        "/warehouse-tasks",
    )


def _integration_finding(snapshot: dict[str, int]) -> EnterpriseAgentFindingRead:
    severity = (
        "critical"
        if snapshot["failed"] or snapshot["stale_processing"]
        else "warning"
        if snapshot["pending"]
        else "info"
    )
    return _finding(
        "integration_delivery_health",
        severity,
        "Integration delivery health",
        (
            f"Outbound delivery has {snapshot['failed']} failed, {snapshot['pending']} pending, "
            f"and {snapshot['stale_processing']} stale-processing event(s)."
        ),
        (
            "Inspect delivery logs and use the authenticated integration retry workflow for failed events."
            if severity != "info"
            else "No current outbound-delivery exception is visible."
        ),
        [
            _evidence(
                "failed_outbound",
                "Failed outbound events",
                snapshot["failed"],
                "events",
                "external_sync_logs",
                "Outbound synchronization logs with status=failed.",
            ),
            _evidence(
                "pending_outbound",
                "Pending outbound events",
                snapshot["pending"],
                "events",
                "external_sync_logs",
                "Outbound synchronization logs with status=pending.",
            ),
            _evidence(
                "stale_processing",
                "Stale processing events",
                snapshot["stale_processing"],
                "events",
                "external_sync_logs",
                "Outbound processing rows older than the configured operations threshold.",
            ),
        ],
        "/integrations",
    )


def _priority(findings: list[EnterpriseAgentFindingRead]) -> str:
    severities = {item.severity for item in findings}
    if "critical" in severities:
        return "critical"
    if "warning" in severities:
        return "warning"
    return "normal"


def build_enterprise_agent_draft(
    db: Session,
    organization_id: int,
    *,
    question: str,
    requested_intent: EnterpriseAgentIntent | None,
    from_date: date,
    to_date: date,
    engineer_id: int | None,
    job_type: str | None,
) -> EnterpriseAgentDraft:
    intent = resolve_enterprise_agent_intent(question, requested_intent)
    analytics = build_enterprise_analytics(
        db,
        organization_id,
        from_date=from_date,
        to_date=to_date,
        engineer_id=engineer_id,
        job_type=job_type,
    )
    findings: list[EnterpriseAgentFindingRead] = []
    tools_used = ["enterprise_analytics"]

    if intent == "daily_brief":
        findings.append(_throughput_finding(analytics))
        backlog = _backlog_snapshot(
            db,
            organization_id,
            to_date=to_date,
            engineer_id=engineer_id,
            job_type=job_type,
        )
        findings.append(_backlog_finding(backlog))
        findings.extend(_quality_findings(analytics))
        findings.append(_inventory_finding(_inventory_snapshot(db, organization_id, analytics)))
        findings.append(_integration_finding(_integration_snapshot(db, organization_id)))
        tools_used.extend(
            ["work_order_backlog", "inventory_readiness", "integration_delivery"]
        )
    elif intent == "backlog_risk":
        findings.append(
            _backlog_finding(
                _backlog_snapshot(
                    db,
                    organization_id,
                    to_date=to_date,
                    engineer_id=engineer_id,
                    job_type=job_type,
                )
            )
        )
        tools_used.append("work_order_backlog")
    elif intent == "service_quality":
        findings.extend(_quality_findings(analytics))
    elif intent == "inventory_risk":
        findings.append(_inventory_finding(_inventory_snapshot(db, organization_id, analytics)))
        tools_used.append("inventory_readiness")
    else:
        findings.append(_integration_finding(_integration_snapshot(db, organization_id)))
        tools_used.append("integration_delivery")

    severity_order = {"critical": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda item: (severity_order[item.severity], item.code))
    priority = _priority(findings)
    critical_count = sum(item.severity == "critical" for item in findings)
    warning_count = sum(item.severity == "warning" for item in findings)
    summary = (
        f"Evidence review resolved to {intent.replace('_', ' ')} with "
        f"{critical_count} critical and {warning_count} warning finding(s)."
    )
    quality = analytics.dashboard.data_quality
    if intent in {"daily_brief", "service_quality"} and quality.completed_work_orders:
        confidence = min(
            quality.first_time_fix_coverage,
            quality.repair_duration_coverage,
            quality.engineer_attribution_coverage,
        )
    else:
        confidence = 0.95
    limitations = [
        "The agent is read-only and cannot claim, edit, complete, transfer, approve, retry, or reconcile records.",
        "Recommendations are deterministic rules over recorded source data; no external language model was called.",
        "Current inventory and delivery state are live snapshots, not historical period-end snapshots.",
        "Historical cancellation and claim-state snapshots are unavailable; related backlog evidence uses current recorded state.",
    ]
    return EnterpriseAgentDraft(
        intent=intent,
        summary=summary,
        priority=priority,
        confidence=round(max(0.0, min(1.0, confidence)), 3),
        analytics=analytics,
        findings=findings,
        tools_used=tools_used,
        limitations=limitations,
    )
