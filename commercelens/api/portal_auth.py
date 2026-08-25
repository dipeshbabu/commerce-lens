from __future__ import annotations

import os
import secrets
from dataclasses import dataclass

from fastapi import HTTPException, Request, status
from starlette.responses import Response

from commercelens.api.auth import require_account_active
from commercelens.api.quota import require_scope
from commercelens.jobs.models import ApiKeyRecord, PortalSessionRecord
from commercelens.jobs.store import JobStore


SESSION_COOKIE_NAME = "__Host-cl-id"
CSRF_COOKIE_NAME = "__Host-cl-csrf"
LOGIN_CSRF_COOKIE_NAME = "__Host-cl-login-csrf"
DEFAULT_ABSOLUTE_TIMEOUT_SECONDS = 8 * 60 * 60
DEFAULT_IDLE_TIMEOUT_SECONDS = 30 * 60
MAX_SESSION_TIMEOUT_SECONDS = 7 * 24 * 60 * 60
LOGIN_CSRF_TIMEOUT_SECONDS = 10 * 60
PORTAL_SCOPES = ("usage:read", "jobs:read", "runs:read", "extractions:read")


@dataclass(frozen=True)
class PortalSessionContext:
    key: ApiKeyRecord
    session: PortalSessionRecord
    csrf_token: str


def _timeout_setting(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer number of seconds.") from exc
    if not 60 <= value <= MAX_SESSION_TIMEOUT_SECONDS:
        raise RuntimeError(f"{name} must be between 60 and {MAX_SESSION_TIMEOUT_SECONDS} seconds.")
    return value


def absolute_timeout_seconds() -> int:
    return _timeout_setting(
        "COMMERCELENS_PORTAL_SESSION_TIMEOUT_SECONDS",
        DEFAULT_ABSOLUTE_TIMEOUT_SECONDS,
    )


def idle_timeout_seconds() -> int:
    return _timeout_setting(
        "COMMERCELENS_PORTAL_IDLE_TIMEOUT_SECONDS",
        DEFAULT_IDLE_TIMEOUT_SECONDS,
    )


def authenticate_portal_api_key(store: JobStore, token: str) -> ApiKeyRecord:
    key = store.verify_api_key(token)
    if not key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid portal credentials.",
        )
    require_account_active(store, key)
    for scope in PORTAL_SCOPES:
        require_scope(key, scope)
    return key


def require_portal_session(request: Request, store: JobStore) -> PortalSessionContext:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    csrf_token = request.cookies.get(CSRF_COOKIE_NAME)
    if not token or not csrf_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Portal sign in required.",
        )
    session = store.verify_portal_session(token, idle_timeout_seconds=idle_timeout_seconds())
    if not session or not store.verify_portal_csrf(session, csrf_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Portal session expired or invalid.",
        )
    key = store.get_api_key(session.api_key_id)
    if not key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Portal session expired or invalid.",
        )
    require_account_active(store, key)
    for scope in PORTAL_SCOPES:
        require_scope(key, scope)
    if key.account_id != session.account_id or key.project_id != session.project_id:
        store.revoke_portal_session(session.id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Portal session expired or invalid.",
        )
    return PortalSessionContext(key=key, session=session, csrf_token=csrf_token)


def require_portal_csrf(
    store: JobStore,
    context: PortalSessionContext,
    submitted_token: str | None,
) -> None:
    if not submitted_token or not store.verify_portal_csrf(context.session, submitted_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid CSRF token.",
        )


def new_login_csrf_token() -> str:
    return f"login_csrf_{secrets.token_urlsafe(32)}"


def require_login_csrf(request: Request, submitted_token: str | None) -> None:
    cookie_token = request.cookies.get(LOGIN_CSRF_COOKIE_NAME)
    if (
        not cookie_token
        or not submitted_token
        or not secrets.compare_digest(cookie_token, submitted_token)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid login CSRF token.",
        )


def set_login_csrf_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        LOGIN_CSRF_COOKIE_NAME,
        token,
        max_age=LOGIN_CSRF_TIMEOUT_SECONDS,
        path="/",
        secure=True,
        httponly=True,
        samesite="strict",
    )
    set_private_response_headers(response)


def clear_login_csrf_cookie(response: Response) -> None:
    response.delete_cookie(
        LOGIN_CSRF_COOKIE_NAME,
        path="/",
        secure=True,
        httponly=True,
        samesite="strict",
    )


def set_portal_cookies(response: Response, token: str, csrf_token: str, max_age: int) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=max_age,
        path="/",
        secure=True,
        httponly=True,
        samesite="strict",
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        csrf_token,
        max_age=max_age,
        path="/",
        secure=True,
        httponly=True,
        samesite="strict",
    )
    clear_login_csrf_cookie(response)
    set_private_response_headers(response)


def clear_portal_cookies(response: Response) -> None:
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/",
        secure=True,
        httponly=True,
        samesite="strict",
    )
    response.delete_cookie(
        CSRF_COOKIE_NAME,
        path="/",
        secure=True,
        httponly=True,
        samesite="strict",
    )
    response.headers["Clear-Site-Data"] = '"cache", "cookies", "storage"'
    set_private_response_headers(response)


def set_private_response_headers(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
        "base-uri 'none'; frame-ancestors 'none'"
    )
