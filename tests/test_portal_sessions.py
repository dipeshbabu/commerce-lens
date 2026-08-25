from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from commercelens.api.main import app
from commercelens.api.portal_auth import (
    CSRF_COOKIE_NAME,
    LOGIN_CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    absolute_timeout_seconds,
    idle_timeout_seconds,
)
from commercelens.jobs.models import ApiKeyCreate
from commercelens.jobs.store import JobStore


def create_portal_key(store: JobStore):
    return store.create_api_key(
        ApiKeyCreate(
            name="portal",
            account_id="acct_portal",
            project_id="proj_portal",
            scopes=["*"],
        )
    )


def test_portal_session_tokens_are_hashed_and_support_lifecycle(tmp_path) -> None:
    store = JobStore(tmp_path / "jobs.db")
    key = create_portal_key(store)

    created = store.create_portal_session(key.key)

    assert created.token.startswith("ps_")
    assert created.csrf_token.startswith("csrf_")
    assert created.session.token_hash != created.token
    assert created.session.csrf_token_hash != created.csrf_token
    with sqlite3.connect(store.path) as connection:
        row = connection.execute(
            "SELECT token_hash, csrf_token_hash, payload FROM portal_sessions WHERE id = ?",
            (created.session.id,),
        ).fetchone()
    assert row is not None
    assert created.token not in "".join(row)
    assert created.csrf_token not in "".join(row)

    verified = store.verify_portal_session(created.token)
    assert verified is not None
    assert verified.id == created.session.id
    assert store.verify_portal_csrf(verified, created.csrf_token)
    assert not store.verify_portal_csrf(verified, "csrf_invalid")

    rotated = store.rotate_portal_session(verified, key.key)
    assert store.verify_portal_session(created.token) is None
    assert store.verify_portal_session(rotated.token) is not None
    assert store.revoke_portal_session(rotated.session.id)
    assert store.verify_portal_session(rotated.token) is None


def test_portal_sessions_enforce_absolute_idle_and_key_expiry(tmp_path) -> None:
    store = JobStore(tmp_path / "jobs.db")
    key = create_portal_key(store)
    now = datetime.now(timezone.utc).replace(microsecond=0)

    absolute = store.create_portal_session(key.key)
    absolute.session.expires_at = (now - timedelta(seconds=1)).isoformat()
    store.save_portal_session(absolute.session)
    assert store.verify_portal_session(absolute.token) is None

    idle = store.create_portal_session(key.key)
    idle.session.last_seen_at = (now - timedelta(minutes=31)).isoformat()
    store.save_portal_session(idle.session)
    assert store.verify_portal_session(idle.token, idle_timeout_seconds=1_800) is None

    disabled = store.create_portal_session(key.key)
    key.key.disabled = True
    store.save_api_key(key.key)
    assert store.verify_portal_session(disabled.token) is None


def test_portal_timeout_settings_are_bounded(monkeypatch) -> None:
    monkeypatch.setenv("COMMERCELENS_PORTAL_SESSION_TIMEOUT_SECONDS", "3600")
    monkeypatch.setenv("COMMERCELENS_PORTAL_IDLE_TIMEOUT_SECONDS", "600")

    assert absolute_timeout_seconds() == 3600
    assert idle_timeout_seconds() == 600

    monkeypatch.setenv("COMMERCELENS_PORTAL_IDLE_TIMEOUT_SECONDS", "59")
    with pytest.raises(RuntimeError, match="between 60"):
        idle_timeout_seconds()

    monkeypatch.setenv("COMMERCELENS_PORTAL_IDLE_TIMEOUT_SECONDS", "invalid")
    with pytest.raises(RuntimeError, match="integer"):
        idle_timeout_seconds()


def test_portal_login_rotation_and_logout_require_csrf(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "jobs.db"
    monkeypatch.setenv("COMMERCELENS_JOBS_DB", str(db_path))
    key = create_portal_key(JobStore(db_path))
    client = TestClient(app, base_url="https://testserver")

    login_page = client.get("/portal/login")
    login_csrf = login_page.cookies[LOGIN_CSRF_COOKIE_NAME]
    assert login_page.status_code == 200
    assert key.token not in login_page.text
    assert client.post("/portal/login", data={"api_key": key.token}).status_code == 403
    assert (
        client.post(
            "/portal/login",
            data={"api_key": key.token, "csrf_token": "login_csrf_invalid"},
        ).status_code
        == 403
    )

    login = client.post(
        "/portal/login",
        data={"api_key": key.token, "csrf_token": login_csrf},
        follow_redirects=False,
    )
    assert login.status_code == 303
    old_session = client.cookies[SESSION_COOKIE_NAME]
    old_csrf = client.cookies[CSRF_COOKIE_NAME]

    assert client.post("/portal/session/rotate").status_code == 403
    assert (
        client.post(
            "/portal/session/rotate",
            data={"csrf_token": "csrf_invalid"},
        ).status_code
        == 403
    )
    rotate = client.post(
        "/portal/session/rotate",
        data={"csrf_token": old_csrf},
        follow_redirects=False,
    )
    assert rotate.status_code == 303
    assert client.cookies[SESSION_COOKIE_NAME] != old_session
    assert client.cookies[CSRF_COOKIE_NAME] != old_csrf

    stale_client = TestClient(app, base_url="https://testserver")
    stale_client.cookies.set(SESSION_COOKIE_NAME, old_session)
    stale_client.cookies.set(CSRF_COOKIE_NAME, old_csrf)
    assert stale_client.get("/portal").status_code == 401

    current_session = client.cookies[SESSION_COOKIE_NAME]
    logout = client.post(
        "/portal/logout",
        data={"csrf_token": client.cookies[CSRF_COOKIE_NAME]},
        follow_redirects=False,
    )
    assert logout.status_code == 303
    assert logout.headers["location"] == "/portal/login"
    assert logout.headers["clear-site-data"] == '"cache", "cookies", "storage"'

    signed_out = TestClient(app, base_url="https://testserver")
    signed_out.cookies.set(SESSION_COOKIE_NAME, current_session)
    signed_out.cookies.set(CSRF_COOKIE_NAME, "csrf_invalid")
    assert signed_out.get("/portal").status_code == 401
