from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from hashlib import sha256
from http.client import HTTPException as HttpClientError, HTTPSConnection
import hmac
from ipaddress import ip_address
import json
import logging
import socket
import ssl
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings, settings
from app.core.database import set_platform_database_scope
from app.core.operations import operations_monitor, utc_iso, utcnow_naive
from app.models import OperationsAlertDelivery, OperationsAlertIncident
from app.services.integrations import validate_webhook_url
from app.services.operations_risks import collect_platform_operations_risks


logger = logging.getLogger(__name__)
MAX_DELIVERY_ATTEMPTS = 5
RETRY_DELAYS_SECONDS = (60, 300, 1800, 7200, 21600)
SEVERITY_ORDER = {"warning": 1, "critical": 2}
OperationsAlertSender = Callable[[str, bytes, dict[str, str]], int]


def operations_alert_configuration_errors(config: Settings = settings) -> list[str]:
    errors: list[str] = []
    if config.operations_alert_min_severity not in SEVERITY_ORDER:
        errors.append("OPERATIONS_ALERT_MIN_SEVERITY must be warning or critical")
    if not 30 <= config.operations_alert_delivery_poll_seconds <= 3600:
        errors.append(
            "OPERATIONS_ALERT_DELIVERY_POLL_SECONDS must be between 30 and 3600"
        )
    if not 5 <= config.operations_alert_reminder_minutes <= 10080:
        errors.append("OPERATIONS_ALERT_REMINDER_MINUTES must be between 5 and 10080")
    if not 1 <= config.operations_alert_request_timeout_seconds <= 30:
        errors.append(
            "OPERATIONS_ALERT_REQUEST_TIMEOUT_SECONDS must be between 1 and 30"
        )
    if not 1024 <= config.operations_alert_max_response_bytes <= 65536:
        errors.append(
            "OPERATIONS_ALERT_MAX_RESPONSE_BYTES must be between 1024 and 65536"
        )
    if config.operations_alert_delivery_enabled:
        try:
            normalized = validate_webhook_url(config.operations_alert_webhook_url)
            if normalized:
                urlsplit(normalized).port
        except (HTTPException, ValueError):
            normalized = None
        if not normalized:
            errors.append(
                "OPERATIONS_ALERT_WEBHOOK_URL must be a safe HTTPS URL when alert delivery is enabled"
            )
        secret = config.operations_alert_webhook_secret
        if len(secret) < 32 or "change-me" in secret.casefold() or "placeholder" in secret.casefold():
            errors.append(
                "OPERATIONS_ALERT_WEBHOOK_SECRET must be a non-placeholder secret of at least 32 characters when alert delivery is enabled"
            )
    return errors


def alert_destination_host(config: Settings = settings) -> str | None:
    if not config.operations_alert_delivery_enabled:
        return None
    return urlsplit(config.operations_alert_webhook_url).hostname


def _canonical_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _meets_delivery_threshold(severity: str) -> bool:
    return SEVERITY_ORDER[severity] >= SEVERITY_ORDER[settings.operations_alert_min_severity]


def _enqueue_delivery(
    db: Session,
    *,
    incident: OperationsAlertIncident | None,
    event_type: str,
    occurred_at: datetime,
    unique_slot: str,
) -> OperationsAlertDelivery:
    identity = f"v1:{incident.id if incident else 'test'}:{event_type}:{unique_slot}"
    idempotency_key = sha256(identity.encode("utf-8")).hexdigest()
    existing = db.scalar(
        select(OperationsAlertDelivery).where(
            OperationsAlertDelivery.idempotency_key == idempotency_key
        )
    )
    if existing:
        return existing
    payload = {
        "event_id": idempotency_key,
        "event_type": f"operations.alert.{event_type}",
        "occurred_at": utc_iso(occurred_at),
        "source": "openpartsflow-self-reported",
        "alert": {
            "incident_id": incident.id if incident else None,
            "code": incident.alert_code if incident else "delivery_test",
            "severity": incident.severity if incident else "warning",
            "status": incident.status if incident else "test",
            "message": incident.message if incident else "OpenPartsFlow operations alert delivery test.",
            "current_count": incident.current_count if incident else 0,
            "peak_count": incident.peak_count if incident else 0,
            "opened_at": utc_iso(incident.opened_at) if incident else None,
            "last_observed_at": utc_iso(incident.last_observed_at) if incident else None,
            "resolved_at": utc_iso(incident.resolved_at) if incident else None,
        },
    }
    serialized = _canonical_json(payload)
    delivery = OperationsAlertDelivery(
        incident_id=incident.id if incident else None,
        event_type=event_type,
        idempotency_key=idempotency_key,
        request_hash=sha256(serialized.encode("utf-8")).hexdigest(),
        payload_json=serialized,
        status="pending",
        attempt_count=0,
        next_attempt_at=occurred_at,
        created_at=occurred_at,
        updated_at=occurred_at,
    )
    db.add(delivery)
    return delivery


