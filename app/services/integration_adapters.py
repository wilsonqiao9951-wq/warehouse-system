from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import base64
import binascii
from hashlib import sha256
from http.client import HTTPException as HttpClientError, HTTPSConnection
from ipaddress import ip_address
import json
import secrets
import socket
import ssl
from time import perf_counter
from typing import Mapping
from urllib.parse import urlsplit

from Crypto.Cipher import AES
from fastapi import HTTPException

from app.core.config import Settings, settings
from app.models import IntegrationAdapterConfiguration, IntegrationConnectionTest
from app.schemas import IntegrationAdapterConfigurationRead, IntegrationConnectionTestRead


SUPPORTED_ADAPTER_PROTOCOLS = {"rest_json", "odata_v4"}
SUPPORTED_ADAPTER_AUTH_TYPES = {"none", "bearer", "basic", "api_key_header"}
_AAD_PREFIX = "OpenPartsFlow:integration-credential:v1"
_SAFE_API_KEY_HEADER_NAMES = {
    "x-api-key",
    "api-key",
    "x-auth-token",
    "x-api-token",
}


class IntegrationCredentialConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class AdapterProbeResult:
    status: str
    response_status_code: int | None
    latency_ms: int
    protocol_confirmed: bool
    protocol_signal: str
    error_code: str | None


def _configured_key_values(config: Settings = settings) -> list[str]:
    return [
        value.strip()
        for value in config.integration_credential_encryption_keys.split(",")
        if value.strip()
    ]


def integration_credential_configuration_errors(
    config: Settings = settings,
    *,
    required: bool = False,
) -> list[str]:
    errors: list[str] = []
    key_values = _configured_key_values(config)
    if required and not key_values:
        errors.append(
            "INTEGRATION_CREDENTIAL_ENCRYPTION_KEYS must contain at least one AES-256 key"
        )
    if len(set(key_values)) != len(key_values):
        errors.append("INTEGRATION_CREDENTIAL_ENCRYPTION_KEYS must not contain duplicate keys")
    for value in key_values:
        try:
            decoded = base64.b64decode(
                value.encode("ascii"), altchars=b"-_", validate=True
            )
            if len(decoded) != 32:
                raise ValueError("invalid key length")
        except (binascii.Error, UnicodeEncodeError, ValueError):
            errors.append(
                "Every INTEGRATION_CREDENTIAL_ENCRYPTION_KEYS entry must encode exactly 32 bytes as URL-safe base64"
            )
            break
    if not 1 <= config.integration_connection_timeout_seconds <= 30:
        errors.append("INTEGRATION_CONNECTION_TIMEOUT_SECONDS must be between 1 and 30")
    if not 1024 <= config.integration_connection_max_response_bytes <= 1024 * 1024:
        errors.append(
            "INTEGRATION_CONNECTION_MAX_RESPONSE_BYTES must be between 1024 and 1048576"
        )
    return errors


def _encryption_keys(config: Settings = settings) -> list[bytes]:
    errors = integration_credential_configuration_errors(config)
    values = _configured_key_values(config)
    if errors or not values:
        raise IntegrationCredentialConfigurationError(
            "Integration credential protection is not configured"
        )
    return [
        base64.b64decode(value.encode("ascii"), altchars=b"-_", validate=True)
        for value in values
    ]


