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
    max_import_upload_bytes: int = 5 * 1024 * 1024
    # Comma-separated browser origins for CORS (e.g. Cloudflare Tunnel https://xxx.trycloudflare.com)
    cors_extra_origins: str = ""


settings = Settings()

# Authentication is fail-closed in every runnable environment. The test suite
# may explicitly change these in-memory values after import, but stale local
# .env files can no longer silently disable ownership enforcement.
if settings.app_env.lower() != "test":
    settings.rbac_enforce = True
    settings.legacy_header_auth = False
