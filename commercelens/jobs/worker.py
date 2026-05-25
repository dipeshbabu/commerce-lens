from __future__ import annotations

import time
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from commercelens.alerts.runner import run_monitor_config
from commercelens.jobs.models import JobRun, WorkerTickResult
from commercelens.jobs.store import JobStore


class MonitoringWorker:
    def __init__(self, store: Any | None = None, store_path: str | Path = "commercelens_jobs.db") -> None:
        self.store = store or JobStore(store_path)

    def tick(self, limit: int = 25, dry_run: bool = False, deliver: bool = True, domain_concurrency: int | None = None) -> WorkerTickResult:
        result = WorkerTickResult()
        claimed_runs = self.store.claim_due_job_runs(limit=limit)
        result.due_jobs = len(claimed_runs)
        domain_concurrency = domain_concurrency or _domain_concurrency_limit()
        active_domains: dict[str, int] = {}

        for job, run in claimed_runs:
            domains = _job_domains(job)
            if domain_concurrency and any(active_domains.get(domain, 0) >= domain_concurrency for domain in domains):
                reason = f"Deferred because domain concurrency limit {domain_concurrency} was reached."
                if hasattr(self.store, "defer_run"):
                    self.store.defer_run(run, reason)
                else:  # pragma: no cover - compatibility with external stores
                    self.store.fail_run(run, reason)
                result.skipped_runs += 1
                result.deferred_runs += 1
                result.run_ids.append(run.id)
                result.warnings.append(f"{job.id}: {reason}")
                continue
            for domain in domains:
                active_domains[domain] = active_domains.get(domain, 0) + 1
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
        domain_concurrency: int | None = None,
        max_ticks: int | None = None,
    ) -> list[WorkerTickResult]:
        results: list[WorkerTickResult] = []
        ticks = 0
        while True:
            results.append(self.tick(limit=limit, dry_run=dry_run, deliver=deliver, domain_concurrency=domain_concurrency))
            ticks += 1
            if max_ticks is not None and ticks >= max_ticks:
                return results
            time.sleep(poll_seconds)


def run_job_now(store: Any, job_id: str, dry_run: bool = False, deliver: bool = True) -> JobRun:
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


def _domain_concurrency_limit() -> int | None:
    raw = os.getenv("COMMERCELENS_DOMAIN_CONCURRENCY_LIMIT")
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _job_domains(job: Any) -> set[str]:
    domains: set[str] = set()
    for target in job.config.targets:
        parsed = urlparse(str(target.url))
        if parsed.netloc:
            domains.add(parsed.netloc.lower())
    return domains
