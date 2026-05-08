from __future__ import annotations

from urllib.parse import urlparse

from fastapi import HTTPException, status

from commercelens.jobs.billing import current_month_window
from commercelens.jobs.models import ApiKeyRecord


def url_domain(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    return (parsed.hostname or parsed.netloc or "").lower() or None


def domain_quota_for_key(record: ApiKeyRecord, domain: str) -> int | None:
    quotas = {key.lower(): value for key, value in record.monthly_domain_quotas.items()}
    return quotas.get(domain) if domain in quotas else quotas.get("*")


def used_domain_quantity(store, record: ApiKeyRecord, domain: str) -> int:
    period_start, period_end = current_month_window()
    events = store.list_usage_events(
        account_id=record.account_id,
        project_id=record.project_id,
        since=period_start,
        until=period_end,
        limit=100_000,
    )
    return sum(
        event.quantity
        for event in events
        if event.api_key_id == record.id and (event.metadata or {}).get("domain") == domain
    )


def require_domain_quota(
    store,
    record: ApiKeyRecord | None,
    url: str | None,
    quantity: int = 1,
) -> str | None:
    domain = url_domain(url)
    if record is None or domain is None:
        return domain

    limit = domain_quota_for_key(record, domain)
    if limit is None:
        return domain

    period_start, period_end = current_month_window()
    used = used_domain_quantity(store, record, domain)
    if used + quantity <= limit:
        return domain

    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "error": "monthly_domain_quota_exceeded",
            "domain": domain,
            "used": used,
            "requested": quantity,
            "limit": limit,
            "remaining": max(0, limit - used),
            "period_start": period_start,
            "period_end": period_end,
        },
    )
