from __future__ import annotations

import threading
import time
from pathlib import Path

from commercelens.alerts.config import AlertRule, MonitorConfig, MonitorTarget
from commercelens.alerts.rules import AlertCondition
from commercelens.jobs.models import (
    ApiKeyCreate,
    JobStatus,
    MonitoringJobCreate,
    MonitoringJobUpdate,
    RunStatus,
    ScheduleKind,
)
from commercelens.jobs.store import JobStore
from commercelens.jobs.worker import MonitoringWorker


def sample_config() -> MonitorConfig:
    return MonitorConfig(
        targets=[MonitorTarget(url="https://example.com/product", name="Example Product")],
        rules=[AlertRule(name="price drop", condition=AlertCondition.PRICE_DROP)],
        channels=[],
    )


def test_create_list_update_job(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.db")
    job = store.create_job(
        MonitoringJobCreate(name="watch example", config=sample_config(), interval_minutes=5)
    )

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
    job = store.create_job(
        MonitoringJobCreate(name="watch example", config=sample_config(), interval_minutes=5)
    )
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


class FakeMonitorResult:
    events = []
    warnings = []
    delivery_reports = []

    def model_dump(self, **kwargs):
        return {"events": []}


def _config_for(url: str) -> MonitorConfig:
    return MonitorConfig(
        targets=[MonitorTarget(url=url, name="Example Product")],
        rules=[AlertRule(name="price drop", condition=AlertCondition.PRICE_DROP)],
        channels=[],
    )


def _due_job(store: JobStore, name: str, url: str):
    job = store.create_job(
        MonitoringJobCreate(
            name=name,
            config=_config_for(url),
            interval_minutes=5,
        )
    )
    job.next_run_at = "2000-01-01T00:00:00+00:00"
    store.save_job(job)
    return job


def test_worker_waits_for_same_domain_capacity(monkeypatch, tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.db")
    _due_job(store, "watch one", "https://example.com/one")
    _due_job(store, "watch two", "https://example.com/two")
    lock = threading.Lock()
    active = 0
    maximum_active = 0

    def fake_run_monitor_config(*args, **kwargs):
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return FakeMonitorResult()

    monkeypatch.setattr("commercelens.jobs.worker.run_monitor_config", fake_run_monitor_config)
    result = MonitoringWorker(store=store).tick(
        limit=10,
        domain_concurrency=1,
        worker_concurrency=2,
    )

    runs = store.list_runs(limit=10)
    assert result.succeeded_runs == 2
    assert result.deferred_runs == 0
    assert maximum_active == 1
    assert {run.status for run in runs} == {RunStatus.succeeded}


def test_worker_runs_different_domains_concurrently(monkeypatch, tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.db")
    _due_job(store, "watch one", "https://one.example/product")
    _due_job(store, "watch two", "https://two.example/product")
    both_active = threading.Event()
    lock = threading.Lock()
    active = 0
    maximum_active = 0

    def fake_run_monitor_config(*args, **kwargs):
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
            if active == 2:
                both_active.set()
        assert both_active.wait(timeout=1)
        with lock:
            active -= 1
        return FakeMonitorResult()

    monkeypatch.setattr("commercelens.jobs.worker.run_monitor_config", fake_run_monitor_config)
    result = MonitoringWorker(store=store).tick(
        limit=10,
        domain_concurrency=1,
        worker_concurrency=2,
    )

    assert result.succeeded_runs == 2
    assert maximum_active == 2


def test_worker_releases_domain_capacity_after_failure(monkeypatch, tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.db")
    _due_job(store, "watch one", "https://example.com/one")
    _due_job(store, "watch two", "https://example.com/two")
    calls = 0

    def fake_run_monitor_config(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary failure")
        return FakeMonitorResult()

    monkeypatch.setattr("commercelens.jobs.worker.run_monitor_config", fake_run_monitor_config)
    result = MonitoringWorker(store=store).tick(
        limit=10,
        domain_concurrency=1,
        worker_concurrency=2,
    )

    assert result.started_runs == 2
    assert result.failed_runs == 1
    assert result.succeeded_runs == 1
    assert result.deferred_runs == 0
