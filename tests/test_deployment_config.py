from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.deployment import (
    DeploymentConfigurationError,
    LOCAL_CORS_ORIGINS,
    cors_allowed_origins,
    validate_deployment_settings,
)


def deployment_settings(**overrides) -> Settings:
    values = {
        "app_env": "production",
        "app_debug": False,
        "database_url": "postgresql+psycopg://openpartsflow:strong-db-secret@db:5432/openpartsflow",
        "jwt_secret_key": "a-production-jwt-secret-with-40-characters",
        "jwt_algorithm": "HS256",
        "frontend_public_url": "https://parts.example.com",
        "cors_extra_origins": "https://parts.example.com,https://api.example.com",
        "data_export_public_files_root": "/app/data/uploads",
        "data_export_private_files_root": "/app/data/private",
        "data_restore_rollback_files_root": "/app/data/rollbacks",
        "billing_webhook_secret": "",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_safe_production_configuration_and_cors_are_accepted():
    config = deployment_settings()

    validate_deployment_settings(config)

    assert cors_allowed_origins(config) == [
        "https://parts.example.com",
        "https://api.example.com",
    ]
    assert not set(LOCAL_CORS_ORIGINS).intersection(cors_allowed_origins(config))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"app_debug": True}, "APP_DEBUG"),
        ({"jwt_secret_key": "CHANGE_ME_GENERATE_AT_LEAST_32_RANDOM_CHARACTERS"}, "JWT_SECRET_KEY"),
        ({"jwt_algorithm": "none"}, "JWT_ALGORITHM"),
        ({"login_rate_limit_window_seconds": 30}, "LOGIN_RATE_LIMIT_WINDOW_SECONDS"),
        ({"login_rate_limit_principal_failures": 2}, "LOGIN_RATE_LIMIT_PRINCIPAL_FAILURES"),
        ({"login_rate_limit_source_failures": 5}, "LOGIN_RATE_LIMIT_SOURCE_FAILURES"),
        ({"password_reset_expire_minutes": 4}, "PASSWORD_RESET_EXPIRE_MINUTES"),
        ({"password_reset_rate_limit_window_seconds": 30}, "PASSWORD_RESET_RATE_LIMIT_WINDOW_SECONDS"),
        ({"password_reset_principal_requests": 0}, "PASSWORD_RESET_PRINCIPAL_REQUESTS"),
        ({"password_reset_source_requests": 2}, "PASSWORD_RESET_SOURCE_REQUESTS"),
        ({"database_url": "sqlite:///./production.db"}, "PostgreSQL"),
        ({"database_url": "not a url"}, "DATABASE_URL"),
        ({"frontend_public_url": "http://parts.example.com"}, "FRONTEND_PUBLIC_URL"),
        ({"cors_extra_origins": "https://*.example.com"}, "CORS_EXTRA_ORIGINS"),
        ({"data_export_public_files_root": "uploads"}, "DATA_EXPORT_PUBLIC_FILES_ROOT"),
        (
            {"data_export_private_files_root": "/app/data/uploads"},
            "storage roots must be distinct",
        ),
        ({"billing_webhook_secret": "change-me"}, "BILLING_WEBHOOK_SECRET"),
    ],
)
def test_unsafe_deployment_configuration_fails_closed(overrides, message):
    with pytest.raises(DeploymentConfigurationError, match=message):
        validate_deployment_settings(deployment_settings(**overrides))


def test_development_keeps_local_origins_and_does_not_require_production_secrets():
    config = Settings(_env_file=None, app_env="development")

    validate_deployment_settings(config)

    assert set(LOCAL_CORS_ORIGINS).issubset(cors_allowed_origins(config))


def test_password_reset_email_configuration_is_fail_closed():
    safe = deployment_settings(
        password_reset_email_enabled=True,
        auth_email_from="OpenPartsFlow <security@example.com>",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username="relay-user",
        smtp_password="secure-relay-password",
        smtp_use_starttls=True,
        smtp_use_ssl=False,
    )
    validate_deployment_settings(safe)

    with pytest.raises(DeploymentConfigurationError, match="SMTP_HOST"):
        validate_deployment_settings(
            deployment_settings(
                password_reset_email_enabled=True,
                auth_email_from="security@example.com",
                smtp_host="",
            )
        )
    with pytest.raises(DeploymentConfigurationError, match="Exactly one"):
        validate_deployment_settings(
            deployment_settings(
                password_reset_email_enabled=True,
                auth_email_from="security@example.com",
                smtp_host="smtp.example.com",
                smtp_use_starttls=True,
                smtp_use_ssl=True,
            )
        )


def test_stripe_production_configuration_is_fail_closed():
    safe = deployment_settings(
        stripe_billing_enabled=True,
        stripe_secret_key="sk_live_secure_server_key_for_tests",
        stripe_webhook_secret="whsec_secure_endpoint_secret_for_tests",
        stripe_price_professional="price_professional_live",
    )
    validate_deployment_settings(safe)

    with pytest.raises(DeploymentConfigurationError, match="STRIPE_SECRET_KEY"):
        validate_deployment_settings(
            deployment_settings(
                stripe_billing_enabled=True,
                stripe_secret_key="pk_live_public_key_is_not_a_secret",
                stripe_webhook_secret="whsec_secure_endpoint_secret_for_tests",
                stripe_price_professional="price_professional_live",
            )
        )
    with pytest.raises(DeploymentConfigurationError, match="STRIPE_PRICE"):
        validate_deployment_settings(
            deployment_settings(
                stripe_billing_enabled=True,
                stripe_secret_key="sk_live_secure_server_key_for_tests",
                stripe_webhook_secret="whsec_secure_endpoint_secret_for_tests",
                stripe_price_professional="prod_not_a_stripe_price",
            )
        )
