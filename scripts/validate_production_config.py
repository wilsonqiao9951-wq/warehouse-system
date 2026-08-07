from __future__ import annotations

import sys
from urllib.parse import urlsplit

from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.deployment import (
    DeploymentConfigurationError,
    cors_allowed_origins,
    validate_deployment_settings,
)


def main() -> int:
    try:
        validate_deployment_settings(settings)
    except DeploymentConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    database = make_url(settings.database_url)
    frontend = urlsplit(settings.frontend_public_url)
    print("OpenPartsFlow deployment configuration is valid.")
    print(f"environment={settings.app_env.lower()}")
    print(f"deployment_region={settings.deployment_region}")
    print(f"database_driver={database.drivername}")
    print(f"frontend_origin={frontend.scheme}://{frontend.netloc}")
    print(f"cors_origin_count={len(cors_allowed_origins(settings))}")
    print("secrets=redacted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
