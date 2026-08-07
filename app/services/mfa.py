from __future__ import annotations

from datetime import datetime, timedelta, timezone
import base64
import binascii
from hashlib import sha1, sha256
import hmac
import json
import secrets
import struct
from urllib.parse import quote, urlencode

from Crypto.Cipher import AES
import jwt
from jwt import InvalidTokenError

from app.core.config import Settings, settings
from app.models import User


TOTP_DIGITS = 6
TOTP_PERIOD_SECONDS = 30
TOTP_ALLOWED_DRIFT_STEPS = 1
RECOVERY_CODE_COUNT = 10
RECOVERY_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


class MfaConfigurationError(RuntimeError):
    pass


def _configured_key_values(config: Settings = settings) -> list[str]:
    return [value.strip() for value in config.mfa_encryption_keys.split(",") if value.strip()]


def mfa_configuration_errors(config: Settings = settings, *, required: bool = False) -> list[str]:
    errors: list[str] = []
    key_values = _configured_key_values(config)
    if required and not key_values:
        errors.append("MFA_ENCRYPTION_KEYS must contain at least one AES-256 key")
    if len(set(key_values)) != len(key_values):
        errors.append("MFA_ENCRYPTION_KEYS must not contain duplicate keys")
    for value in key_values:
        try:
            decoded = base64.b64decode(value.encode("ascii"), altchars=b"-_", validate=True)
            if len(decoded) != 32:
                raise ValueError("invalid key length")
        except (binascii.Error, UnicodeEncodeError, ValueError):
            errors.append("Every MFA_ENCRYPTION_KEYS entry must encode exactly 32 bytes as URL-safe base64")
            break
    if not 1 <= config.mfa_challenge_expire_minutes <= 15:
        errors.append("MFA_CHALLENGE_EXPIRE_MINUTES must be between 1 and 15")
    if not 2 <= config.mfa_enrollment_expire_minutes <= 60:
        errors.append("MFA_ENROLLMENT_EXPIRE_MINUTES must be between 2 and 60")
    if not 3 <= config.mfa_max_attempts <= 10:
        errors.append("MFA_MAX_ATTEMPTS must be between 3 and 10")
    return errors


def mfa_is_available(config: Settings = settings) -> bool:
    return not mfa_configuration_errors(config) and bool(_configured_key_values(config))


def _encryption_keys(config: Settings = settings) -> list[bytes]:
    errors = mfa_configuration_errors(config)
    if errors or not _configured_key_values(config):
        raise MfaConfigurationError("MFA secret protection is not configured")
    return [
        base64.b64decode(value.encode("ascii"), altchars=b"-_", validate=True)
        for value in _configured_key_values(config)
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
        raise ValueError("non-canonical encrypted secret segment")
    return decoded


def generate_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def encrypt_totp_secret(secret: str) -> str:
    nonce = secrets.token_bytes(12)
    cipher = AES.new(_encryption_keys()[0], AES.MODE_GCM, nonce=nonce, mac_len=16)
    cipher.update(b"OpenPartsFlow:mfa-secret:v1")
    ciphertext, tag = cipher.encrypt_and_digest(secret.encode("ascii"))
    return ".".join(("v1", _token_segment(nonce), _token_segment(ciphertext), _token_segment(tag)))


def decrypt_totp_secret(ciphertext: str) -> str:
    try:
        version, nonce_value, encrypted_value, tag_value = ciphertext.split(".")
        if version != "v1":
            raise ValueError("unsupported encrypted secret version")
        nonce = _decode_token_segment(nonce_value)
        encrypted = _decode_token_segment(encrypted_value)
        tag = _decode_token_segment(tag_value)
        if len(nonce) != 12 or len(tag) != 16 or not encrypted:
            raise ValueError("invalid encrypted secret")
    except (binascii.Error, UnicodeEncodeError, ValueError) as exc:
        raise MfaConfigurationError("MFA secret has an invalid encrypted format") from exc
    for key in _encryption_keys():
        try:
            cipher = AES.new(key, AES.MODE_GCM, nonce=nonce, mac_len=16)
            cipher.update(b"OpenPartsFlow:mfa-secret:v1")
            return cipher.decrypt_and_verify(encrypted, tag).decode("ascii")
        except (UnicodeDecodeError, ValueError):
            continue
    raise MfaConfigurationError("MFA secret cannot be decrypted with the configured keys")


def provisioning_uri(*, secret: str, email: str, issuer: str = "OpenPartsFlow") -> str:
    label = quote(f"{issuer}:{email}", safe="")
    query = urlencode(
        {
            "secret": secret,
            "issuer": issuer,
            "algorithm": "SHA1",
            "digits": str(TOTP_DIGITS),
            "period": str(TOTP_PERIOD_SECONDS),
        }
    )
    return f"otpauth://totp/{label}?{query}"


def _secret_bytes(secret: str) -> bytes:
    normalized = secret.strip().replace(" ", "").upper()
    return base64.b32decode(normalized + "=" * (-len(normalized) % 8), casefold=True)


def totp_code(secret: str, *, step: int | None = None, at: datetime | None = None) -> str:
    if step is None:
        instant = at or datetime.now(timezone.utc)
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=timezone.utc)
        step = int(instant.timestamp()) // TOTP_PERIOD_SECONDS
    digest = hmac.new(_secret_bytes(secret), struct.pack(">Q", step), sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10**TOTP_DIGITS)).zfill(TOTP_DIGITS)


