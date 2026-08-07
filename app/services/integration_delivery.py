from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from hashlib import sha256
import hmac
from ipaddress import ip_address
import json
import logging
import socket
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.core.database import set_tenant_database_scope
from app.models import (
    ExternalIntegration,
    ExternalSyncLog,
    ExternalWorkOrderLink,
    WorkOrder,
)
from app.services.integrations import (
    integration_subscribed_events,
    validate_webhook_url,
)


logger = logging.getLogger(__name__)

MAX_DELIVERY_ATTEMPTS = 5
RETRY_DELAYS_SECONDS = (60, 300, 1800, 7200, 21600)
WebhookSender = Callable[[str, bytes, dict[str, str]], tuple[int, str]]


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _work_order_payload(work_order: WorkOrder) -> dict[str, Any]:
    return {
        "work_order_id": work_order.id,
        "ticket_number": work_order.ticket_number,
        "status": work_order.status,
        "assigned_engineer_id": work_order.engineer_id or work_order.assigned_user_id,
        "claimed_by_id": work_order.claimed_by_id,
        "completed_by_id": work_order.completed_by_id,
        "started_at": work_order.started_at,
        "paused_at": work_order.paused_at,
        "completed_at": work_order.completed_at,
        "final_outcome": work_order.final_outcome,
        "updated_at": work_order.updated_at,
    }


def enqueue_work_order_event(
    db: Session,
    work_order: WorkOrder,
    event_type: str,
    idempotency_key: str,
    data: dict[str, Any] | None = None,
) -> list[ExternalSyncLog]:
    """Persist outbound events in the same transaction as the business change."""
    links = db.scalars(
        select(ExternalWorkOrderLink).where(
            ExternalWorkOrderLink.work_order_id == work_order.id
        )
    ).all()
    queued: list[ExternalSyncLog] = []
    occurred_at = datetime.utcnow()
    for link in links:
        integration = db.get(ExternalIntegration, link.integration_id)
        if (
            not integration
            or not integration.is_active
            or not integration.webhook_url
            or event_type not in integration_subscribed_events(integration)
        ):
            continue
        existing = db.scalar(
            select(ExternalSyncLog).where(
                ExternalSyncLog.integration_id == integration.id,
                ExternalSyncLog.idempotency_key == idempotency_key,
            )
        )
        if existing:
            queued.append(existing)
            continue
        delivery_id = str(uuid4())
        payload = {
            "event_id": delivery_id,
            "event_type": event_type,
            "occurred_at": occurred_at,
            "integration_id": integration.id,
            "external_id": link.external_id,
            "work_order": _work_order_payload(work_order),
            "data": data or {},
        }
        serialized = _canonical_json(payload)
        log = ExternalSyncLog(
            organization_id=work_order.organization_id,
            integration_id=integration.id,
            direction="outbound",
            event_type=event_type,
            external_id=link.external_id,
            idempotency_key=idempotency_key,
            request_hash=sha256(serialized.encode("utf-8")).hexdigest(),
            status="pending",
            attempt_count=0,
            work_order_id=work_order.id,
            payload_json=serialized,
            next_retry_at=occurred_at,
        )
        db.add(log)
        queued.append(log)
    return queued


def _http_sender(
    url: str,
    body: bytes,
    headers: dict[str, str],
) -> tuple[int, str]:
    hostname = urlsplit(url).hostname
    if not hostname:
        raise RuntimeError("Webhook URL has no hostname")
    try:
        addresses = {
            row[4][0]
            for row in socket.getaddrinfo(
                hostname,
                443,
                type=socket.SOCK_STREAM,
            )
        }
    except OSError as exc:
        raise RuntimeError("Webhook hostname could not be resolved") from exc
    for raw_address in addresses:
        address = ip_address(raw_address)
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            raise RuntimeError(
                "Webhook hostname resolved to a private or reserved network"
            )
    with httpx.Client(
        timeout=httpx.Timeout(10.0),
        follow_redirects=False,
    ) as client:
        response = client.post(url, content=body, headers=headers)
    return response.status_code, response.text[:4000]


def _delivery_headers(
    integration: ExternalIntegration,
    log: ExternalSyncLog,
    body: bytes,
    timestamp: str,
) -> dict[str, str]:
    signing_key = bytes.fromhex(integration.api_key_hash)
    signed_message = timestamp.encode("utf-8") + b"." + body
    signature = hmac.new(signing_key, signed_message, sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "User-Agent": "OpenPartsFlow-Webhook/1.0",
        "X-OpenPartsFlow-Event": log.event_type,
        "X-OpenPartsFlow-Delivery": str(log.id),
        "X-OpenPartsFlow-Timestamp": timestamp,
        "X-OpenPartsFlow-Signature": f"sha256={signature}",
        "Idempotency-Key": log.idempotency_key,
    }