def enqueue_operations_alert_test(db: Session, *, now: datetime | None = None) -> OperationsAlertDelivery:
    queued_at = now or utcnow_naive()
    return _enqueue_delivery(
        db,
        incident=None,
        event_type="test",
        occurred_at=queued_at,
        unique_slot=queued_at.isoformat(timespec="microseconds"),
    )


def reconcile_operations_alerts(
    db: Session,
    alerts: list[dict],
    *,
    now: datetime | None = None,
) -> tuple[int, int]:
    """Persist alert episodes and enqueue transition/reminder events."""
    observed_at = now or utcnow_naive()
    current = {
        row["code"]: row
        for row in alerts
        if not row["code"].startswith("worker_operations_alert_delivery_")
    }
    open_incidents = {
        row.alert_code: row
        for row in db.scalars(
            select(OperationsAlertIncident).where(
                OperationsAlertIncident.status == "open"
            )
        ).all()
    }
    transitions = 0
    queued = 0
    reminder_cutoff = observed_at - timedelta(
        minutes=max(5, settings.operations_alert_reminder_minutes)
    )

    for code, alert in current.items():
        incident = open_incidents.pop(code, None)
        if incident is None:
            incident = OperationsAlertIncident(
                alert_code=code,
                severity=alert["severity"],
                message=alert["message"],
                status="open",
                current_count=alert["count"],
                peak_count=alert["count"],
                observation_count=1,
                opened_at=observed_at,
                last_observed_at=observed_at,
                version=0,
                created_at=observed_at,
                updated_at=observed_at,
            )
            db.add(incident)
            db.flush()
            transitions += 1
            if _meets_delivery_threshold(incident.severity):
                _enqueue_delivery(
                    db,
                    incident=incident,
                    event_type="triggered",
                    occurred_at=observed_at,
                    unique_slot="opened",
                )
                queued += 1
            continue

        previous_severity = incident.severity
        incident.severity = alert["severity"]
        incident.message = alert["message"]
        incident.current_count = alert["count"]
        incident.peak_count = max(incident.peak_count, alert["count"])
        incident.observation_count += 1
        incident.last_observed_at = observed_at
        incident.version += 1
        incident.updated_at = observed_at
        db.add(incident)

        escalated = (
            SEVERITY_ORDER[incident.severity] > SEVERITY_ORDER[previous_severity]
            and _meets_delivery_threshold(incident.severity)
        )
        if escalated:
            _enqueue_delivery(
                db,
                incident=incident,
                event_type="escalated",
                occurred_at=observed_at,
                unique_slot=f"severity:{incident.severity}",
            )
            queued += 1
            transitions += 1
            continue

        if not _meets_delivery_threshold(incident.severity):
            continue
        last_delivery = db.scalar(
            select(OperationsAlertDelivery)
            .where(OperationsAlertDelivery.incident_id == incident.id)
            .order_by(OperationsAlertDelivery.created_at.desc(), OperationsAlertDelivery.id.desc())
            .limit(1)
        )
        if (
            last_delivery
            and last_delivery.status == "sent"
            and last_delivery.created_at <= reminder_cutoff
        ):
            reminder_slot = int(
                observed_at.timestamp()
                // (max(5, settings.operations_alert_reminder_minutes) * 60)
            )
            _enqueue_delivery(
                db,
                incident=incident,
                event_type="reminder",
                occurred_at=observed_at,
                unique_slot=f"reminder:{reminder_slot}",
            )
            queued += 1

    for incident in open_incidents.values():
        incident.status = "resolved"
        incident.current_count = 0
        incident.resolved_at = observed_at
        incident.version += 1
        incident.updated_at = observed_at
        db.add(incident)
        transitions += 1
        prior_delivery = db.scalar(
            select(OperationsAlertDelivery.id).where(
                OperationsAlertDelivery.incident_id == incident.id
            )
        )
        if prior_delivery is not None:
            _enqueue_delivery(
                db,
                incident=incident,
                event_type="resolved",
                occurred_at=observed_at,
                unique_slot="resolved",
            )
            queued += 1
    return transitions, queued


