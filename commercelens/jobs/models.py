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
    disabled = "disabled"


class RunStatus(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    skipped = "skipped"


class ScheduleKind(str, Enum):
    interval = "interval"
    manual = "manual"


class UsageMetric(str, Enum):
    api_request = "api_request"
    product_extract = "product_extract"
    listing_extract = "listing_extract"
    catalog_crawl = "catalog_crawl"
    monitor_run = "monitor_run"
    job_run = "job_run"
    alert_event = "alert_event"
    alert_delivery = "alert_delivery"
    match_request = "match_request"


class TenantContext(BaseModel):
    account_id: str | None = None
    project_id: str | None = None
    owner: str | None = None


class MonitoringJob(BaseModel):
    id: str = Field(default_factory=lambda: f"job_{uuid4().hex[:16]}")
    name: str
    config: MonitorConfig
    schedule_kind: ScheduleKind = ScheduleKind.interval
    interval_minutes: int = Field(default=360, ge=1)
    status: JobStatus = JobStatus.active
    owner: str | None = None
    account_id: str | None = None
    project_id: str | None = None
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
    account_id: str | None = None
    project_id: str | None = None
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
    account_id: str | None = None
    project_id: str | None = None
    tags: list[str] | None = None
    max_retries: int | None = Field(default=None, ge=0, le=10)
    retry_backoff_seconds: int | None = Field(default=None, ge=1)


class JobRun(BaseModel):
    id: str = Field(default_factory=lambda: f"run_{uuid4().hex[:16]}")
    job_id: str
    status: RunStatus = RunStatus.queued
    account_id: str | None = None
    project_id: str | None = None
    owner: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None
    attempt: int = 1
    event_count: int = 0
    delivery_count: int = 0
    warning_count: int = 0
    error: str | None = None
    result: dict[str, Any] | None = None
    created_at: str = Field(default_factory=utc_now_iso)


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
    account_id: str | None = None
    project_id: str | None = None
    scopes: list[str] = Field(default_factory=lambda: ["jobs:read", "jobs:write", "runs:read", "usage:read"])


class ApiKeyRecord(BaseModel):
    id: str = Field(default_factory=lambda: f"key_{uuid4().hex[:12]}")
    name: str
    owner: str | None = None
    account_id: str | None = None
    project_id: str | None = None
    token_hash: str
    token_prefix: str
    scopes: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now_iso)
    last_used_at: str | None = None
    disabled: bool = False


class ApiKeyCreateResult(BaseModel):
    key: ApiKeyRecord
    token: str


class UsageEvent(BaseModel):
    id: str = Field(default_factory=lambda: f"usage_{uuid4().hex[:16]}")
    metric: UsageMetric
    quantity: int = Field(default=1, ge=1)
    account_id: str | None = None
    project_id: str | None = None
    owner: str | None = None
    api_key_id: str | None = None
    job_id: str | None = None
    run_id: str | None = None
    route: str | None = None
    status_code: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso)


class UsageSummaryItem(BaseModel):
    metric: UsageMetric
    quantity: int


class UsageSummary(BaseModel):
    account_id: str | None = None
    project_id: str | None = None
    since: str | None = None
    until: str | None = None
    total_quantity: int = 0
    items: list[UsageSummaryItem] = Field(default_factory=list)


class WebhookTarget(BaseModel):
    name: str
    url: HttpUrl
    enabled: bool = True
    event_types: list[str] = Field(default_factory=lambda: ["job.run.succeeded", "job.run.failed", "alert.created"])
