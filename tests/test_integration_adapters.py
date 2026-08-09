from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import json

from fastapi import HTTPException
from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.models import (
    AuditLog,
    IntegrationAdapterConfiguration,
    IntegrationConnectionTest,
    Organization,
    User,
    UserRole,
)
from app.services.data_exports import _row_payload
from app.services.integration_adapters import (
    AdapterProbeResult,
    IntegrationCredentialConfigurationError,
    decrypt_integration_credential,
    encrypt_integration_credential,
    normalize_adapter_base_url,
    normalize_api_key_header,
    normalize_health_path,
    probe_adapter_connection,
)


TEST_KEY = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="
SECOND_KEY = "ICEiIyQlJicoKSorLC0uLzAxMjM0NTY3ODk6Ozw9Pj8="
PASSWORD = "adapter-admin-password"


@contextmanager
def _credential_keys(value: str = TEST_KEY):
    original = settings.integration_credential_encryption_keys
    settings.integration_credential_encryption_keys = value
    try:
        yield
    finally:
        settings.integration_credential_encryption_keys = original


def _create_integration(
    client,
    *,
    provider: str = "erp",
    name: str = "ERP adapter",
    headers: dict[str, str] | None = None,
) -> dict:
    response = client.post(
        "/api/integrations",
        headers=headers,
        json={"name": name, "provider": provider, "field_mapping": {}},
    )
    assert response.status_code == 200, response.text
    return response.json()["integration"]


def _adapter_payload(
    *,
    expected_version: int = 0,
    credential_secret: str | None = "erp-token-value",
    account_password: str | None = None,
) -> dict:
    payload = {
        "expected_version": expected_version,
        "protocol": "rest_json",
        "base_url": "https://erp.example.test/api/",
        "health_path": "/health",
        "auth_type": "bearer",
        "credential_secret": credential_secret,
        "timeout_seconds": 8,
    }
    if account_password is not None:
        payload["account_password"] = account_password
    return payload


