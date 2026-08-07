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
    assert services["migrate"]["restart"] == "no"
    assert services["api"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert services["web"]["depends_on"]["api"]["condition"] == "service_healthy"


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


def test_proxy_exposes_only_allowlisted_backend_routes_and_security_headers():
    nginx = (ROOT / "frontend" / "deploy" / "nginx.conf").read_text(encoding="utf-8")

    for route in ("/api/", "/uploads/", "/health/"):
        assert f"location {route}" in nginx
    assert "proxy_pass http://api:8000" in nginx
    assert 'add_header X-Content-Type-Options "nosniff" always;' in nginx
    assert 'add_header X-Frame-Options "DENY" always;' in nginx
    assert "client_max_body_size 600m;" in nginx