def matching_totp_step(secret: str, code: str, *, now: datetime | None = None) -> int | None:
    normalized = code.strip().replace(" ", "")
    if len(normalized) != TOTP_DIGITS or not normalized.isdigit():
        return None
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    current_step = int(instant.timestamp()) // TOTP_PERIOD_SECONDS
    matched: int | None = None
    for offset in range(-TOTP_ALLOWED_DRIFT_STEPS, TOTP_ALLOWED_DRIFT_STEPS + 1):
        candidate_step = current_step + offset
        if hmac.compare_digest(totp_code(secret, step=candidate_step), normalized):
            matched = candidate_step
    return matched


def generate_recovery_codes() -> list[str]:
    return [
        "-".join(
            "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(4))
            for _ in range(3)
        )
        for _ in range(RECOVERY_CODE_COUNT)
    ]


def recovery_code_hash(code: str) -> str:
    normalized = code.strip().replace("-", "").replace(" ", "").upper()
    return sha256(f"openpartsflow-mfa-recovery:{normalized}".encode("ascii")).hexdigest()


def encode_recovery_code_hashes(codes: list[str]) -> str:
    return json.dumps([recovery_code_hash(code) for code in codes], separators=(",", ":"))


def decode_recovery_code_hashes(value: str | None) -> list[str]:
    try:
        rows = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, str) and len(row) == 64]


def create_mfa_challenge_token(user: User) -> tuple[str, int]:
    expires_in = settings.mfa_challenge_expire_minutes * 60
    now = datetime.now(timezone.utc)
    payload = {
        "purpose": "mfa_login",
        "sub": str(user.id),
        "organization_id": user.organization_id,
        "credential_version": user.auth_version,
        "jti": secrets.token_urlsafe(18),
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm), expires_in


def decode_mfa_challenge_token(token: str) -> tuple[int, int, int]:
    try:
        segments = token.split(".")
        if len(segments) != 3 or any(not segment for segment in segments):
            raise InvalidTokenError("Malformed token")
        for segment in segments:
            padded = segment + "=" * (-len(segment) % 4)
            canonical = base64.urlsafe_b64encode(base64.urlsafe_b64decode(padded)).rstrip(b"=").decode("ascii")
            if canonical != segment:
                raise InvalidTokenError("Non-canonical token")
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={
                "require": [
                    "purpose",
                    "sub",
                    "organization_id",
                    "credential_version",
                    "jti",
                    "exp",
                ]
            },
        )
        if payload["purpose"] != "mfa_login":
            raise ValueError("Invalid MFA challenge purpose")
        return int(payload["sub"]), int(payload["organization_id"]), int(payload["credential_version"])
    except (InvalidTokenError, KeyError, TypeError, ValueError, binascii.Error) as exc:
        raise ValueError("Invalid or expired MFA challenge") from exc