def deliver_outbound_event(
    db: Session,
    log_id: int,
    *,
    sender: WebhookSender | None = None,
) -> ExternalSyncLog | None:
    log = db.get(ExternalSyncLog, log_id)
    if not log or log.direction != "outbound":
        return None
    if log.status == "processed":
        return log
    if log.status == "processing":
        return log
    integration = db.get(ExternalIntegration, log.integration_id)
    if not integration or not integration.is_active or not integration.webhook_url:
        log.status = "failed"
        log.error_message = "Integration is inactive or has no webhook URL"
        log.next_retry_at = None
        log.processed_at = datetime.utcnow()
        db.add(log)
        db.commit()
        return log

    try:
        url = validate_webhook_url(integration.webhook_url)
    except Exception as exc:
        log.status = "failed"
        log.error_message = str(exc)[:4000]
        log.next_retry_at = None
        log.processed_at = datetime.utcnow()
        db.add(log)
        db.commit()
        return log
    if not url:
        return log

    body = (log.payload_json or "{}").encode("utf-8")
    attempted_at = datetime.utcnow()
    previous_status = log.status
    previous_attempts = log.attempt_count
    claimed = db.execute(
        update(ExternalSyncLog)
        .where(
            ExternalSyncLog.id == log.id,
            ExternalSyncLog.status == previous_status,
            ExternalSyncLog.attempt_count == previous_attempts,
        )
        .values(
            status="processing",
            attempt_count=previous_attempts + 1,
            last_attempt_at=attempted_at,
            error_message=None,
        )
    )
    if claimed.rowcount != 1:
        db.rollback()
        db.expire(log)
        return db.get(ExternalSyncLog, log_id)
    db.commit()
    db.refresh(log)

    timestamp = f"{int(attempted_at.timestamp())}"
    headers = _delivery_headers(integration, log, body, timestamp)
    send = sender or _http_sender
    try:
        status_code, response_body = send(url, body, headers)
        log.response_status_code = status_code
        log.response_json = json.dumps(
            {"body": response_body[:4000]},
            separators=(",", ":"),
        )
        if 200 <= status_code < 300:
            log.status = "processed"
            log.error_message = None
            log.next_retry_at = None
            log.processed_at = datetime.utcnow()
        else:
            raise RuntimeError(f"Webhook returned HTTP {status_code}")
    except Exception as exc:
        log.error_message = str(exc)[:4000]
        log.processed_at = None
        cycle_attempt = (
            (log.attempt_count - 1) % MAX_DELIVERY_ATTEMPTS
        ) + 1
        if cycle_attempt == MAX_DELIVERY_ATTEMPTS:
            log.status = "failed"
            log.next_retry_at = None
            log.processed_at = datetime.utcnow()
        else:
            log.status = "pending"
            delay_index = min(
                cycle_attempt - 1,
                len(RETRY_DELAYS_SECONDS) - 1,
            )
            log.next_retry_at = datetime.utcnow() + timedelta(
                seconds=RETRY_DELAYS_SECONDS[delay_index]
            )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def process_due_deliveries(
    session_factory,
    *,
    limit: int = 50,
) -> int:
    now = datetime.utcnow()
    with session_factory() as scan_db:
        ids = scan_db.scalars(
            select(ExternalSyncLog.id)
            .where(
                ExternalSyncLog.direction == "outbound",
                ExternalSyncLog.status == "pending",
                or_(
                    ExternalSyncLog.next_retry_at.is_(None),
                    ExternalSyncLog.next_retry_at <= now,
                ),
            )
            .order_by(
                ExternalSyncLog.next_retry_at,
                ExternalSyncLog.id,
            )
            .limit(limit)
        ).all()

    processed = 0
    for log_id in ids:
        try:
            with session_factory() as db:
                log = db.get(ExternalSyncLog, log_id)
                if not log:
                    continue
                set_tenant_database_scope(db, log.organization_id)
                deliver_outbound_event(db, log_id)
                processed += 1
        except Exception:
            logger.exception("Unexpected outbound webhook delivery failure", extra={"log_id": log_id})
    return processed
