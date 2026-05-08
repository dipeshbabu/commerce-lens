from __future__ import annotations

from pathlib import Path

from commercelens.alerts.config import AlertRule, MonitorConfig, MonitorTarget
from commercelens.alerts.rules import AlertCondition
from commercelens.jobs.models import ApiKeyCreate, JobStatus, MonitoringJobCreate, MonitoringJobUpdate, ScheduleKind
from commercelens.jobs.store import JobStore


def sample_config() -> MonitorConfig:
    return MonitorConfig(
        targets=[MonitorTarget(url="https://example.com/product", name="Example Product")],
        rules=[AlertRule(name="price drop", condition=AlertCondition.PRICE_DROP)],
        channels=[],
    )


def test_create_list_update_job(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.db")
    job = store.create_job(MonitoringJobCreate(name="watch example", config=sample_config(), interval_minutes=5))

    assert job.id.startswith("job_")
    assert job.next_run_at is not None
    assert store.get_job(job.id) is not None
    assert len(store.list_jobs()) == 1

    updated = store.update_job(job.id, MonitoringJobUpdate(status=JobStatus.paused))
    assert updated is not None
    assert updated.status == JobStatus.paused
    assert updated.next_run_at is None


def test_manual_job_has_no_next_run(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.db")
    job = store.create_job(
        MonitoringJobCreate(
            name="manual watch",
            config=sample_config(),
            schedule_kind=ScheduleKind.manual,
            interval_minutes=5,
        )
    )
    assert job.next_run_at is None
    assert store.due_jobs() == []


def test_claim_due_job_runs_prevents_duplicate_claims(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.db")
    job = store.create_job(MonitoringJobCreate(name="watch example", config=sample_config(), interval_minutes=5))
    job.next_run_at = "2000-01-01T00:00:00+00:00"
    store.save_job(job)

    first_claims = store.claim_due_job_runs(limit=10)
    second_claims = store.claim_due_job_runs(limit=10)

    assert len(first_claims) == 1
    claimed_job, run = first_claims[0]
    assert claimed_job.id == job.id
    assert run.job_id == job.id
    assert store.get_job(job.id).next_run_at is None  # type: ignore[union-attr]
    assert store.get_run(run.id) is not None
    assert second_claims == []


def test_api_key_roundtrip(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.db")
    result = store.create_api_key(ApiKeyCreate(name="local dev"))
    assert result.token.startswith("cl_")
    verified = store.verify_api_key(result.token)
    assert verified is not None
    assert verified.name == "local dev"
