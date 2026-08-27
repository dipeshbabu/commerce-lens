from __future__ import annotations

from typing import TYPE_CHECKING, Any

from commercelens.jobs.models import (
    ApiKeyCreate,
    ApiKeyCreateResult,
    ApiKeyRecord,
    JobRun,
    JobStatus,
    MonitoringJob,
    MonitoringJobCreate,
    MonitoringJobUpdate,
    RunStatus,
    ScheduleKind,
    WorkerTickResult,
)
from commercelens.jobs.store import JobStore

if TYPE_CHECKING:
    from commercelens.jobs.worker import MonitoringWorker

__all__ = [
    "ApiKeyCreate",
    "ApiKeyCreateResult",
    "ApiKeyRecord",
    "JobRun",
    "JobStatus",
    "JobStore",
    "MonitoringJob",
    "MonitoringJobCreate",
    "MonitoringJobUpdate",
    "MonitoringWorker",
    "RunStatus",
    "ScheduleKind",
    "WorkerTickResult",
    "run_job_now",
]


def __getattr__(name: str) -> Any:
    if name == "MonitoringWorker":
        from commercelens.jobs.worker import MonitoringWorker

        return MonitoringWorker
    if name == "run_job_now":
        from commercelens.jobs.worker import run_job_now

        return run_job_now
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