def test_adapter_configuration_encrypts_credentials_and_versions_connection_evidence(
    client, monkeypatch
):
    integration = _create_integration(client)
    endpoint = f"/api/integrations/{integration['id']}/adapter"
    empty = client.get(endpoint)
    assert empty.status_code == 200, empty.text
    assert empty.json()["persisted"] is False
    assert empty.json()["has_credentials"] is False

    with _credential_keys():
        created = client.put(endpoint, json=_adapter_payload())
        assert created.status_code == 200, created.text
        configuration = created.json()
        assert configuration["persisted"] is True
        assert configuration["base_url"] == "https://erp.example.test/api"
        assert configuration["has_credentials"] is True
        assert "credential_secret" not in created.text
        assert "erp-token-value" not in created.text

        with client.app.state.testing_session_local() as db:
            stored = db.scalar(select(IntegrationAdapterConfiguration))
            assert stored.credential_ciphertext
            assert "erp-token-value" not in stored.credential_ciphertext
            assert decrypt_integration_credential(
                stored.credential_ciphertext,
                organization_id=stored.organization_id,
                integration_id=stored.integration_id,
                auth_type=stored.auth_type,
            ) == "erp-token-value"
            assert "credential_ciphertext" not in _row_payload(stored)

        updated_payload = _adapter_payload(expected_version=0, credential_secret=None)
        updated_payload["health_path"] = "/ready"
        updated = client.put(endpoint, json=updated_payload)
        assert updated.status_code == 200, updated.text
        assert updated.json()["version"] == 1
        assert updated.json()["has_credentials"] is True
        assert client.put(endpoint, json=updated_payload).status_code == 409

        monkeypatch.setattr(
            "app.api.integrations.probe_adapter_connection",
            lambda configuration, credential: AdapterProbeResult(
                status="success",
                response_status_code=204,
                latency_ms=37,
                protocol_confirmed=True,
                protocol_signal="http_2xx",
                error_code=None,
            )
            if credential == "erp-token-value"
            else (_ for _ in ()).throw(AssertionError("plaintext credential was not decrypted")),
        )
        tested = client.post(f"{endpoint}/test", json={"expected_version": 1})
        assert tested.status_code == 200, tested.text
        evidence = tested.json()
        assert evidence["status"] == "success"
        assert evidence["current"] is True
        assert evidence["response_status_code"] == 204
        assert evidence["protocol_confirmed"] is True
        assert len(evidence["evidence_fingerprint"]) == 64
        assert "erp-token-value" not in tested.text

        current = client.get(endpoint).json()
        assert current["latest_test"]["id"] == evidence["id"]
        assert current["latest_test"]["current"] is True

        changed = client.put(
            endpoint,
            json=_adapter_payload(expected_version=1, credential_secret=None),
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["version"] == 2
        assert changed.json()["latest_test"]["current"] is False
        history = client.get(f"{endpoint}/tests")
        assert history.status_code == 200, history.text
        assert history.json()[0]["current"] is False

    with client.app.state.testing_session_local() as db:
        assert db.scalar(select(IntegrationConnectionTest)).status == "success"
        audits = db.scalars(select(AuditLog)).all()
        serialized = "\n".join(row.metadata_json or "" for row in audits)
        assert "erp-token-value" not in serialized
        assert "credential_ciphertext" not in serialized
        actions = {row.action for row in audits}
        assert {
            "create_integration_adapter_configuration",
            "update_integration_adapter_configuration",
            "test_integration_adapter_connection",
        }.issubset(actions)


def test_adapter_validation_key_rotation_tamper_and_ssrf_guard(client, monkeypatch):
    for blocked in (
        "http://erp.example.test",
        "https://localhost/api",
        "https://127.0.0.1/api",
        "https://169.254.169.254/latest/meta-data",
        "https://user:password@erp.example.test/api",
    ):
        try:
            normalize_adapter_base_url(blocked)
            assert False, f"{blocked} should have been rejected"
        except HTTPException as exc:
            assert exc.status_code == 422
    for blocked_path in ("https://evil.test/path", "//evil.test/path", "/../secret", "/ok?q=1"):
        try:
            normalize_health_path(blocked_path)
            assert False, f"{blocked_path} should have been rejected"
        except HTTPException as exc:
            assert exc.status_code == 422
    assert normalize_api_key_header("X-API-Key") == "x-api-key"
    try:
        normalize_api_key_header("Authorization")
        assert False, "arbitrary authentication headers must be rejected"
    except HTTPException as exc:
        assert exc.status_code == 422

    with _credential_keys():
        ciphertext = encrypt_integration_credential(
            "first-secret",
            organization_id=1,
            integration_id=9,
            auth_type="bearer",
        )
        assert decrypt_integration_credential(
            ciphertext,
            organization_id=1,
            integration_id=9,
            auth_type="bearer",
        ) == "first-secret"
        settings.integration_credential_encryption_keys = f"{SECOND_KEY},{TEST_KEY}"
        assert decrypt_integration_credential(
            ciphertext,
            organization_id=1,
            integration_id=9,
            auth_type="bearer",
        ) == "first-secret"
        tampered = ciphertext[:-1] + ("A" if ciphertext[-1] != "A" else "B")
        try:
            decrypt_integration_credential(
                tampered,
                organization_id=1,
                integration_id=9,
                auth_type="bearer",
            )
            assert False, "authenticated encryption must detect tampering"
        except IntegrationCredentialConfigurationError:
            pass

    integration = _create_integration(client, name="Blocked DNS adapter")
    with client.app.state.testing_session_local() as db:
        configuration = IntegrationAdapterConfiguration(
            organization_id=1,
            integration_id=integration["id"],
            protocol="rest_json",
            base_url="https://erp.example.test/api",
            health_path="/health",
            auth_type="none",
            timeout_seconds=5,
        )
        db.add(configuration)
        db.commit()
        db.refresh(configuration)
        db.expunge(configuration)
    monkeypatch.setattr(
        "app.services.integration_adapters.socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("10.0.0.8", 443))],
    )
    monkeypatch.setattr(
        "app.services.integration_adapters._pinned_https_get",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("blocked destinations must never reach the pinned TLS client")
        ),
    )
    result = probe_adapter_connection(configuration, None)
    assert result.status == "failed"
    assert result.error_code == "blocked_address"

    pinned_call: dict = {}
    monkeypatch.setattr(
        "app.services.integration_adapters.socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))],
    )

    def pinned_success(**kwargs):
        pinned_call.update(kwargs)
        return 200, {"odata-version": "4.0"}, b""

    monkeypatch.setattr(
        "app.services.integration_adapters._pinned_https_get",
        pinned_success,
    )
    configuration.protocol = "odata_v4"
    configuration.health_path = "/$metadata"
    result = probe_adapter_connection(configuration, None)
    assert result.status == "success"
    assert result.protocol_signal == "odata_v4_header"
    assert pinned_call["hostname"] == "erp.example.test"
    assert pinned_call["address"] == "93.184.216.34"
    assert pinned_call["target"] == "/api/$metadata"


