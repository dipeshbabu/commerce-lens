from __future__ import annotations

from pydantic import BaseModel, Field

from commercelens.jobs.models import (
    BillingUsageSnapshot,
    ExtractionRecord,
    JobRun,
    MonitoringJob,
    UsageSummary,
)


class MonitoredTargetSummary(BaseModel):
    url: str
    job_id: str
    job_name: str
    job_status: str
    render: bool = False
    tags: list[str] = Field(default_factory=list)
    last_run_at: str | None = None
    next_run_at: str | None = None
    last_error: str | None = None


class MonitoringOverview(BaseModel):
    target_count: int = 0
    active_job_count: int = 0
    failed_run_count: int = 0
    rule_count: int = 0
    render_target_count: int = 0
    recent_failure_count: int = 0
    targets: list[MonitoredTargetSummary] = Field(default_factory=list)


class DashboardSummary(BaseModel):
    account_id: str | None = None
    project_id: str | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    billing: BillingUsageSnapshot
    usage: UsageSummary
    monitoring: MonitoringOverview = Field(default_factory=MonitoringOverview)
    jobs: list[MonitoringJob] = Field(default_factory=list)
    runs: list[JobRun] = Field(default_factory=list)
    extractions: list[ExtractionRecord] = Field(default_factory=list)
