from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.operations import utc_iso
from app.models import (
    ExternalSyncLog,
    Organization,
    OrganizationDataExport,
    OrganizationDataRestore,
    SubscriptionNotice,
    WorkerLease,
)


def collect_platform_operations_risks(
    db: Session,
    *,
    snapshot: dict,
    schema_ready: bool,
    now: datetime,
) -> dict:
    """Collect aggregate platform risk without returning tenant records."""
    leases = {row.name: row for row in db.scalars(select(WorkerLease)).all()}
    for worker in snapshot["workers"]:
        lease = leases.get(worker["name"])
        worker.update(
            lease_generation=lease.generation if lease else None,
            lease_expires_at=utc_iso(lease.lease_expires_at) if lease else None,
            next_run_at=utc_iso(lease.next_run_at) if lease else None,
            run_started_at=utc_iso(lease.run_started_at) if lease else None,
        )

    pending_conditions = (
        ExternalSyncLog.direction == "outbound",
        ExternalSyncLog.status == "pending",
    )
    outbound_pending = db.scalar(
        select(func.count(ExternalSyncLog.id)).where(*pending_conditions)
    ) or 0
    outbound_due = db.scalar(
        select(func.count(ExternalSyncLog.id)).where(
            *pending_conditions,
            or_(
                ExternalSyncLog.next_retry_at.is_(None),
                ExternalSyncLog.next_retry_at <= now,
            ),
        )
    ) or 0
    outbound_failed = db.scalar(
        select(func.count(ExternalSyncLog.id)).where(
            ExternalSyncLog.direction == "outbound",
            ExternalSyncLog.status == "failed",
        )
    ) or 0
    stale_cutoff = now - timedelta(
        minutes=max(1, settings.operations_stale_processing_minutes)
    )
    stale_processing = db.scalar(
        select(func.count(ExternalSyncLog.id)).where(
            ExternalSyncLog.direction == "outbound",
            ExternalSyncLog.status == "processing",
            ExternalSyncLog.updated_at < stale_cutoff,
        )
    ) or 0

    critical_notices = db.scalar(
        select(func.count(SubscriptionNotice.id)).where(
            SubscriptionNotice.status == "open",
            SubscriptionNotice.severity == "critical",
        )
    ) or 0
    active_organizations = db.scalar(
        select(func.count(Organization.id)).where(Organization.is_active.is_(True))
    ) or 0
    latest_exports = (
        select(
            OrganizationDataExport.organization_id.label("organization_id"),
            func.max(OrganizationDataExport.generated_at).label("latest_generated_at"),
        )
        .group_by(OrganizationDataExport.organization_id)
        .subquery()
    )
    backup_cutoff = now - timedelta(
        days=max(1, settings.operations_backup_warning_days)
    )
    organizations_without_recent_backup = db.scalar(
        select(func.count(Organization.id))
        .outerjoin(
            latest_exports,
            latest_exports.c.organization_id == Organization.id,
        )
        .where(
            Organization.is_active.is_(True),
            or_(
                latest_exports.c.latest_generated_at.is_(None),
                latest_exports.c.latest_generated_at < backup_cutoff,
            ),
        )
    ) or 0
    restore_plans_with_conflicts = db.scalar(
        select(func.count(OrganizationDataRestore.id)).where(
            OrganizationDataRestore.status.in_(["validated", "approved"]),
            or_(
                OrganizationDataRestore.conflict_count > 0,
                OrganizationDataRestore.file_conflict_count > 0,
            ),
        )
    ) or 0

    alerts: list[dict] = []

    def alert(severity: str, code: str, message: str, count: int) -> None:
        if count > 0:
            alerts.append(
                {
                    "severity": severity,
                    "code": code,
                    "message": message,
                    "count": count,
                }
            )

    alert("warning", "outbound_delivery_due", "Outbound webhook deliveries are due.", outbound_due)
    alert(
        "critical",
        "outbound_delivery_failed",
        "Outbound webhook deliveries require manual retry.",
        outbound_failed,
    )
    alert(
        "critical",
        "outbound_delivery_stale",
        "Outbound webhook deliveries are stuck in processing.",
        stale_processing,
    )
    alert(
        "critical",
        "billing_notice_critical",
        "Critical subscription notices are open.",
        critical_notices,
    )
    alert(
        "warning",
        "backup_overdue",
        "Active organizations have no backup in the last "
        f"{max(1, settings.operations_backup_warning_days)} days.",
        organizations_without_recent_backup,
    )
    alert(
        "warning",
        "restore_conflict",
        "Restore plans have unresolved record or media conflicts.",
        restore_plans_with_conflicts,
    )
    for worker in snapshot["workers"]:
        if worker["enabled"] and worker["status"] in {"error", "stale"}:
            alert(
                "critical" if worker["status"] == "stale" else "warning",
                f"worker_{worker['name']}_{worker['status']}",
                f"Background worker {worker['name']} is {worker['status']}.",
                1,
            )
    request_metrics = snapshot["requests"]
    if request_metrics["total"] >= 20 and request_metrics["server_error_rate"] >= 0.05:
        alert(
            "critical",
            "request_error_rate",
            "Five-minute server error rate is at least 5%.",
            request_metrics["server_errors"],
        )
    if (
        request_metrics["total"] >= 5
        and request_metrics["p95_duration_ms"]
        > max(1, settings.operations_slow_request_ms)
    ):
        alert(
            "warning",
            "request_latency",
            "Five-minute p95 request latency exceeds the configured threshold.",
            1,
        )
    if not schema_ready:
        alert(
            "critical",
            "schema_not_ready",
            "Application schema readiness has been lost.",
            1,
        )

    return {
        "integration_queue": {
            "outbound_pending": outbound_pending,
            "outbound_due": outbound_due,
            "outbound_failed": outbound_failed,
            "stale_processing": stale_processing,
        },
        "open_critical_billing_notices": critical_notices,
        "data_protection": {
            "active_organizations": active_organizations,
            "organizations_without_recent_backup": organizations_without_recent_backup,
            "backup_warning_days": max(1, settings.operations_backup_warning_days),
            "restore_plans_with_conflicts": restore_plans_with_conflicts,
        },
        "alerts": alerts,
    }
