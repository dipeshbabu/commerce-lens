from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, HttpUrl

from commercelens.alerts.config import MonitorConfig


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class JobStatus(str, Enum):
    active = "active"
    paused = "paused"
    running = "running"
    failed = "failed"
    completed = "completed"
    disabled = "disabled"


class RunStatus(str, Enum):
    queued = "queued"
    running = "running"
    success = "success"
    failed = "failed"
    skipped = "skipped"


class ScheduleKind(str, Enum):
    interval = "interval"
    manual = "manual"


class MonitoringJob(BaseModel):
    id: str = Field(default_factory=lambda: f"job_{uuid4().hex[:16]}")
    name: str
    config: MonitorConfig
    schedule_kind: ScheduleKind = ScheduleKind.interval
    interval_minutes: int = Field(default=360, ge=1)
    status: JobStatus = JobStatus.active
    owner: str | None = None
    tags: list[str] = Field(default_factory=list)
    max_retries: int = Field(default=2, ge=0, le=10)
    retry_backoff_seconds: int = Field(default=60, ge=1)
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    last_run_at: str | None = None
    next_run_at: str | None = None
    last_error: str | None = None


class MonitoringJobCreate(BaseModel):
    name: str
    config: MonitorConfig
    schedule_kind: ScheduleKind = ScheduleKind.interval
    interval_minutes: int = Field(default=360, ge=1)
    owner: str | None = None
    tags: list[str] = Field(default_factory=list)
    max_retries: int = Field(default=2, ge=0, le=10)
    retry_backoff_seconds: int = Field(default=60, ge=1)


class MonitoringJobUpdate(BaseModel):
    name: str | None = None
    config: MonitorConfig | None = None
    schedule_kind: ScheduleKind | None = None
    interval_minutes: int | None = Field(default=None, ge=1)
    status: JobStatus | None = None
    owner: str | None = None
    tags: list[str] | None = None
    max_retries: int | None = Field(default=None, ge=0, le=10)
    retry_backoff_seconds: int | None = Field(default=None, ge=1)


class JobRun(BaseModel):
    id: str = Field(default_factory=lambda: f"run_{uuid4().hex[:16]}")
    job_id: str
    status: RunStatus = RunStatus.queued
    started_at: str | None = None
    finished_at: str | None = None
    attempt: int = 1
    event_count: int = 0
    delivery_count: int = 0
    warning_count: int = 0
    error: str | None = None
    result: dict[str, Any] | None = None


class WorkerTickResult(BaseModel):
    checked_at: str = Field(default_factory=utc_now_iso)
    due_jobs: int = 0
    started_runs: int = 0
    succeeded_runs: int = 0
    failed_runs: int = 0
    skipped_runs: int = 0
    run_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ApiKeyCreate(BaseModel):
    name: str
    owner: str | None = None
    scopes: list[str] = Field(default_factory=lambda: ["jobs:read", "jobs:write", "runs:read"])


class ApiKeyRecord(BaseModel):
    id: str = Field(default_factory=lambda: f"key_{uuid4().hex[:12]}")
    name: str
    owner: str | None = None
    token_hash: str
    token_prefix: str
    scopes: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now_iso)
    last_used_at: str | None = None
    disabled: bool = False


class ApiKeyCreateResult(BaseModel):
    key: ApiKeyRecord
    token: str


class WebhookTarget(BaseModel):
    name: str
    url: HttpUrl
    enabled: bool = True
    event_types: list[str] = Field(default_factory=lambda: ["job.run.success", "job.run.failed", "alert.created"])
