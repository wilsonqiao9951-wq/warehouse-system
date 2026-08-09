from __future__ import annotations

from datetime import timedelta
import json
from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db, set_platform_database_scope
from app.core.operations import operations_monitor, utc_iso, utcnow_naive
from app.core.rbac import Actor, get_current_actor, require_platform_admin
from app.core.security import verify_password
from app.models import (
    AuditLog,
    ExternalSyncLog,
    OperationsAlertDelivery,
    OperationsAlertIncident,
    User,
)
from app.schemas import (
    OperationsAlertAction,
    OperationsAlertDeliveryRead,
    OperationsAlertRetryAction,
    OperationsAlertingRead,
    OperationsStaleDeliveryRecovery,
    OperationsStaleDeliveryRecoveryRead,
    PlatformOperationsHistoryRead,
    PlatformOperationsSummaryRead,
)
from app.services.operations_history import aggregate_operations_history
from app.services.operations_alerts import (
    alert_destination_host,
    enqueue_operations_alert_test,
    operations_alert_configuration_errors,
)
from app.services.operations_risks import collect_platform_operations_risks


router = APIRouter(tags=["operations"])


def _worker_health(snapshot: dict) -> str:
    statuses = {
        row["status"]
        for row in snapshot["workers"]
        if row["enabled"]
    }
    return "degraded" if statuses.intersection({"error", "stale"}) else "ok"


def _require_platform_reauthentication(
    db: Session,
    actor: Actor,
    password: str,
) -> None:
    if actor.auth_method == "test":
        return
    if actor.auth_method not in {"bearer", "cookie"} or actor.user_id is None:
        raise HTTPException(status_code=401, detail="Authenticated session required")
    user = db.get(User, actor.user_id)
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(
            status_code=401,
            detail="Account password verification failed",
        )


