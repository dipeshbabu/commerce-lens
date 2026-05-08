from __future__ import annotations

from fastapi.testclient import TestClient

from commercelens.api.main import app
from commercelens.connectors.datasets import ProductRecord
from commercelens.intelligence.price_summary import summarize_prices
from commercelens.jobs.models import ApiKeyCreate
from commercelens.jobs.store import JobStore


def test_summarize_prices_reports_price_band_and_availability() -> None:
    records = [
        ProductRecord(name="A", amount=10, currency="USD", availability="in_stock"),
        ProductRecord(name="B", amount=20, currency="USD", availability="out_of_stock"),
        ProductRecord(name="C", amount=None, currency="USD", availability="in_stock"),
    ]

    summary = summarize_prices(records)

    assert summary.record_count == 3
    assert summary.priced_count == 2
    assert summary.min_amount == 10
    assert summary.max_amount == 20
    assert summary.average_amount == 15
    assert summary.cheapest.name == "A"  # type: ignore[union-attr]
    assert summary.availability_counts == {"in_stock": 2, "out_of_stock": 1}


def test_price_summary_endpoint_records_usage(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "jobs.db"
    monkeypatch.setenv("COMMERCELENS_REQUIRE_API_KEY", "true")
    monkeypatch.setenv("COMMERCELENS_JOBS_DB", str(db_path))
    key = JobStore(db_path).create_api_key(ApiKeyCreate(name="price-summary", scopes=["*"]))
    client = TestClient(app)

    response = client.post(
        "/v1/intelligence/price-summary",
        headers={"X-API-Key": key.token},
        json={
            "records": [
                {"name": "A", "amount": 10, "currency": "USD", "availability": "in_stock"},
                {"name": "B", "amount": 20, "currency": "USD", "availability": "out_of_stock"},
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["average_amount"] == 15
    assert JobStore(db_path).usage_summary().total_quantity == 1