def _token_segment(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_token_segment(value: str) -> bytes:
    decoded = base64.b64decode(
        (value + "=" * (-len(value) % 4)).encode("ascii"),
        altchars=b"-_",
        validate=True,
    )
    if not value or _token_segment(decoded) != value:
        raise ValueError("non-canonical encrypted credential segment")
    return decoded


def _credential_aad(
    *, organization_id: int, integration_id: int, auth_type: str
) -> bytes:
    return (
        f"{_AAD_PREFIX}:{organization_id}:{integration_id}:{auth_type}"
    ).encode("ascii")


def encrypt_integration_credential(
    secret: str,
    *,
    organization_id: int,
    integration_id: int,
    auth_type: str,
) -> str:
    if auth_type not in SUPPORTED_ADAPTER_AUTH_TYPES - {"none"}:
        raise ValueError("Credential encryption requires an authenticated adapter")
    if not secret or len(secret) > 4096:
        raise ValueError("Integration credential must contain between 1 and 4096 characters")
    nonce = secrets.token_bytes(12)
    cipher = AES.new(_encryption_keys()[0], AES.MODE_GCM, nonce=nonce, mac_len=16)
    cipher.update(
        _credential_aad(
            organization_id=organization_id,
            integration_id=integration_id,
            auth_type=auth_type,
        )
    )
    ciphertext, tag = cipher.encrypt_and_digest(secret.encode("utf-8"))
    return ".".join(
        ("v1", _token_segment(nonce), _token_segment(ciphertext), _token_segment(tag))
    )


def decrypt_integration_credential(
    ciphertext: str,
    *,
    organization_id: int,
    integration_id: int,
    auth_type: str,
) -> str:
    try:
        version, nonce_value, encrypted_value, tag_value = ciphertext.split(".")
        if version != "v1":
            raise ValueError("unsupported encrypted credential version")
        nonce = _decode_token_segment(nonce_value)
        encrypted = _decode_token_segment(encrypted_value)
        tag = _decode_token_segment(tag_value)
        if len(nonce) != 12 or len(tag) != 16 or not encrypted:
            raise ValueError("invalid encrypted credential")
    except (binascii.Error, UnicodeEncodeError, ValueError) as exc:
        raise IntegrationCredentialConfigurationError(
            "Integration credential has an invalid encrypted format"
        ) from exc
    aad = _credential_aad(
        organization_id=organization_id,
        integration_id=integration_id,
        auth_type=auth_type,
    )
    for key in _encryption_keys():
        try:
            cipher = AES.new(key, AES.MODE_GCM, nonce=nonce, mac_len=16)
            cipher.update(aad)
            return cipher.decrypt_and_verify(encrypted, tag).decode("utf-8")
        except (UnicodeDecodeError, ValueError):
            continue
    raise IntegrationCredentialConfigurationError(
        "Integration credential cannot be decrypted with the configured keys"
    )


def normalize_adapter_base_url(value: str) -> str:
    cleaned = value.strip().rstrip("/")
    parsed = urlsplit(cleaned)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise HTTPException(
            status_code=422,
            detail="Adapter base URL must be HTTPS without credentials, query, or fragment",
        )
    hostname = parsed.hostname.casefold().rstrip(".")
    try:
        parsed.port
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Adapter URL contains an invalid port") from exc
    if hostname == "localhost" or hostname.endswith((".localhost", ".local")):
        raise HTTPException(status_code=422, detail="Adapter URL cannot target a local host")
    try:
        address = ip_address(hostname)
    except ValueError:
        address = None
    if address and _address_is_blocked(address):
        raise HTTPException(
            status_code=422,
            detail="Adapter URL cannot target a private or reserved network",
        )
    return cleaned


def normalize_health_path(value: str) -> str:
    cleaned = value.strip() or "/"
    parsed = urlsplit(cleaned)
    if (
        not cleaned.startswith("/")
        or cleaned.startswith("//")
        or parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or any(segment == ".." for segment in parsed.path.split("/"))
    ):
        raise HTTPException(
            status_code=422,
            detail="Health path must be an absolute relative path without query, fragment, or traversal",
        )
    return parsed.path


def normalize_api_key_header(value: str | None) -> str | None:
    cleaned = (value or "").strip().casefold()
    if not cleaned:
        return None
    if cleaned not in _SAFE_API_KEY_HEADER_NAMES:
        raise HTTPException(
            status_code=422,
            detail="API key header must be one of X-API-Key, API-Key, X-Auth-Token, or X-API-Token",
        )
    return cleaned


def _address_is_blocked(address) -> bool:
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _adapter_url(configuration: IntegrationAdapterConfiguration) -> str:
    return (
        configuration.base_url.rstrip("/")
        + "/"
        + configuration.health_path.lstrip("/")
    )


def _connection_headers(
    configuration: IntegrationAdapterConfiguration,
    credential: str | None,
) -> dict[str, str]:
    headers = {
        "Accept": "application/json, application/xml;q=0.9, text/xml;q=0.8",
        "Accept-Encoding": "identity",
        "User-Agent": "OpenPartsFlow-ERP-WMS-Validator/1.0",
    }
    if configuration.auth_type == "bearer":
        headers["Authorization"] = f"Bearer {credential or ''}"
    elif configuration.auth_type == "basic":
        token = base64.b64encode(
            f"{configuration.auth_username or ''}:{credential or ''}".encode("utf-8")
        ).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    elif configuration.auth_type == "api_key_header":
        headers[configuration.api_key_header or "x-api-key"] = credential or ""
    return headers


def _protocol_evidence(
    protocol: str,
    headers: Mapping[str, str],
    sample: bytes,
) -> tuple[bool, str]:
    if protocol == "rest_json":
        return True, "http_2xx"
    odata_version = headers.get("odata-version", "").strip()
    lowered = sample[:65536].lower()
    if odata_version.startswith("4"):
        return True, "odata_v4_header"
    if b"<edmx:edmx" in lowered and (b'version="4.0"' in lowered or b"version='4.0'" in lowered):
        return True, "odata_v4_metadata"
    if b'"@odata.context"' in lowered:
        return True, "odata_v4_context"
    return False, "odata_v4_unconfirmed"


class _PinnedHTTPSConnection(HTTPSConnection):
    """TLS connection pinned to one pre-validated address.

    Certificate verification and SNI continue to use the configured hostname,
    while the TCP socket cannot perform a second DNS lookup and rebind to an
    internal address after the policy check.
    """

    def __init__(
        self,
        hostname: str,
        port: int,
        address: str,
        timeout: float,
    ) -> None:
        super().__init__(
            hostname,
            port=port,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
        self._pinned_address = address

    def connect(self) -> None:
        raw_socket = socket.create_connection(
            (self._pinned_address, self.port),
            self.timeout,
            self.source_address,
        )
        try:
            raw_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.sock = self._context.wrap_socket(
                raw_socket,
                server_hostname=self.host,
            )
        except Exception:
            raw_socket.close()
            raise


def _pinned_https_get(
    *,
    hostname: str,
    port: int,
    address: str,
    target: str,
    headers: dict[str, str],
    timeout: float,
    max_bytes: int,
) -> tuple[int, dict[str, str], bytes]:
    connection = _PinnedHTTPSConnection(hostname, port, address, timeout)
    try:
        connection.request("GET", target, headers=headers)
        response = connection.getresponse()
        response_headers = {
            name.casefold(): value
            for name, value in response.getheaders()
        }
        sample = response.read(max_bytes + 1)[:max_bytes]
        return response.status, response_headers, sample
    finally:
        connection.close()


def probe_adapter_connection(
    configuration: IntegrationAdapterConfiguration,
    credential: str | None,
) -> AdapterProbeResult:
    started = perf_counter()
    url = _adapter_url(configuration)
    parsed = urlsplit(url)
    hostname = parsed.hostname
    port = parsed.port or 443
    target = parsed.path or "/"
    if not hostname:
        return AdapterProbeResult("failed", None, 0, False, "none", "configuration_invalid")
    try:
        addresses = {
            row[4][0]
            for row in socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        }
    except OSError:
        return AdapterProbeResult("failed", None, 0, False, "none", "dns_resolution_failed")
    if not addresses:
        return AdapterProbeResult("failed", None, 0, False, "none", "dns_resolution_failed")
    if any(_address_is_blocked(ip_address(raw)) for raw in addresses):
        return AdapterProbeResult("failed", None, 0, False, "none", "blocked_address")
    max_bytes = settings.integration_connection_max_response_bytes
    timeout_seconds = min(
        configuration.timeout_seconds,
        settings.integration_connection_timeout_seconds,
    )
    failure_code = "connect_error"
    response_headers: dict[str, str] = {}
    sample = b""
    status_code: int | None = None
    for address in sorted(addresses):
        try:
            status_code, response_headers, sample = _pinned_https_get(
                hostname=hostname,
                port=port,
                address=address,
                target=target,
                headers=_connection_headers(configuration, credential),
                timeout=timeout_seconds,
                max_bytes=max_bytes,
            )
            break
        except (TimeoutError, socket.timeout):
            failure_code = "timeout"
        except ssl.SSLError:
            failure_code = "tls_error"
        except (HttpClientError, OSError):
            failure_code = "connect_error"
    latency_ms = max(0, round((perf_counter() - started) * 1000))
    if status_code is None:
        return AdapterProbeResult(
            "failed", None, latency_ms, False, "none", failure_code
        )
    if 300 <= status_code < 400:
        return AdapterProbeResult("failed", status_code, latency_ms, False, "none", "redirect_not_allowed")
    if not 200 <= status_code < 300:
        return AdapterProbeResult("failed", status_code, latency_ms, False, "none", "http_status")
    confirmed, signal = _protocol_evidence(
        configuration.protocol, response_headers, sample
    )
    if not confirmed:
        return AdapterProbeResult("failed", status_code, latency_ms, False, signal, "protocol_unconfirmed")
    return AdapterProbeResult("success", status_code, latency_ms, True, signal, None)


def adapter_configuration_fingerprint(
    configuration: IntegrationAdapterConfiguration,
) -> str:
    payload = {
        "protocol": configuration.protocol,
        "base_url": configuration.base_url,
        "health_path": configuration.health_path,
        "auth_type": configuration.auth_type,
        "auth_username": configuration.auth_username,
        "api_key_header": configuration.api_key_header,
        "credential_ciphertext_sha256": sha256(
            (configuration.credential_ciphertext or "").encode("utf-8")
        ).hexdigest(),
        "timeout_seconds": configuration.timeout_seconds,
        "version": configuration.version,
    }
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def connection_evidence_fingerprint(
    configuration: IntegrationAdapterConfiguration,
    result: AdapterProbeResult,
    tested_at: datetime,
    tested_by: int | None,
) -> str:
    payload = {
        "integration_id": configuration.integration_id,
        "configuration_id": configuration.id,
        "configuration_version": configuration.version,
        "configuration_fingerprint": adapter_configuration_fingerprint(configuration),
        "status": result.status,
        "response_status_code": result.response_status_code,
        "latency_ms": result.latency_ms,
        "protocol_confirmed": result.protocol_confirmed,
        "protocol_signal": result.protocol_signal,
        "error_code": result.error_code,
        "tested_by": tested_by,
        "tested_at": tested_at.isoformat(timespec="microseconds"),
    }
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def adapter_configuration_read(
    configuration: IntegrationAdapterConfiguration,
    latest_test: IntegrationConnectionTest | None = None,
) -> IntegrationAdapterConfigurationRead:
    return IntegrationAdapterConfigurationRead(
        id=configuration.id,
        persisted=True,
        organization_id=configuration.organization_id,
        integration_id=configuration.integration_id,
        protocol=configuration.protocol,
        base_url=configuration.base_url,
        health_path=configuration.health_path,
        auth_type=configuration.auth_type,
        auth_username=configuration.auth_username,
        api_key_header=configuration.api_key_header,
        has_credentials=bool(configuration.credential_ciphertext),
        credential_updated_at=configuration.credential_updated_at,
        timeout_seconds=configuration.timeout_seconds,
        version=configuration.version,
        latest_test=connection_test_read(latest_test, current_version=configuration.version)
        if latest_test
        else None,
        created_by=configuration.created_by,
        updated_by=configuration.updated_by,
        created_at=configuration.created_at,
        updated_at=configuration.updated_at,
    )


def connection_test_read(
    row: IntegrationConnectionTest,
    *,
    current_version: int | None = None,
) -> IntegrationConnectionTestRead:
    return IntegrationConnectionTestRead(
        id=row.id,
        organization_id=row.organization_id,
        integration_id=row.integration_id,
        configuration_id=row.configuration_id,
        configuration_version=row.configuration_version,
        current=(
            row.configuration_version == current_version
            if current_version is not None
            else False
        ),
        status=row.status,
        response_status_code=row.response_status_code,
        latency_ms=row.latency_ms,
        protocol_confirmed=row.protocol_confirmed,
        protocol_signal=row.protocol_signal,
        error_code=row.error_code,
        evidence_fingerprint=row.evidence_fingerprint,
        tested_by=row.tested_by,
        tested_at=row.tested_at,
    )
