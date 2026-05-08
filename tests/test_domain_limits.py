from __future__ import annotations

import pytest
from fastapi import HTTPException

from commercelens.api.domain_limits import domain_quota_for_key, require_domain_quota, url_domain
from commercelens.jobs.models import ApiKeyCreate
from commercelens.jobs.store import JobStore


def test_url_domain_normalizes_hostname() -> None:
    assert url_domain("https://Shop.Example.com/products/widget?x=1") == "shop.example.com"


def test_domain_quota_supports_exact_and_default_limits(tmp_path) -> None:
    store = JobStore(tmp_path / "jobs.db")
    result = store.create_api_key(
        ApiKeyCreate(
            name="limited",
            monthly_domain_quotas={"example.com": 0, "*": 10},
        )
    )

    assert domain_quota_for_key(result.key, "example.com") == 0
    assert domain_quota_for_key(result.key, "other.test") == 10

    with pytest.raises(HTTPException) as exc:
        require_domain_quota(store, result.key, "https://example.com/products/widget")

    assert exc.value.status_code == 429
    assert exc.value.detail["error"] == "monthly_domain_quota_exceeded"
    assert exc.value.detail["domain"] == "example.com"
