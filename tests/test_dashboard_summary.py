from __future__ import annotations

from fastapi.testclient import TestClient

from commercelens.alerts.config import AlertRule, MonitorConfig, MonitorTarget
from commercelens.alerts.rules import AlertCondition
from commercelens.api.main import app
from commercelens.jobs.models import (
    ApiKeyCreate,
    ExtractionCreate,
    ExtractionKind,
    ExtractionStatus,
    JobRun,
    MonitoringJobCreate,
    RunStatus,
    UsageEvent,
    UsageMetric,
)
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
    assert payload["monitoring"]["target_count"] == 1
    assert payload["monitoring"]["rule_count"] == 1
    assert payload["usage"]["total_quantity"] == 4
    assert payload["billing"]["billing_plan"] == "free"


def test_monitoring_overview_and_customer_portal(monkeypatch, tmp_path) -> None:
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
    job = store.create_job(
        MonitoringJobCreate(
            name="competitor watch",
            config=sample_config(),
            account_id="acct_demo",
            project_id="proj_demo",
        )
    )
    other_job = store.create_job(
        MonitoringJobCreate(
            name="hidden tenant watch",
            config=sample_config(),
            account_id="acct_other",
            project_id="proj_other",
        )
    )
    run = store.save_run(
        JobRun(
            job_id=job.id,
            status=RunStatus.failed,
            account_id="acct_demo",
            project_id="proj_demo",
            event_count=2,
            delivery_count=1,
            warning_count=0,
            error="competitor.example timed out after 20 seconds",
            result={"events": [{"change_type": "price_drop", "product": "Example Product"}]},
        )
    )
    extraction = store.record_extraction(
        ExtractionCreate(
            kind=ExtractionKind.product,
            status=ExtractionStatus.succeeded,
            url="https://example.com/product",
            account_id="acct_demo",
            project_id="proj_demo",
            payload={"product": {"name": "Example Product", "price": {"amount": 10, "currency": "USD"}}},
        )
    )
    client = TestClient(app)

    overview = client.get("/v1/monitoring/overview", headers={"X-API-Key": key.token})
    portal = client.get(f"/portal?api_key={key.token}")
    job_detail = client.get(f"/portal/jobs/{job.id}?api_key={key.token}")
    run_detail = client.get(f"/portal/runs/{run.id}?api_key={key.token}")
    extraction_detail = client.get(f"/portal/extractions/{extraction.id}?api_key={key.token}")
    hidden_detail = client.get(f"/portal/jobs/{other_job.id}?api_key={key.token}")
    export_response = client.get(f"/portal/export/jobs?api_key={key.token}")
    issues_response = client.get("/v1/issues", headers={"X-API-Key": key.token})
    metrics_response = client.get("/v1/ops/failure-metrics")

    assert overview.status_code == 200
    assert overview.json()["target_count"] == 1
    assert overview.json()["targets"][0]["job_name"] == "competitor watch"
    assert portal.status_code == 200
    assert "customer portal" in portal.text
    assert "competitor watch" in portal.text
    assert "Recent Issues" in portal.text
    assert "timeout" in portal.text
    assert "Monitoring Jobs" in portal.text
    assert "/portal/export/jobs" in portal.text
    assert job_detail.status_code == 200
    assert "Alert Rules" in job_detail.text
    assert "price drop" in job_detail.text
    assert run_detail.status_code == 200
    assert "price_drop" in run_detail.text
    assert "Failure Class" in run_detail.text
    assert extraction_detail.status_code == 200
    assert "Example Product" in extraction_detail.text
    assert hidden_detail.status_code == 404
    assert export_response.status_code == 200
    assert export_response.json()["items"][0]["name"] == "competitor watch"
    assert issues_response.status_code == 200
    assert issues_response.json()["issues"][0]["failure_class"] == "timeout"
    assert metrics_response.status_code == 200
    assert metrics_response.json()["by_failure_class"]["timeout"] == 1
