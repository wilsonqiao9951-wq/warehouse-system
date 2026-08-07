from __future__ import annotations

from hashlib import sha256
import secrets

from fastapi import HTTPException, Request, Response

from app.core.config import settings


SESSION_MODE_HEADER = "cookie"
DEVELOPMENT_SESSION_COOKIE = "opf_session"
SECURE_SESSION_COOKIE = "__Host-opf_session"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def _secure_cookie_environment() -> bool:
    return settings.app_env.strip().lower() in {"production", "staging"}


def browser_session_cookie_name() -> str:
    return SECURE_SESSION_COOKIE if _secure_cookie_environment() else DEVELOPMENT_SESSION_COOKIE


def wants_browser_session(session_mode: str | None) -> bool:
    if session_mode is None or not session_mode.strip():
        return False
    normalized = session_mode.strip().lower()
    if normalized not in {"bearer", SESSION_MODE_HEADER}:
        raise HTTPException(status_code=400, detail="X-Session-Mode must be bearer or cookie")
    return normalized == SESSION_MODE_HEADER


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def set_browser_session(response: Response, token: str, expires_in: int) -> None:
    response.set_cookie(
        key=browser_session_cookie_name(),
        value=token,
        max_age=expires_in,
        path="/",
        secure=_secure_cookie_environment(),
        httponly=True,
        samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def clear_browser_session(response: Response) -> None:
    # Clear both names so an environment transition cannot leave an older
    # session cookie active in the browser.
    response.delete_cookie(
        DEVELOPMENT_SESSION_COOKIE,
        path="/",
        secure=False,
        httponly=True,
        samesite="strict",
    )
    response.delete_cookie(
        SECURE_SESSION_COOKIE,
        path="/",
        secure=True,
        httponly=True,
        samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"


def browser_session_token(request: Request) -> str | None:
    return request.cookies.get(browser_session_cookie_name())


def require_csrf_proof(
    request: Request,
    *,
    expected_hash: str | None,
    submitted_token: str | None,
) -> None:
    if expected_hash is None:
        raise HTTPException(status_code=401, detail="Browser session is invalid")
    if request.method.upper() in SAFE_METHODS:
        return
    submitted_hash = (
        sha256(submitted_token.encode("utf-8")).hexdigest()
        if submitted_token
        else ""
    )
    if not secrets.compare_digest(expected_hash, submitted_hash):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
