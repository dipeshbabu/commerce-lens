from __future__ import annotations

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from commercelens.alerts.config import MonitorConfig, MonitorTarget
from commercelens.alerts.rules import AlertCondition, AlertRule
from commercelens.api.main import app
from commercelens.api.portal_auth import CSRF_COOKIE_NAME, LOGIN_CSRF_COOKIE_NAME
from commercelens.jobs.models import (
    AccountCreate,
    AccountStatus,
    ApiKeyCreate,
    JobStatus,
    MonitoringJobCreate,
    ProjectCreate,
    RunStatus,
)
from commercelens.jobs.postgres_store import PostgresJobStore


POSTGRES_DSN = os.getenv("COMMERCELENS_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(
    not POSTGRES_DSN,
    reason="COMMERCELENS_TEST_POSTGRES_DSN is not configured.",
)


def test_postgres_migrations_and_tenant_store_round_trip() -> None:
    import psycopg
    from psycopg import sql

    assert POSTGRES_DSN is not None
    schema = f"cl_test_{uuid4().hex}"
    with psycopg.connect(POSTGRES_DSN, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))

    separator = "&" if "?" in POSTGRES_DSN else "?"
    scoped_dsn = f"{POSTGRES_DSN}{separator}options=-csearch_path%3D{schema}"
    try:
        store = PostgresJobStore(scoped_dsn)
        assert store.migrate() == []

        account = store.create_account(AccountCreate(name="Integration Account"))
        project = store.create_project(account.id, ProjectCreate(name="Competitor Watch"))
        key = store.create_api_key(
            ApiKeyCreate(
                name="Integration key",
                account_id=account.id,
                project_id=project.id,
                scopes=["*"],
            )
        )
        assert store.verify_api_key(key.token) is not None
        session = store.create_portal_session(key.key)
        verified_session = store.verify_portal_session(session.token)
        assert verified_session is not None
        assert verified_session.account_id == account.id
        assert store.verify_portal_csrf(verified_session, session.csrf_token)
        rotated_session = store.rotate_portal_session(verified_session, key.key)
        assert store.verify_portal_session(session.token) is None
        assert store.verify_portal_session(rotated_session.token) is not None

        config = MonitorConfig(
            targets=[MonitorTarget(url="https://example.com/product")],
            rules=[AlertRule(name="Price drop", condition=AlertCondition.PRICE_DROP)],
            channels=[],
        )
        job = store.create_job(
            MonitoringJobCreate(
                name="Integration monitor",
                config=config,
                interval_minutes=5,
                account_id=account.id,
                project_id=project.id,
            )
        )
        job.next_run_at = "2000-01-01T00:00:00+00:00"
        store.save_job(job)

        claims = store.claim_due_job_runs(limit=10)
        assert len(claims) == 1
        claimed_job, run = claims[0]
        assert claimed_job.id == job.id
        assert store.get_job(job.id, account_id="acct_other") is None

        completed = store.complete_run(
            run,
            result={"events": []},
            event_count=0,
            delivery_count=0,
            warning_count=0,
        )
        assert completed.status == RunStatus.succeeded
        assert store.get_run(run.id, account_id=account.id) is not None
        assert store.get_run(run.id, account_id="acct_other") is None
    finally:
        with psycopg.connect(POSTGRES_DSN, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_postgres_portal_monitor_management_round_trip(monkeypatch) -> None:
    import psycopg
    from psycopg import sql

    assert POSTGRES_DSN is not None
    schema = f"cl_portal_{uuid4().hex}"
    with psycopg.connect(POSTGRES_DSN, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))

    separator = "&" if "?" in POSTGRES_DSN else "?"
    scoped_dsn = f"{POSTGRES_DSN}{separator}options=-csearch_path%3D{schema}"
    try:
        store = PostgresJobStore(scoped_dsn)
        assert store.migrate() == []
        account = store.create_account(
            AccountCreate(name="Portal Account", status=AccountStatus.active)
        )
        project = store.create_project(account.id, ProjectCreate(name="Portal Project"))
        key = store.create_api_key(
            ApiKeyCreate(
                name="Portal key",
                account_id=account.id,
                project_id=project.id,
                scopes=["*"],
            )
        )
        job = store.create_job(
            MonitoringJobCreate(
                name="Portal monitor",
                config=MonitorConfig(
                    targets=[MonitorTarget(url="https://example.com/portal-product")]
                ),
                account_id=account.id,
                project_id=project.id,
            )
        )

        monkeypatch.setenv("COMMERCELENS_STORE_BACKEND", "postgres")
        monkeypatch.setenv("COMMERCELENS_DATABASE_URL", scoped_dsn)
        client = TestClient(app, base_url="https://testserver")
        login_page = client.get("/portal/login")
        login_csrf = login_page.cookies[LOGIN_CSRF_COOKIE_NAME]
        login = client.post(
            "/portal/login",
            data={"api_key": key.token, "csrf_token": login_csrf},
            follow_redirects=False,
        )
        assert login.status_code == 303
        csrf = client.cookies[CSRF_COOKIE_NAME]

        paused = client.post(
            f"/portal/manage/jobs/{job.id}/pause",
            data={"csrf_token": csrf, "project_id": project.id},
            follow_redirects=False,
        )
        assert paused.status_code == 303

        reloaded = PostgresJobStore(scoped_dsn)
        assert reloaded.get_job(job.id, account_id=account.id, project_id=project.id).status == (
            JobStatus.paused
        )
        audited_project = reloaded.get_project(project.id, account_id=account.id)
        assert audited_project is not None
        assert any(
            event.get("operation") == "portal_monitor_pause"
            for event in audited_project.metadata.get("portal_audit_events", [])
        )
    finally:
        with psycopg.connect(POSTGRES_DSN, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
