from __future__ import annotations

from datetime import datetime, timezone

from commercelens.jobs.models import BillingPlan, UsageMetric

MONTHLY_PLAN_LIMITS: dict[BillingPlan, dict[UsageMetric, int | None]] = {
    BillingPlan.free: {
        UsageMetric.api_request: 1_000,
        UsageMetric.product_extract: 500,
        UsageMetric.listing_extract: 250,
        UsageMetric.catalog_crawl: 50,
        UsageMetric.monitor_run: 100,
        UsageMetric.job_run: 100,
        UsageMetric.alert_event: 500,
        UsageMetric.alert_delivery: 250,
        UsageMetric.match_request: 250,
    },
    BillingPlan.developer: {
        UsageMetric.api_request: 50_000,
        UsageMetric.product_extract: 25_000,
        UsageMetric.listing_extract: 10_000,
        UsageMetric.catalog_crawl: 2_000,
        UsageMetric.monitor_run: 5_000,
        UsageMetric.job_run: 5_000,
        UsageMetric.alert_event: 25_000,
        UsageMetric.alert_delivery: 10_000,
        UsageMetric.match_request: 10_000,
    },
    BillingPlan.team: {
        UsageMetric.api_request: 500_000,
        UsageMetric.product_extract: 250_000,
        UsageMetric.listing_extract: 100_000,
        UsageMetric.catalog_crawl: 20_000,
        UsageMetric.monitor_run: 50_000,
        UsageMetric.job_run: 50_000,
        UsageMetric.alert_event: 250_000,
        UsageMetric.alert_delivery: 100_000,
        UsageMetric.match_request: 100_000,
    },
    BillingPlan.enterprise: {metric: None for metric in UsageMetric},
}


def current_month_window(now: datetime | None = None) -> tuple[str, str]:
    now = now or datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start.isoformat(), end.isoformat()


def limit_for_metric(
    billing_plan: BillingPlan,
    metric: UsageMetric,
    overrides: dict[UsageMetric, int] | None = None,
) -> int | None:
    overrides = overrides or {}
    if metric in overrides:
        return overrides[metric]
    plan_limits = MONTHLY_PLAN_LIMITS.get(billing_plan, MONTHLY_PLAN_LIMITS[BillingPlan.free])
    return plan_limits.get(metric)