def _operations_alert_delivery_read(row: OperationsAlertDelivery) -> dict:
    return {
        "id": row.id,
        "incident_id": row.incident_id,
        "event_type": row.event_type,
        "idempotency_key": row.idempotency_key,
        "request_hash": row.request_hash,
        "status": row.status,
        "attempt_count": row.attempt_count,
        "response_status_code": row.response_status_code,
        "failure_code": row.failure_code,
        "next_attempt_at": row.next_attempt_at,
        "last_attempt_at": row.last_attempt_at,
        "sent_at": row.sent_at,
        "version": row.version,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _operations_alert_incident_read(row: OperationsAlertIncident) -> dict:
    return {
        "id": row.id,
        "alert_code": row.alert_code,
        "severity": row.severity,
        "message": row.message,
        "status": row.status,
        "current_count": row.current_count,
        "peak_count": row.peak_count,
        "observation_count": row.observation_count,
        "opened_at": row.opened_at,
        "last_observed_at": row.last_observed_at,
        "resolved_at": row.resolved_at,
        "version": row.version,
    }


@router.get("/health/live")
def liveness(response: Response):
    snapshot = operations_monitor.snapshot(
        window_seconds=settings.operations_request_window_seconds
    )
    response.headers["Cache-Control"] = "no-store"
    return {
        "status": "alive",
        "checked_at": snapshot["checked_at"],
        "uptime_seconds": snapshot["uptime_seconds"],
    }


@router.get("/health/ready")
def readiness(
    request: Request,
    db: Session = Depends(get_db),
):
    database_status = "ok"
    try:
        db.scalar(text("SELECT 1"))
    except Exception:
        database_status = "error"
        db.rollback()
    schema_status = "ok" if getattr(request.app.state, "schema_ready", False) else "error"
    snapshot = operations_monitor.snapshot(
        window_seconds=settings.operations_request_window_seconds
    )
    core_ready = database_status == "ok" and schema_status == "ok"
    return JSONResponse(
        status_code=200 if core_ready else 503,
        content={
            "status": "ready" if core_ready else "not_ready",
            "checked_at": snapshot["checked_at"],
            "database": database_status,
            "schema": schema_status,
            "workers": _worker_health(snapshot),
        },
        headers={"Cache-Control": "no-store"},
    )


@router.get(
    "/api/platform/operations/summary",
    response_model=PlatformOperationsSummaryRead,
)
def platform_operations_summary(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_platform_admin(actor)
    set_platform_database_scope(db)
    response.headers["Cache-Control"] = "no-store"
    now = utcnow_naive()

    database_started = perf_counter()
    db.scalar(text("SELECT 1"))
    database_latency_ms = round((perf_counter() - database_started) * 1000, 3)
    snapshot = operations_monitor.snapshot(
        window_seconds=settings.operations_request_window_seconds,
        now=now,
    )
    schema_ready = getattr(request.app.state, "schema_ready", False)
    schema_revision = str(getattr(request.app.state, "schema_revision", "unknown"))
    risks = collect_platform_operations_risks(
        db,
        snapshot=snapshot,
        schema_ready=schema_ready,
        now=now,
    )
    alerts = risks["alerts"]

    status = (
        "critical"
        if any(row["severity"] == "critical" for row in alerts)
        else "degraded"
        if alerts
        else "healthy"
    )
    return {
        "status": status,
        "checked_at": utc_iso(now),
        "started_at": snapshot["started_at"],
        "uptime_seconds": snapshot["uptime_seconds"],
        "database_status": "ok",
        "database_latency_ms": database_latency_ms,
        "schema_status": "ok" if schema_ready else "error",
        "schema_revision": schema_revision,
        "requests": snapshot["requests"],
        "workers": snapshot["workers"],
        "integration_queue": risks["integration_queue"],
        "open_critical_billing_notices": risks["open_critical_billing_notices"],
        "data_protection": risks["data_protection"],
        "alerts": alerts,
    }


@router.get(
    "/api/platform/operations/alerting",
    response_model=OperationsAlertingRead,
)
def platform_operations_alerting(
    response: Response,
    incident_limit: int = Query(default=50, ge=1, le=200),
    delivery_limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_platform_admin(actor)
    set_platform_database_scope(db)
    response.headers["Cache-Control"] = "no-store"
    incidents = db.scalars(
        select(OperationsAlertIncident)
        .order_by(
            OperationsAlertIncident.last_observed_at.desc(),
            OperationsAlertIncident.id.desc(),
        )
        .limit(incident_limit)
    ).all()
    deliveries = db.scalars(
        select(OperationsAlertDelivery)
        .order_by(
            OperationsAlertDelivery.created_at.desc(),
            OperationsAlertDelivery.id.desc(),
        )
        .limit(delivery_limit)
    ).all()
    open_incident_count = db.scalar(
        select(func.count(OperationsAlertIncident.id)).where(
            OperationsAlertIncident.status == "open"
        )
    ) or 0
    pending_delivery_count = db.scalar(
        select(func.count(OperationsAlertDelivery.id)).where(
            OperationsAlertDelivery.status.in_(["pending", "processing"])
        )
    ) or 0
    failed_delivery_count = db.scalar(
        select(func.count(OperationsAlertDelivery.id)).where(
            OperationsAlertDelivery.status == "failed"
        )
    ) or 0
    config_errors = operations_alert_configuration_errors()
    return {
        "enabled": settings.operations_alert_delivery_enabled,
        "configured": settings.operations_alert_delivery_enabled and not config_errors,
        "destination_host": alert_destination_host(),
        "minimum_severity": settings.operations_alert_min_severity,
        "poll_seconds": settings.operations_alert_delivery_poll_seconds,
        "reminder_minutes": settings.operations_alert_reminder_minutes,
        "open_incident_count": open_incident_count,
        "pending_delivery_count": pending_delivery_count,
        "failed_delivery_count": failed_delivery_count,
        "incidents": [_operations_alert_incident_read(row) for row in incidents],
        "deliveries": [_operations_alert_delivery_read(row) for row in deliveries],
    }


@router.post(
    "/api/platform/operations/alerting/test",
    response_model=OperationsAlertDeliveryRead,
)
def queue_operations_alert_test(
    payload: OperationsAlertAction,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_platform_admin(actor)
    _require_platform_reauthentication(db, actor, payload.account_password)
    errors = operations_alert_configuration_errors()
    if not settings.operations_alert_delivery_enabled or errors:
        raise HTTPException(status_code=409, detail="Operations alert delivery is not configured")
    set_platform_database_scope(db)
    queued_at = utcnow_naive()
    delivery = enqueue_operations_alert_test(db, now=queued_at)
    db.flush()
    db.add(
        AuditLog(
            organization_id=actor.organization_id,
            user_id=actor.user_id,
            action="queue_operations_alert_test",
            entity_type="operations_alert_delivery",
            entity_id=delivery.id,
            metadata_json=json.dumps(
                {
                    "reason": payload.reason,
                    "destination_host": alert_destination_host(),
                    "queued_at": utc_iso(queued_at),
                },
                separators=(",", ":"),
            ),
            timestamp=queued_at,
        )
    )
    db.commit()
    db.refresh(delivery)
    return _operations_alert_delivery_read(delivery)


@router.post(
    "/api/platform/operations/alerting/deliveries/{delivery_id}/retry",
    response_model=OperationsAlertDeliveryRead,
)
def retry_operations_alert_delivery(
    delivery_id: int,
    payload: OperationsAlertRetryAction,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_platform_admin(actor)
    _require_platform_reauthentication(db, actor, payload.account_password)
    errors = operations_alert_configuration_errors()
    if not settings.operations_alert_delivery_enabled or errors:
        raise HTTPException(status_code=409, detail="Operations alert delivery is not configured")
    set_platform_database_scope(db)
    delivery = db.get(OperationsAlertDelivery, delivery_id)
    if not delivery:
        raise HTTPException(status_code=404, detail="Operations alert delivery not found")
    if delivery.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Operations alert delivery version conflict")
    if delivery.status != "failed":
        raise HTTPException(status_code=409, detail="Only failed alert deliveries can be retried")
    queued_at = utcnow_naive()
    previous_attempt_count = delivery.attempt_count
    delivery.status = "pending"
    delivery.attempt_count = 0
    delivery.response_status_code = None
    delivery.failure_code = None
    delivery.next_attempt_at = queued_at
    delivery.sent_at = None
    delivery.version += 1
    delivery.updated_at = queued_at
    db.add(delivery)
    db.add(
        AuditLog(
            organization_id=actor.organization_id,
            user_id=actor.user_id,
            action="retry_operations_alert_delivery",
            entity_type="operations_alert_delivery",
            entity_id=delivery.id,
            metadata_json=json.dumps(
                {
                    "reason": payload.reason,
                    "previous_attempt_count": previous_attempt_count,
                    "idempotency_key": delivery.idempotency_key,
                    "queued_at": utc_iso(queued_at),
                },
                separators=(",", ":"),
            ),
            timestamp=queued_at,
        )
    )
    db.commit()
    db.refresh(delivery)
    return _operations_alert_delivery_read(delivery)


@router.get(
    "/api/platform/operations/history",
    response_model=PlatformOperationsHistoryRead,
)
def platform_operations_history(
    response: Response,
    hours: int = Query(default=24, ge=1, le=168),
    bucket_minutes: int = Query(default=15, ge=1, le=60),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_platform_admin(actor)
    response.headers["Cache-Control"] = "no-store"
    to_at = utcnow_naive()
    from_at = to_at - timedelta(hours=hours)
    return aggregate_operations_history(
        db,
        from_at=from_at,
        to_at=to_at,
        bucket_minutes=bucket_minutes,
        max_samples=settings.operations_history_query_max_samples,
    )


@router.post(
    "/api/platform/operations/recover-stale-deliveries",
    response_model=OperationsStaleDeliveryRecoveryRead,
)
def recover_stale_outbound_deliveries(
    payload: OperationsStaleDeliveryRecovery,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_platform_admin(actor)
    _require_platform_reauthentication(db, actor, payload.account_password)
    set_platform_database_scope(db)

    queued_at = utcnow_naive()
    stale_before = queued_at - timedelta(
        minutes=max(1, settings.operations_stale_processing_minutes)
    )
    candidates = db.scalars(
        select(ExternalSyncLog)
        .where(
            ExternalSyncLog.direction == "outbound",
            ExternalSyncLog.status == "processing",
            ExternalSyncLog.updated_at < stale_before,
        )
        .order_by(ExternalSyncLog.updated_at, ExternalSyncLog.id)
        .limit(payload.max_items)
        .with_for_update(skip_locked=True)
    ).all()

    recovered_by_organization: dict[int, list[int]] = {}
    for delivery in candidates:
        # The row lock and repeated state check preserve a worker result that
        # completed while this recovery request was waiting for the lock.
        if delivery.status != "processing" or delivery.updated_at >= stale_before:
            continue
        delivery.status = "pending"
        delivery.next_retry_at = queued_at
        delivery.processed_at = None
        delivery.error_message = "Recovered from an interrupted processing lease"
        delivery.updated_at = queued_at
        recovered_by_organization.setdefault(delivery.organization_id, []).append(
            delivery.id
        )
        db.add(delivery)

    audit_groups = recovered_by_organization or {actor.organization_id: []}
    for organization_id, delivery_ids in audit_groups.items():
        db.add(
            AuditLog(
                organization_id=organization_id,
                user_id=actor.user_id,
                action="recover_stale_outbound_deliveries",
                entity_type="external_sync_log",
                metadata_json=json.dumps(
                    {
                        "actor_role": actor.role.value,
                        "auth_method": actor.auth_method,
                        "recovered_count": len(delivery_ids),
                        "delivery_ids": delivery_ids,
                        "stale_before": utc_iso(stale_before),
                        "queued_at": utc_iso(queued_at),
                        "reason": payload.reason,
                    },
                    separators=(",", ":"),
                ),
                timestamp=queued_at,
            )
        )
    db.commit()

    recovered_ids = sorted(
        delivery_id
        for delivery_ids in recovered_by_organization.values()
        for delivery_id in delivery_ids
    )
    return OperationsStaleDeliveryRecoveryRead(
        recovered_count=len(recovered_ids),
        organization_count=len(recovered_by_organization),
        recovered_delivery_ids=recovered_ids,
        stale_before=stale_before,
        queued_at=queued_at,
    )
