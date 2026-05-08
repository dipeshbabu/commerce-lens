from fastapi.testclient import TestClient

from commercelens.api.main import app
from commercelens.core.crawler import CatalogCrawlResult
from commercelens.core.monitor import MonitorResult
from commercelens.jobs.models import ApiKeyCreate
from commercelens.jobs.store import JobStore
from commercelens.schemas.listing import ListingProduct
from commercelens.storage.price_store import ProductSnapshot


def test_health_reports_version() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["version"] == "0.9.0"


def test_readiness_reports_store_and_auth(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("COMMERCELENS_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("COMMERCELENS_JOBS_DB", str(tmp_path / "jobs.db"))
    monkeypatch.setenv("COMMERCELENS_REQUIRE_API_KEY", "true")
    monkeypatch.setenv("COMMERCELENS_ADMIN_TOKEN", "secret")
    client = TestClient(app)

    response = client.get("/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["store_backend"] == "sqlite"
    assert payload["api_key_required"] is True
    assert payload["admin_token_configured"] is True


def test_catalog_crawl_endpoint_records_usage_with_pages_crawled(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("COMMERCELENS_REQUIRE_API_KEY", "false")
    monkeypatch.setenv("COMMERCELENS_JOBS_DB", str(tmp_path / "jobs.db"))

    def fake_crawl_catalog(**_kwargs) -> CatalogCrawlResult:
        return CatalogCrawlResult(
            start_url="https://example.com/category",
            pages_crawled=2,
            products=[ListingProduct(name="Widget")],
        )

    monkeypatch.setattr("commercelens.api.main.crawl_catalog", fake_crawl_catalog)
    client = TestClient(app)

    response = client.post("/v1/crawl/catalog", json={"url": "https://example.com/category"})

    assert response.status_code == 200
    assert response.json()["pages_crawled"] == 2


def test_product_extract_blocks_domain_quota(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("COMMERCELENS_REQUIRE_API_KEY", "true")
    monkeypatch.setenv("COMMERCELENS_JOBS_DB", str(tmp_path / "jobs.db"))
    key = JobStore(tmp_path / "jobs.db").create_api_key(
        ApiKeyCreate(name="limited", scopes=["*"], monthly_domain_quotas={"example.com": 0})
    )
    client = TestClient(app)

    response = client.post(
        "/v1/extract/product",
        headers={"X-API-Key": key.token},
        json={
            "url": "https://example.com/products/widget",
            "html": "<html></html>",
        },
    )

    assert response.status_code == 429
    assert response.json()["detail"]["error"] == "monthly_domain_quota_exceeded"


def test_monitor_endpoint_records_usage_with_has_change(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("COMMERCELENS_REQUIRE_API_KEY", "false")
    monkeypatch.setenv("COMMERCELENS_JOBS_DB", str(tmp_path / "jobs.db"))
    snapshot = ProductSnapshot(
        product_key="key",
        source_url="https://example.com/products/widget",
        canonical_url=None,
        name="Widget",
        brand=None,
        amount=10.0,
        currency="USD",
        availability="in_stock",
        image_url=None,
        captured_at="2026-01-01T00:00:00+00:00",
        raw={},
    )

    def fake_monitor_product(*_args, **_kwargs) -> MonitorResult:
        return MonitorResult(product_key="key", snapshot=snapshot, has_change=False)

    monkeypatch.setattr("commercelens.api.main.monitor_product", fake_monitor_product)
    client = TestClient(app)

    response = client.post(
        "/v1/monitor/product",
        json={"url": "https://example.com/products/widget", "db_path": str(tmp_path / "prices.db")},
    )

    assert response.status_code == 200
    assert response.json()["has_change"] is False
