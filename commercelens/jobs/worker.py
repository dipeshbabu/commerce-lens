from __future__ import annotations

import os
import time
from collections import deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from commercelens.alerts.runner import run_monitor_config
from commercelens.jobs.models import JobRun, WorkerTickResult
from commercelens.jobs.store import JobStore


class MonitoringWorker:
    def __init__(
        self, store: Any | None = None, store_path: str | Path = "commercelens_jobs.db"
    ) -> None:
        self.store = store or JobStore(store_path)

    def tick(
        self,
        limit: int = 25,
        dry_run: bool = False,
        deliver: bool = True,
        domain_concurrency: int | None = None,
        worker_concurrency: int | None = None,
    ) -> WorkerTickResult:
        result = WorkerTickResult()
        claimed_runs = self.store.claim_due_job_runs(limit=limit)
        result.due_jobs = len(claimed_runs)
        result.run_ids = [run.id for _, run in claimed_runs]
        domain_concurrency = _positive_limit(
            domain_concurrency,
            _domain_concurrency_limit(),
            "domain_concurrency",
        )
        worker_concurrency = (
            _positive_limit(
                worker_concurrency,
                _worker_concurrency_limit(),
                "worker_concurrency",
            )
            or 1
        )
        if not claimed_runs:
            return result

        pending = deque((job, run, _job_domains(job)) for job, run in claimed_runs)
        active_domains: dict[str, int] = {}
        active: dict[Future[Any], tuple[Any, JobRun, set[str]]] = {}

        with ThreadPoolExecutor(max_workers=worker_concurrency) as executor:
            while pending or active:
                _submit_available_runs(
                    pending=pending,
                    active=active,
                    active_domains=active_domains,
                    executor=executor,
                    worker_concurrency=worker_concurrency,
                    domain_concurrency=domain_concurrency,
                    dry_run=dry_run,
                    deliver=deliver,
                    result=result,
                )

                if not active:
                    raise RuntimeError("Worker could not schedule a claimed run.")

                completed, _ = wait(active, return_when=FIRST_COMPLETED)
                for future in completed:
                    job, run, domains = active.pop(future)
                    try:
                        monitor_result = future.result()
                        delivery_count = sum(
                            len(report.results) for report in monitor_result.delivery_reports
                        )
                        self.store.complete_run(
                            run,
                            result=monitor_result.model_dump(mode="json", exclude_none=True),
                            event_count=len(monitor_result.events),
                            delivery_count=delivery_count,
                            warning_count=len(monitor_result.warnings),
                        )
                        result.succeeded_runs += 1
                    except Exception as exc:  # pragma: no cover - integration and mocks
                        self.store.fail_run(run, str(exc))
                        result.failed_runs += 1
                        result.warnings.append(f"{job.id}: {exc}")
                    finally:
                        _release_domains(active_domains, domains)

        return result

    def run_forever(
        self,
        poll_seconds: int = 60,
        limit: int = 25,
        dry_run: bool = False,
        deliver: bool = True,
        domain_concurrency: int | None = None,
        worker_concurrency: int | None = None,
        max_ticks: int | None = None,
    ) -> list[WorkerTickResult]:
        results: list[WorkerTickResult] = []
        ticks = 0
        while True:
            results.append(
                self.tick(
                    limit=limit,
                    dry_run=dry_run,
                    deliver=deliver,
                    domain_concurrency=domain_concurrency,
                    worker_concurrency=worker_concurrency,
                )
            )
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
    return _env_positive_limit("COMMERCELENS_DOMAIN_CONCURRENCY_LIMIT")


def _worker_concurrency_limit() -> int:
    return _env_positive_limit("COMMERCELENS_WORKER_CONCURRENCY") or 1


def _job_domains(job: Any) -> set[str]:
    domains: set[str] = set()
    for target in job.config.targets:
        parsed = urlparse(str(target.url))
        if parsed.netloc:
            domains.add(parsed.netloc.lower())
    return domains


def _positive_limit(
    explicit: int | None,
    default: int | None,
    name: str,
) -> int | None:
    value = explicit if explicit is not None else default
    if value is not None and value < 1:
        raise ValueError(f"{name} must be greater than zero.")
    return value


def _env_positive_limit(name: str) -> int | None:
    raw = os.getenv(name)
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _submit_available_runs(
    *,
    pending: deque[tuple[Any, JobRun, set[str]]],
    active: dict[Future[Any], tuple[Any, JobRun, set[str]]],
    active_domains: dict[str, int],
    executor: ThreadPoolExecutor,
    worker_concurrency: int,
    domain_concurrency: int | None,
    dry_run: bool,
    deliver: bool,
    result: WorkerTickResult,
) -> None:
    candidates = len(pending)
    for _ in range(candidates):
        if len(active) >= worker_concurrency:
            return
        job, run, domains = pending.popleft()
        if domain_concurrency is not None and any(
            active_domains.get(domain, 0) >= domain_concurrency for domain in domains
        ):
            pending.append((job, run, domains))
            continue

        for domain in domains:
            active_domains[domain] = active_domains.get(domain, 0) + 1
        future = executor.submit(
            run_monitor_config,
            job.config,
            dry_run=dry_run,
            deliver=deliver,
        )
        active[future] = (job, run, domains)
        result.started_runs += 1


def _release_domains(active_domains: dict[str, int], domains: set[str]) -> None:
    for domain in domains:
        remaining = active_domains[domain] - 1
        if remaining:
            active_domains[domain] = remaining
        else:
            del active_domains[domain]
