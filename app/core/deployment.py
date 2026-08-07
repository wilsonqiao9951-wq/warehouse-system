from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath
from urllib.parse import urlsplit

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from app.core.config import Settings, settings


DEPLOYMENT_ENVIRONMENTS = {"production", "staging"}
LOCAL_CORS_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "http://localhost:3002",
    "http://127.0.0.1:3002",
)
_PLACEHOLDER_MARKERS = (
    "change-me",
    "change_me",
    "changeme",
    "development-only",
    "example-secret",
    "replace-me",
    "replace-with",
)


class DeploymentConfigurationError(RuntimeError):
    """Raised when a deployable environment is configured unsafely."""


def _configured_origins(config: Settings) -> list[str]:
    return [
        origin.strip().rstrip("/")
        for origin in (config.cors_extra_origins or "").split(",")
        if origin.strip()
    ]


def cors_allowed_origins(config: Settings = settings) -> list[str]:
    """Return exact browser origins without exposing dev origins in production."""

    configured = _configured_origins(config)
    origins = configured if config.app_env.lower() in DEPLOYMENT_ENVIRONMENTS else [
        *LOCAL_CORS_ORIGINS,
        *configured,
    ]
    return list(dict.fromkeys(origins))


def _is_placeholder(value: str) -> bool:
    lowered = value.strip().lower()
    return any(marker in lowered for marker in _PLACEHOLDER_MARKERS)


def _validate_https_origin(value: str, label: str, errors: list[str]) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or "*" in value
    ):
        errors.append(f"{label} must be an exact HTTPS origin without credentials, path, query, fragment, or wildcard")


def validate_deployment_settings(config: Settings = settings) -> None:
    """Fail closed on unsafe staging/production configuration.

    Development and test remain intentionally flexible. This check runs before
    schema readiness so an invalid deployment never begins serving traffic.
    """

    environment = config.app_env.strip().lower()
    if environment not in DEPLOYMENT_ENVIRONMENTS:
        return

    errors: list[str] = []
    if config.app_debug:
        errors.append("APP_DEBUG must be false")
    if len(config.jwt_secret_key) < 32 or _is_placeholder(config.jwt_secret_key):
        errors.append("JWT_SECRET_KEY must be a non-placeholder secret of at least 32 characters")
    if config.jwt_algorithm not in {"HS256", "HS384", "HS512"}:
        errors.append("JWT_ALGORITHM must be HS256, HS384, or HS512")

    try:
        database = make_url(config.database_url)
        if not database.drivername.startswith("postgresql"):
            errors.append("DATABASE_URL must use PostgreSQL in staging or production")
        if _is_placeholder(config.database_url):
            errors.append("DATABASE_URL must not contain placeholder credentials")
    except (ArgumentError, TypeError, ValueError):
        errors.append("DATABASE_URL is not a valid SQLAlchemy URL")

    _validate_https_origin(config.frontend_public_url.rstrip("/"), "FRONTEND_PUBLIC_URL", errors)
    for origin in _configured_origins(config):
        _validate_https_origin(origin, "Each CORS_EXTRA_ORIGINS entry", errors)

    storage_values = {
        "DATA_EXPORT_PUBLIC_FILES_ROOT": config.data_export_public_files_root,
        "DATA_EXPORT_PRIVATE_FILES_ROOT": config.data_export_private_files_root,
        "DATA_RESTORE_ROLLBACK_FILES_ROOT": config.data_restore_rollback_files_root,
    }
    normalized_storage: list[str] = []
    for label, value in storage_values.items():
        if not (
            PurePosixPath(value).is_absolute()
            or PureWindowsPath(value).is_absolute()
        ):
            errors.append(f"{label} must be an absolute path")
        normalized_storage.append(value.rstrip("/\\"))
    if len(set(normalized_storage)) != len(normalized_storage):
        errors.append("Public, private, and rollback storage roots must be distinct")

    if config.billing_webhook_secret and (
        len(config.billing_webhook_secret) < 32
        or _is_placeholder(config.billing_webhook_secret)
    ):
        errors.append("BILLING_WEBHOOK_SECRET must be empty or a non-placeholder secret of at least 32 characters")

    if config.stripe_billing_enabled:
        if (
            len(config.stripe_secret_key) < 24
            or not config.stripe_secret_key.startswith("sk_")
            or _is_placeholder(config.stripe_secret_key)
        ):
            errors.append("STRIPE_SECRET_KEY must be a non-placeholder server secret when Stripe billing is enabled")
        if (
            len(config.stripe_webhook_secret) < 24
            or not config.stripe_webhook_secret.startswith("whsec_")
            or _is_placeholder(config.stripe_webhook_secret)
        ):
            errors.append("STRIPE_WEBHOOK_SECRET must be a non-placeholder endpoint secret when Stripe billing is enabled")
        configured_prices = (
            config.stripe_price_starter,
            config.stripe_price_professional,
            config.stripe_price_enterprise,
        )
        if not any(value.strip() for value in configured_prices):
            errors.append("At least one STRIPE_PRICE_* value is required when Stripe billing is enabled")
        if any(value and not value.startswith("price_") for value in configured_prices):
            errors.append("Every configured STRIPE_PRICE_* value must be a Stripe Price identifier")
        if config.stripe_api_base_url.rstrip("/") != "https://api.stripe.com":
            errors.append("STRIPE_API_BASE_URL must be https://api.stripe.com in staging or production")
        if config.stripe_request_timeout_seconds < 1 or config.stripe_request_timeout_seconds > 60:
            errors.append("STRIPE_REQUEST_TIMEOUT_SECONDS must be between 1 and 60")

    if errors:
        formatted = "\n".join(f"- {error}" for error in errors)
        raise DeploymentConfigurationError(
            f"Unsafe {environment} configuration:\n{formatted}"
        )
