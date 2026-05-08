from __future__ import annotations

from fastapi.testclient import TestClient

from commercelens.alerts.config import AlertRule, MonitorConfig, MonitorTarget
from commercelens.alerts.rules import AlertCondition
from commercelens.api.main import app
from commercelens.jobs.models import ApiKeyCreate, MonitoringJobCreate, UsageEvent, UsageMetric
from commercelens.jobs.store import JobStore


def sample_config() -> MonitorConfig:
    return MonitorConfig(
        targets=[MonitorTarget(url="https://example.com/product", name="Example Product")],
        rules=[AlertRule(name="price drop", condition=AlertCondition.PRICE_DROP)],
        channels=[],
    )


def test_dashboard_summary_is_scoped_to_api_key(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "jobs.db"
    monkeypatch.setenv("COMMERCELENS_REQUIRE_API_KEY", "true")
    monkeypatch.setenv("COMMERCELENS_JOBS_DB", str(db_path))
    store = JobStore(db_path)
    key = store.create_api_key(
        ApiKeyCreate(
            name="customer",
            account_id="acct_demo",
            project_id="proj_demo",
            scopes=["*"],
        )
    )
    store.create_job(
        MonitoringJobCreate(
            name="watch",
            config=sample_config(),
            account_id="acct_demo",
            project_id="proj_demo",
        )
    )
    store.record_usage(
        UsageEvent(
            metric=UsageMetric.product_extract,
            quantity=3,
            account_id="acct_demo",
            project_id="proj_demo",
            api_key_id=key.key.id,
        )
    )
    client = TestClient(app)

    response = client.get("/v1/dashboard/summary", headers={"X-API-Key": key.token})

    assert response.status_code == 200
    payload = response.json()
    assert payload["account_id"] == "acct_demo"
    assert payload["project_id"] == "proj_demo"
    assert payload["counts"]["jobs"] == 1
    assert payload["usage"]["total_quantity"] == 4
    assert payload["billing"]["billing_plan"] == "free"
