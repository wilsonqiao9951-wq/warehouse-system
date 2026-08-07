from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import hmac
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import settings


@dataclass(frozen=True)
class StripeAPIResult:
    data: dict[str, Any]
    request_id: str | None


class StripeConfigurationError(RuntimeError):
    pass


class StripeRequestError(RuntimeError):
    def __init__(self, status_code: int, code: str, request_id: str | None = None):
        super().__init__(code)
        self.status_code = status_code
        self.code = code[:100]
        self.request_id = request_id[:200] if request_id else None


def configured_price_ids() -> dict[str, str]:
    return {
        plan: value.strip()
        for plan, value in {
            "starter": settings.stripe_price_starter,
            "professional": settings.stripe_price_professional,
            "enterprise": settings.stripe_price_enterprise,
        }.items()
        if value.strip()
    }


def require_stripe_configuration() -> None:
    if not settings.stripe_billing_enabled:
        raise StripeConfigurationError("Stripe billing is disabled")
    if len(settings.stripe_secret_key) < 24 or not settings.stripe_secret_key.startswith("sk_"):
        raise StripeConfigurationError("Stripe secret key is not configured safely")
    if not configured_price_ids():
        raise StripeConfigurationError("No Stripe plan prices are configured")


def stripe_plan_for_price(price_id: str | None) -> str | None:
    if not price_id:
        return None
    return next((plan for plan, configured in configured_price_ids().items() if configured == price_id), None)


def _stripe_headers(idempotency_key: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {settings.stripe_secret_key}",
        "Stripe-Version": settings.stripe_api_version,
        "User-Agent": "OpenPartsFlow/1.0",
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def _stripe_result(response: httpx.Response) -> StripeAPIResult:
    request_id = response.headers.get("Request-Id")
    try:
        data = response.json()
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    if response.is_error:
        error = data.get("error") if isinstance(data.get("error"), dict) else {}
        code = error.get("code") or error.get("type") or "stripe_request_failed"
        raise StripeRequestError(response.status_code, str(code), request_id)
    return StripeAPIResult(data=data, request_id=request_id)


def stripe_api_post(
    path: str,
    form: dict[str, str],
    *,
    idempotency_key: str,
) -> StripeAPIResult:
    require_stripe_configuration()
    try:
        with httpx.Client(
            base_url=settings.stripe_api_base_url,
            timeout=settings.stripe_request_timeout_seconds,
            follow_redirects=False,
        ) as client:
            response = client.post(
                path,
                data=form,
                headers=_stripe_headers(idempotency_key),
            )
    except httpx.RequestError as exc:
        raise StripeRequestError(503, "stripe_unavailable") from exc
    return _stripe_result(response)


def stripe_api_get(path: str) -> StripeAPIResult:
    require_stripe_configuration()
    try:
        with httpx.Client(
            base_url=settings.stripe_api_base_url,
            timeout=settings.stripe_request_timeout_seconds,
            follow_redirects=False,
        ) as client:
            response = client.get(path, headers=_stripe_headers())
    except httpx.RequestError as exc:
        raise StripeRequestError(503, "stripe_unavailable") from exc
    return _stripe_result(response)


def verify_stripe_signature(
    body: bytes,
    signature_header: str | None,
    *,
    now_epoch: int | None = None,
) -> None:
    secret = settings.stripe_webhook_secret
    if len(secret) < 24 or not secret.startswith("whsec_"):
        raise StripeConfigurationError("Stripe webhook secret is not configured safely")
    parts: dict[str, list[str]] = {}
    for field in (signature_header or "").split(","):
        key, separator, value = field.partition("=")
        if separator:
            parts.setdefault(key.strip(), []).append(value.strip())
    try:
        timestamp = int(parts.get("t", [""])[0])
    except (ValueError, IndexError) as exc:
        raise ValueError("Stripe signature timestamp is invalid") from exc
    current = int(time.time()) if now_epoch is None else now_epoch
    tolerance = max(30, settings.billing_webhook_tolerance_seconds)
    if abs(current - timestamp) > tolerance:
        raise ValueError("Stripe signature timestamp is outside the allowed window")
    signed = str(timestamp).encode("ascii") + b"." + body
    expected = hmac.new(secret.encode("utf-8"), signed, sha256).hexdigest()
    if not any(hmac.compare_digest(candidate, expected) for candidate in parts.get("v1", [])):
        raise ValueError("Stripe webhook signature is invalid")


def stripe_signature(body: bytes, timestamp: int, secret: str) -> str:
    signed = str(timestamp).encode("ascii") + b"." + body
    digest = hmac.new(secret.encode("utf-8"), signed, sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def stripe_redirect_url(value: object, expected_host: str) -> str:
    url = str(value or "")
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != expected_host or parsed.username or parsed.password:
        raise StripeRequestError(502, "stripe_invalid_redirect")
    return url


def utc_from_epoch(value: object) -> datetime | None:
    if not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc).replace(tzinfo=None)
    except (OverflowError, OSError, ValueError):
        return None
