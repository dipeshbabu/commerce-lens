from __future__ import annotations

import time
from pathlib import Path

from commercelens.alerts.runner import run_monitor_config
from commercelens.jobs.models import JobRun, WorkerTickResult
from commercelens.jobs.store import JobStore


class MonitoringWorker:
    def __init__(self, store: JobStore | None = None, store_path: str | Path = "commercelens_jobs.db") -> None:
        self.store = store or JobStore(store_path)

    def tick(self, limit: int = 25, dry_run: bool = False, deliver: bool = True) -> WorkerTickResult:
        result = WorkerTickResult()
        due_jobs = self.store.due_jobs(limit=limit)
        result.due_jobs = len(due_jobs)

        for job in due_jobs:
            run = self.store.mark_job_run_started(job)
            result.started_runs += 1
            result.run_ids.append(run.id)
            try:
                monitor_result = run_monitor_config(job.config, dry_run=dry_run, deliver=deliver)
                delivery_count = sum(len(report.results) for report in monitor_result.delivery_reports)
                self.store.complete_run(
                    run,
                    result=monitor_result.model_dump(mode="json", exclude_none=True),
                    event_count=len(monitor_result.events),
                    delivery_count=delivery_count,
                    warning_count=len(monitor_result.warnings),
                )
                result.succeeded_runs += 1
            except Exception as exc:  # pragma: no cover - exercised through integration tests/mocks
                self.store.fail_run(run, str(exc))
                result.failed_runs += 1
                result.warnings.append(f"{job.id}: {exc}")

        return result

    def run_forever(
        self,
        poll_seconds: int = 60,
        limit: int = 25,
        dry_run: bool = False,
        deliver: bool = True,
        max_ticks: int | None = None,
    ) -> list[WorkerTickResult]:
        results: list[WorkerTickResult] = []
        ticks = 0
        while True:
            results.append(self.tick(limit=limit, dry_run=dry_run, deliver=deliver))
            ticks += 1
            if max_ticks is not None and ticks >= max_ticks:
                return results
            time.sleep(poll_seconds)


def run_job_now(store: JobStore, job_id: str, dry_run: bool = False, deliver: bool = True) -> JobRun:
    job = store.get_job(job_id)
    if not job:
        raise ValueError(f"Job not found: {job_id}")
    run = store.mark_job_run_started(job)
    try:
        monitor_result = run_monitor_config(job.config, dry_run=dry_run, deliver=deliver)
        delivery_count = sum(len(report.results) for report in monitor_result.delivery_reports)
        return store.complete_run(
            run,
            result=monitor_result.model_dump(mode="json", exclude_none=True),
            event_count=len(monitor_result.events),
            delivery_count=delivery_count,
            warning_count=len(monitor_result.warnings),
        )
    except Exception as exc:
        return store.fail_run(run, str(exc))
