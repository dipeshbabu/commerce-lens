from __future__ import annotations

from fastapi import HTTPException, status

from commercelens.api.auth import get_job_store
from commercelens.jobs.billing import current_month_window, limit_for_metric
from commercelens.jobs.models import ApiKeyRecord, QuotaDecision, UsageMetric


def require_scope(record: ApiKeyRecord | None, scope: str) -> None:
    if record is None:
        return
    if "*" in record.scopes or scope in record.scopes:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing required scope: {scope}")


def quota_decision(record: ApiKeyRecord, metric: UsageMetric, quantity: int = 1) -> QuotaDecision:
    period_start, period_end = current_month_window()
    summary = get_job_store().usage_summary(
        account_id=record.account_id,
        project_id=record.project_id,
        since=period_start,
        until=period_end,
    )
    used = next((item.quantity for item in summary.items if item.metric == metric), 0)
    limit = limit_for_metric(record.billing_plan, metric, record.monthly_quota_overrides)
    remaining = None if limit is None else max(0, limit - used)
    allowed = limit is None or used + quantity <= limit
    return QuotaDecision(
        allowed=allowed,
        metric=metric,
        used=used,
        requested=quantity,
        limit=limit,
        remaining=remaining,
        period_start=period_start,
        period_end=period_end,
        billing_plan=record.billing_plan,
        reason=None if allowed else "monthly_quota_exceeded",
    )


def require_quota(record: ApiKeyRecord | None, metric: UsageMetric, quantity: int = 1) -> None:
    if record is None:
        return
    decision = quota_decision(record, metric, quantity)
    if decision.allowed:
        return
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "error": "monthly_quota_exceeded",
            "metric": metric.value,
            "billing_plan": decision.billing_plan.value,
            "used": decision.used,
            "requested": decision.requested,
            "limit": decision.limit,
            "remaining": decision.remaining,
            "period_start": decision.period_start,
            "period_end": decision.period_end,
        },
    )
