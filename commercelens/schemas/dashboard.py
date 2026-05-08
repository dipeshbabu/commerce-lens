from __future__ import annotations

from pydantic import BaseModel, Field

from commercelens.jobs.models import (
    BillingUsageSnapshot,
    ExtractionRecord,
    JobRun,
    MonitoringJob,
    UsageSummary,
)


class DashboardSummary(BaseModel):
    account_id: str | None = None
    project_id: str | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    billing: BillingUsageSnapshot
    usage: UsageSummary
    jobs: list[MonitoringJob] = Field(default_factory=list)
    runs: list[JobRun] = Field(default_factory=list)
    extractions: list[ExtractionRecord] = Field(default_factory=list)
