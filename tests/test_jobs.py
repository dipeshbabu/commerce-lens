from __future__ import annotations

from pathlib import Path

from commercelens.alerts.config import AlertRule, MonitorConfig, MonitorTarget
from commercelens.jobs.models import JobStatus, MonitoringJobCreate, MonitoringJobUpdate, ScheduleKind
from commercelens.jobs.store import JobStore


def sample_config() -> MonitorConfig:
    return MonitorConfig(
        targets=[MonitorTarget(url="https://example.com/product", name="Example Product")],
        rules=[AlertRule(type="price_drop", threshold_percent=5)],
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


def test_api_key_roundtrip(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.db")
    result = store.create_api_key(request={"name": "local dev"})  # type: ignore[arg-type]
    assert result.token.startswith("cl_")
    verified = store.verify_api_key(result.token)
    assert verified is not None
    assert verified.name == "local dev"