def _create_password_user(client, name: str, role: str, password: str = PASSWORD) -> dict:
    response = client.post(
        "/api/users",
        json={
            "name": name,
            "email": f"{name}@adapter-role.test",
            "role": role,
            "password": password,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _login_headers(client, email: str, password: str = PASSWORD) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        data={"username": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_adapter_roles_reauthentication_provider_boundary_and_tenant_isolation(client):
    original = (settings.rbac_enforce, settings.legacy_header_auth)
    admin = _create_password_user(client, "adapter-admin", "admin")
    manager = _create_password_user(client, "adapter-manager", "manager")
    engineer = _create_password_user(client, "adapter-engineer", "engineer")
    with client.app.state.testing_session_local() as db:
        other_org = Organization(name="Adapter Tenant Two", slug="adapter-tenant-two")
        db.add(other_org)
        db.flush()
        other_admin = User(
            organization_id=other_org.id,
            name="adapter-other-admin",
            email="adapter-other-admin@adapter-role.test",
            role=UserRole.ADMIN,
            password_hash=hash_password(PASSWORD),
        )
        db.add(other_admin)
        db.commit()
        other_email = other_admin.email
    admin_headers = _login_headers(client, admin["email"])
    other_headers = _login_headers(client, other_email)
    try:
        settings.rbac_enforce = True
        settings.legacy_header_auth = True
        integration = _create_integration(
            client,
            name="Tenant one ERP",
            headers=admin_headers,
        )
        generic = _create_integration(
            client,
            provider="generic",
            name="Not an adapter",
            headers=admin_headers,
        )
        endpoint = f"/api/integrations/{integration['id']}/adapter"
        assert client.get(
            endpoint, headers={"X-User-Id": str(manager["id"])}
        ).status_code == 200
        assert client.get(
            endpoint, headers={"X-User-Id": str(engineer["id"])}
        ).status_code == 403
        assert client.put(
            endpoint,
            headers={"X-User-Id": str(manager["id"])},
            json={
                "expected_version": 0,
                "protocol": "rest_json",
                "base_url": "https://erp.example.test",
                "health_path": "/health",
                "auth_type": "none",
            },
        ).status_code == 403
        assert client.get(
            f"/api/integrations/{generic['id']}/adapter",
            headers=admin_headers,
        ).status_code == 422
        wrong = _adapter_payload(credential_secret="tenant-secret", account_password="wrong-password")
        assert client.put(endpoint, headers=admin_headers, json=wrong).status_code == 401
        with _credential_keys():
            correct = _adapter_payload(
                credential_secret="tenant-secret",
                account_password=PASSWORD,
            )
            saved = client.put(endpoint, headers=admin_headers, json=correct)
            assert saved.status_code == 200, saved.text

        hidden = client.get(endpoint, headers=other_headers)
        assert hidden.status_code == 404
        other = _create_integration(
            client,
            provider="wms",
            name="Tenant two WMS",
            headers=other_headers,
        )
        assert other["organization_id"] != integration["organization_id"]
        assert client.get(
            f"/api/integrations/{other['id']}/adapter", headers=admin_headers
        ).status_code == 404
    finally:
        settings.rbac_enforce, settings.legacy_header_auth = original
