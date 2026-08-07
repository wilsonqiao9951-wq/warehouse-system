from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
import hmac

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AuthSecurityEvent, User


COUNTED_LOGIN_FAILURES = (
    "invalid_credentials",
    "device_rejected",
    "rate_limited",
)
COUNTED_PASSWORD_RESET_REQUESTS = (
    "reset_requested",
    "reset_request_ignored",
)


def auth_fingerprint(namespace: str, value: str) -> str:
    normalized = value.strip().lower()
    return hmac.new(
        settings.jwt_secret_key.encode("utf-8"),
        f"{namespace}:{normalized}".encode("utf-8"),
        sha256,
    ).hexdigest()


def login_source_fingerprint(request: Request) -> str:
    # Only the directly connected peer is trusted. Forwarded headers are not
    # accepted here because spoofed values would bypass the rate limit.
    source = request.client.host if request.client else "unknown"
    return auth_fingerprint("login-source", source)


def login_is_rate_limited(
    db: Session,
    *,
    principal_fingerprint: str,
    source_fingerprint: str,
    now: datetime,
) -> bool:
    since = now - timedelta(seconds=settings.login_rate_limit_window_seconds)
    common = (
        AuthSecurityEvent.event_type == "login",
        AuthSecurityEvent.outcome.in_(COUNTED_LOGIN_FAILURES),
        AuthSecurityEvent.occurred_at >= since,
    )
    principal_failures = db.scalar(
        select(func.count(AuthSecurityEvent.id)).where(
            *common,
            AuthSecurityEvent.principal_fingerprint == principal_fingerprint,
        )
    ) or 0
    if principal_failures >= settings.login_rate_limit_principal_failures:
        return True
    source_failures = db.scalar(
        select(func.count(AuthSecurityEvent.id)).where(
            *common,
            AuthSecurityEvent.source_fingerprint == source_fingerprint,
        )
    ) or 0
    return source_failures >= settings.login_rate_limit_source_failures


def password_reset_is_rate_limited(
    db: Session,
    *,
    principal_fingerprint: str,
    source_fingerprint: str,
    now: datetime,
) -> bool:
    since = now - timedelta(seconds=settings.password_reset_rate_limit_window_seconds)
    common = (
        AuthSecurityEvent.event_type == "password_reset",
        AuthSecurityEvent.outcome.in_(COUNTED_PASSWORD_RESET_REQUESTS),
        AuthSecurityEvent.occurred_at >= since,
    )
    principal_requests = db.scalar(
        select(func.count(AuthSecurityEvent.id)).where(
            *common,
            AuthSecurityEvent.principal_fingerprint == principal_fingerprint,
        )
    ) or 0
    if principal_requests >= settings.password_reset_principal_requests:
        return True
    source_requests = db.scalar(
        select(func.count(AuthSecurityEvent.id)).where(
            *common,
            AuthSecurityEvent.source_fingerprint == source_fingerprint,
        )
    ) or 0
    return source_requests >= settings.password_reset_source_requests


def record_auth_security_event(
    db: Session,
    *,
    event_type: str,
    outcome: str,
    principal_fingerprint: str,
    source_fingerprint: str,
    user: User | None,
    occurred_at: datetime,
) -> AuthSecurityEvent:
    event = AuthSecurityEvent(
        organization_id=user.organization_id if user else None,
        user_id=user.id if user else None,
        event_type=event_type,
        outcome=outcome,
        principal_fingerprint=principal_fingerprint,
        source_fingerprint=source_fingerprint,
        occurred_at=occurred_at,
    )
    db.add(event)
    return event
