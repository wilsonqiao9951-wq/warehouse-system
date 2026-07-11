from datetime import datetime, timedelta, timezone
import base64

import jwt
from jwt import InvalidTokenError
from pwdlib import PasswordHash

from app.core.config import settings


password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return False
    return password_hash.verify(password, stored_hash)


def create_access_token(user_id: int, organization_id: int) -> tuple[str, int]:
    if (
        settings.app_env.lower() in {"production", "staging"}
        and settings.jwt_secret_key == "development-only-change-me-32-bytes-minimum"
    ):
        raise RuntimeError("JWT_SECRET_KEY must be configured outside development")
    expires_in = settings.access_token_expire_minutes * 60
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": str(user_id),
            "organization_id": organization_id,
            "iat": now,
            "exp": now + timedelta(seconds=expires_in),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return token, expires_in


def decode_access_token(token: str) -> tuple[int, int]:
    try:
        # Reject non-canonical base64url segments. Without this check, changing
        # unused padding bits in the final signature character can decode to the
        # same bytes and bypass simple token-tampering checks.
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
            options={"require": ["sub", "organization_id", "exp"]},
        )
        return int(payload["sub"]), int(payload["organization_id"])
    except (InvalidTokenError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid or expired access token") from exc
