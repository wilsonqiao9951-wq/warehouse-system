from __future__ import annotations

from ipaddress import ip_address
import re
from urllib.parse import urlsplit

import httpx

from app.core.config import settings


_DOMAIN_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_RESERVED_SUFFIXES = (
    ".example",
    ".invalid",
    ".local",
    ".localhost",
    ".test",
)


def normalize_custom_domain(value: str) -> str:
    candidate = value.strip().casefold().rstrip(".")
    if not candidate or any(character in candidate for character in "/:@?#\\"):
        raise ValueError("Enter a hostname without a scheme, port, path, or query")
    try:
        candidate = candidate.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("Domain name is not valid IDNA") from exc
    if len(candidate) > 253:
        raise ValueError("Domain name is too long")
    labels = candidate.split(".")
    if len(labels) < 2 or any(not _DOMAIN_LABEL.fullmatch(label) for label in labels):
        raise ValueError("Enter a valid public domain name")
    try:
        ip_address(candidate)
    except ValueError:
        pass
    else:
        raise ValueError("IP addresses cannot be used as custom domains")
    if candidate in {"localhost", "local"} or candidate.endswith(_RESERVED_SUFFIXES):
        raise ValueError("Reserved or local domains cannot be used")
    if len(f"_openpartsflow-challenge.{candidate}") > 253:
        raise ValueError("Domain name is too long for the verification record")
    return candidate


def _txt_value(data: object) -> str:
    value = str(data or "").strip()
    quoted = re.findall(r'"((?:\\.|[^"\\])*)"', value)
    if quoted:
        return "".join(quoted).replace(r'\"', '"').replace(r"\\", "\\")
    return value


async def lookup_txt_records(name: str) -> tuple[set[str], str | None]:
    """Resolve TXT data through the operator-controlled fixed DoH endpoint."""
    resolver_url = settings.custom_domain_dns_resolver_url
    try:
        parsed = urlsplit(resolver_url)
        valid_resolver = (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
        )
        _ = parsed.port
    except ValueError:
        valid_resolver = False
    if not valid_resolver:
        return set(), "DNS verification service is not configured safely."
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(5.0),
            follow_redirects=False,
        ) as client:
            response = await client.get(
                resolver_url,
                params={"name": name, "type": "TXT"},
                headers={"Accept": "application/dns-json"},
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError):
        return set(), "DNS verification service is temporarily unavailable."
    if not isinstance(payload, dict) or payload.get("Status") != 0:
        return set(), "The DNS resolver did not return a successful answer."
    answers = payload.get("Answer")
    if not isinstance(answers, list):
        return set(), None
    records = {
        _txt_value(answer.get("data"))
        for answer in answers
        if isinstance(answer, dict) and answer.get("type") == 16
    }
    return {record for record in records if record}, None
