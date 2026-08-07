from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "OpenPartsFlow"
    app_env: str = "development"
    app_debug: bool = False
    log_level: str = "INFO"
    database_url: str = "sqlite:///./openpartsflow.db"
    rbac_enforce: bool = True
    legacy_header_auth: bool = False
    jwt_secret_key: str = "development-only-change-me-32-bytes-minimum"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480
    invitation_expire_hours: int = 72
    frontend_public_url: str = "http://localhost:3000"
    max_image_upload_bytes: int = 10 * 1024 * 1024
    max_audio_upload_bytes: int = 15 * 1024 * 1024
    max_knowledge_media_upload_bytes: int = 50 * 1024 * 1024
    max_import_upload_bytes: int = 5 * 1024 * 1024
    integration_delivery_enabled: bool = True
    integration_delivery_poll_seconds: int = 30
    custom_domain_dns_resolver_url: str = "https://cloudflare-dns.com/dns-query"
    custom_domain_verification_cooldown_seconds: int = 30
    billing_reconciliation_enabled: bool = True
    billing_reconciliation_poll_seconds: int = 3600
    billing_notice_window_days: int = 7
    billing_webhook_secret: str = ""
    billing_webhook_tolerance_seconds: int = 300
    billing_webhook_max_bytes: int = 65536
    data_export_public_files_root: str = "uploads"
    data_export_private_files_root: str = "private_uploads"
    max_data_export_bytes: int = 512 * 1024 * 1024
    max_audit_export_rows: int = 100_000
    operations_request_window_seconds: int = 300
    operations_backup_warning_days: int = 7
    operations_stale_processing_minutes: int = 10
    operations_slow_request_ms: int = 1000
    # Includes room for the manifest/ZIP overhead around a max-sized export.
    max_data_restore_archive_bytes: int = 528 * 1024 * 1024
    max_data_restore_uncompressed_bytes: int = 528 * 1024 * 1024
    max_data_restore_rollback_bytes: int = 64 * 1024 * 1024
    data_restore_rollback_files_root: str = "restore_rollbacks"
    max_data_restore_file_rollback_bytes: int = 1024 * 1024 * 1024
    # Comma-separated browser origins for CORS (e.g. Cloudflare Tunnel https://xxx.trycloudflare.com)
    cors_extra_origins: str = ""


settings = Settings()

# Authentication is fail-closed in every runnable environment. The test suite
# may explicitly change these in-memory values after import, but stale local
# .env files can no longer silently disable ownership enforcement.
if settings.app_env.lower() != "test":
    settings.rbac_enforce = True
    settings.legacy_header_auth = False