class _PinnedHTTPSConnection(HTTPSConnection):
    def __init__(self, hostname: str, port: int, address: str, timeout: float) -> None:
        super().__init__(
            hostname,
            port=port,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
        self._pinned_address = address

    def connect(self) -> None:
        raw_socket = socket.create_connection(
            (self._pinned_address, self.port),
            self.timeout,
            self.source_address,
        )
        try:
            raw_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.sock = self._context.wrap_socket(raw_socket, server_hostname=self.host)
        except Exception:
            raw_socket.close()
            raise


def _address_is_blocked(raw_address: str) -> bool:
    address = ip_address(raw_address)
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _pinned_webhook_sender(url: str, body: bytes, headers: dict[str, str]) -> int:
    normalized = validate_webhook_url(url)
    if not normalized:
        raise RuntimeError("destination_invalid")
    parsed = urlsplit(normalized)
    hostname = parsed.hostname
    port = parsed.port or 443
    if not hostname:
        raise RuntimeError("destination_invalid")
    try:
        addresses = {
            row[4][0]
            for row in socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        }
    except OSError as exc:
        raise RuntimeError("dns_resolution_failed") from exc
    if not addresses:
        raise RuntimeError("dns_resolution_failed")
    if any(_address_is_blocked(address) for address in addresses):
        raise RuntimeError("blocked_address")
    target = parsed.path or "/"
    if parsed.query:
        target += f"?{parsed.query}"
    last_error: Exception | None = None
    for address in sorted(addresses):
        connection = _PinnedHTTPSConnection(
            hostname,
            port,
            address,
            settings.operations_alert_request_timeout_seconds,
        )
        try:
            connection.request("POST", target, body=body, headers=headers)
            response = connection.getresponse()
            response.read(settings.operations_alert_max_response_bytes + 1)
            return response.status
        except (TimeoutError, socket.timeout, ssl.SSLError, HttpClientError, OSError) as exc:
            last_error = exc
        finally:
            connection.close()
    raise RuntimeError("connect_error") from last_error


def _delivery_headers(delivery: OperationsAlertDelivery, body: bytes, timestamp: str) -> dict[str, str]:
    signed_message = timestamp.encode("ascii") + b"." + body
    signature = hmac.new(
        settings.operations_alert_webhook_secret.encode("utf-8"),
        signed_message,
        sha256,
    ).hexdigest()
    return {
        "Content-Type": "application/json",
        "User-Agent": "OpenPartsFlow-Operations-Alert/1.0",
        "X-OpenPartsFlow-Operations-Event": delivery.event_type,
        "X-OpenPartsFlow-Operations-Delivery": str(delivery.id),
        "X-OpenPartsFlow-Timestamp": timestamp,
        "X-OpenPartsFlow-Operations-Signature": f"sha256={signature}",
        "Idempotency-Key": delivery.idempotency_key,
    }


def deliver_operations_alert(
    db: Session,
    delivery_id: int,
    *,
    sender: OperationsAlertSender | None = None,
) -> OperationsAlertDelivery | None:
    delivery = db.get(OperationsAlertDelivery, delivery_id)
    if not delivery or delivery.status != "pending":
        return delivery
    attempted_at = utcnow_naive()
    previous_status = delivery.status
    previous_attempts = delivery.attempt_count
    claimed = db.execute(
        update(OperationsAlertDelivery)
        .where(
            OperationsAlertDelivery.id == delivery.id,
            OperationsAlertDelivery.status == previous_status,
            OperationsAlertDelivery.attempt_count == previous_attempts,
        )
        .values(
            status="processing",
            attempt_count=previous_attempts + 1,
            last_attempt_at=attempted_at,
            failure_code=None,
            updated_at=attempted_at,
            version=delivery.version + 1,
        )
    )
    if claimed.rowcount != 1:
        db.rollback()
        return db.get(OperationsAlertDelivery, delivery_id)
    db.commit()
    db.refresh(delivery)

    body = delivery.payload_json.encode("utf-8")
    timestamp = str(int(attempted_at.timestamp()))
    headers = _delivery_headers(delivery, body, timestamp)
    try:
        status_code = (sender or _pinned_webhook_sender)(
            settings.operations_alert_webhook_url,
            body,
            headers,
        )
        delivery.response_status_code = status_code
        if 200 <= status_code < 300:
            delivery.status = "sent"
            delivery.failure_code = None
            delivery.next_attempt_at = None
            delivery.sent_at = utcnow_naive()
        else:
            raise RuntimeError("http_status")
    except Exception as exc:
        safe_code = str(exc) if str(exc) in {
            "destination_invalid",
            "dns_resolution_failed",
            "blocked_address",
            "connect_error",
            "http_status",
        } else "delivery_error"
        delivery.failure_code = safe_code
        cycle_attempt = min(delivery.attempt_count, MAX_DELIVERY_ATTEMPTS)
        if cycle_attempt >= MAX_DELIVERY_ATTEMPTS:
            delivery.status = "failed"
            delivery.next_attempt_at = None
        else:
            delivery.status = "pending"
            delivery.next_attempt_at = utcnow_naive() + timedelta(
                seconds=RETRY_DELAYS_SECONDS[cycle_attempt - 1]
            )
    delivery.updated_at = utcnow_naive()
    delivery.version += 1
    db.add(delivery)
    db.commit()
    db.refresh(delivery)
    return delivery


def process_operations_alert_cycle(
    session_factory,
    *,
    schema_ready: bool,
    limit: int = 50,
    heartbeat: Callable[[], None] | None = None,
) -> int:
    now = utcnow_naive()
    with session_factory() as db:
        set_platform_database_scope(db)
        stale_before = now - timedelta(
            seconds=max(60, settings.operations_alert_delivery_poll_seconds * 3)
        )
        db.execute(
            update(OperationsAlertDelivery)
            .where(
                OperationsAlertDelivery.status == "processing",
                OperationsAlertDelivery.updated_at < stale_before,
                OperationsAlertDelivery.attempt_count >= MAX_DELIVERY_ATTEMPTS,
            )
            .values(
                status="failed",
                next_attempt_at=None,
                failure_code="processing_lease_expired",
                updated_at=now,
                version=OperationsAlertDelivery.version + 1,
            )
        )
        db.execute(
            update(OperationsAlertDelivery)
            .where(
                OperationsAlertDelivery.status == "processing",
                OperationsAlertDelivery.updated_at < stale_before,
                OperationsAlertDelivery.attempt_count < MAX_DELIVERY_ATTEMPTS,
            )
            .values(
                status="pending",
                next_attempt_at=now,
                failure_code="processing_lease_recovered",
                updated_at=now,
                version=OperationsAlertDelivery.version + 1,
            )
        )
        snapshot = operations_monitor.snapshot(
            window_seconds=settings.operations_request_window_seconds,
            now=now,
        )
        risks = collect_platform_operations_risks(
            db,
            snapshot=snapshot,
            schema_ready=schema_ready,
            now=now,
        )
        transitions, queued = reconcile_operations_alerts(
            db,
            risks["alerts"],
            now=now,
        )
        db.commit()
        due_ids = db.scalars(
            select(OperationsAlertDelivery.id)
            .where(
                OperationsAlertDelivery.status == "pending",
                or_(
                    OperationsAlertDelivery.next_attempt_at.is_(None),
                    OperationsAlertDelivery.next_attempt_at <= now,
                ),
            )
            .order_by(
                OperationsAlertDelivery.next_attempt_at,
                OperationsAlertDelivery.id,
            )
            .limit(limit)
        ).all()

    processed = 0
    for delivery_id in due_ids:
        if heartbeat:
            heartbeat()
        try:
            with session_factory() as db:
                set_platform_database_scope(db)
                deliver_operations_alert(db, delivery_id)
                processed += 1
        except Exception:
            logger.exception(
                "Unexpected operations alert delivery failure",
                extra={"delivery_id": delivery_id},
            )
        if heartbeat:
            heartbeat()
    return transitions + queued + processed
