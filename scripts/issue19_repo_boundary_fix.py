from pathlib import Path

path = Path("commercelens/domain/repository.py")
text = path.read_text()
text = text.replace("from commercelens.jobs.migrations import run_postgres_migrations\n", "")

old_path = (
    '    path = getattr(store, "path", None)\n'
    '    return SQLiteDomainRepository(path or os.getenv("COMMERCELENS_JOBS_DB", "commercelens_jobs.db"))\n'
)
new_path = (
    '    path = getattr(store, "path", None)\n'
    '    sqlite_path = str(path) if path is not None else os.getenv("COMMERCELENS_JOBS_DB", "commercelens_jobs.db")\n'
    "    return SQLiteDomainRepository(sqlite_path)\n"
)
if old_path in text:
    text = text.replace(old_path, new_path, 1)
elif new_path not in text:
    raise RuntimeError("Repository path anchor not found")

old_init = (
    "        self._dict_row = dict_row\n"
    "        with self._connect() as conn:\n"
    "            run_postgres_migrations(conn)\n"
)
new_init = (
    "        self._dict_row = dict_row\n"
    "        from commercelens.jobs.migrations import run_postgres_migrations\n\n"
    "        with self._connect() as conn:\n"
    "            run_postgres_migrations(conn)\n"
)
if old_init in text:
    text = text.replace(old_init, new_init, 1)
elif new_init not in text:
    raise RuntimeError("Postgres migration import anchor not found")

path.write_text(text)

jobs_init = Path("commercelens/jobs/__init__.py")
jobs_init.write_text(
    '''from __future__ import annotations

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
'''
)
