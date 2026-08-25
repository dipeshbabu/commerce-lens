from __future__ import annotations

import os
from uuid import uuid4

import pytest

from commercelens.alerts.config import MonitorConfig, MonitorTarget
from commercelens.alerts.rules import AlertCondition, AlertRule
from commercelens.jobs.models import (
    AccountCreate,
    ApiKeyCreate,
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
