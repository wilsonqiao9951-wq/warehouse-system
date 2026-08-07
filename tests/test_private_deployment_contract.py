from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_production_compose_keeps_data_private_and_migrations_one_shot():
    compose = yaml.safe_load((ROOT / "docker-compose.production.yml").read_text(encoding="utf-8"))
    services = compose["services"]

    assert set(services) == {"db", "migrate", "api", "web"}
    assert "ports" not in services["db"]
    assert "ports" not in services["api"]
    assert "ports" not in services["migrate"]
    assert services["web"]["ports"] == ["${OPENPARTSFLOW_PORT:-8080}:8080"]
    assert compose["networks"]["data"]["internal"] is True
    assert services["db"]["networks"] == ["data"]

    assert services["migrate"]["command"] == ["alembic", "upgrade", "head"]
    assert services["migrate"]["environment"]["DATABASE_URL"].startswith(
        "${MIGRATION_DATABASE_URL:"
    )
    assert services["api"]["environment"]["DATABASE_URL"].startswith(
        "${DATABASE_URL:"
    )
    assert services["api"]["environment"]["DEPLOYMENT_REGION"].startswith(
        "${DEPLOYMENT_REGION:"
    )
    assert (
        services["migrate"]["environment"]["DATABASE_URL"]
        != services["api"]["environment"]["DATABASE_URL"]
    )
    assert services["db"]["environment"]["POSTGRES_USER"].startswith(
        "${POSTGRES_OWNER_USER:"
    )
    assert services["db"]["environment"]["POSTGRES_APP_USER"].startswith(
        "${POSTGRES_APP_USER:"
    )
    assert any(
        "init-app-role.sh" in volume for volume in services["db"]["volumes"]
    )
    assert "--proxy-headers" in services["api"]["command"]
    assert "--forwarded-allow-ips=*" in services["api"]["command"]
    assert services["api"]["networks"] == ["edge", "data"]
    assert services["web"]["networks"] == ["edge"]
    assert services["migrate"]["restart"] == "no"
    assert services["api"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert services["web"]["depends_on"]["api"]["condition"] == "service_healthy"
    assert services["web"]["build"]["args"]["NEXT_PUBLIC_AUTH_SESSION_MODE"] == "${PUBLIC_AUTH_SESSION_MODE:-auto}"


def test_runtime_services_are_non_root_read_only_and_have_explicit_writes():
    compose = yaml.safe_load((ROOT / "docker-compose.production.yml").read_text(encoding="utf-8"))
    services = compose["services"]

    for service_name in ("migrate", "api"):
        service = services[service_name]
        assert service["user"] == "10001:10001"
        assert service["read_only"] is True
        assert service["cap_drop"] == ["ALL"]
        assert "no-new-privileges:true" in service["security_opt"]
    assert services["web"]["read_only"] is True
    assert services["web"]["user"] == "101:101"
    assert services["web"]["cap_drop"] == ["ALL"]

    for service in services.values():
        assert service["logging"]["driver"] == "json-file"
        assert service["logging"]["options"] == {"max-size": "10m", "max-file": "5"}

    assert set(compose["volumes"]) == {
        "postgres_data",
        "uploads",
        "private_uploads",
        "restore_rollbacks",
    }
    assert set(services["api"]["volumes"]) == {
        "uploads:/app/data/uploads",
        "private_uploads:/app/data/private",
        "restore_rollbacks:/app/data/rollbacks",
    }


def test_postgres_runtime_role_bootstrap_forbids_rls_bypass():
    script = (ROOT / "deploy" / "postgres" / "init-app-role.sh").read_text(
        encoding="utf-8"
    )

    assert "NOSUPERUSER" in script
    assert "NOBYPASSRLS" in script
    assert "NOINHERIT" in script
    assert "ALTER DEFAULT PRIVILEGES" in script
    assert "GRANT SELECT, INSERT, UPDATE, DELETE" in script


def test_proxy_exposes_only_allowlisted_backend_routes_and_security_headers():
    nginx = (ROOT / "frontend" / "deploy" / "nginx.conf").read_text(encoding="utf-8")

    for route in ("/api/", "/uploads/", "/health/"):
        assert f"location {route}" in nginx
    assert "proxy_pass http://api:8000" in nginx
    assert "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;" in nginx
    assert 'add_header X-Content-Type-Options "nosniff" always;' in nginx
    assert 'add_header X-Frame-Options "DENY" always;' in nginx
    assert "client_max_body_size 600m;" in nginx
