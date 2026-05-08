from __future__ import annotations

from fastapi.testclient import TestClient

from commercelens.api.main import app
from commercelens.connectors.datasets import ProductRecord
from commercelens.jobs.models import ApiKeyCreate
from commercelens.jobs.store import JobStore
from commercelens.matching.catalog_diff import diff_catalogs


def test_diff_catalogs_reports_added_removed_and_changed() -> None:
    before = [
        ProductRecord(url="https://shop.test/a", name="A", amount=10, availability="in_stock"),
        ProductRecord(url="https://shop.test/b", name="B", amount=20, availability="in_stock"),
    ]
    after = [
        ProductRecord(url="https://shop.test/a", name="A", amount=8, availability="in_stock"),
        ProductRecord(url="https://shop.test/c", name="C", amount=30, availability="out_of_stock"),
    ]

    result = diff_catalogs(before, after)

    assert result.total_changes == 3
    assert result.added[0].after.name == "C"  # type: ignore[union-attr]
    assert result.removed[0].before.name == "B"  # type: ignore[union-attr]
    assert result.changed[0].fields["amount"] == {"before": 10.0, "after": 8.0}


def test_catalog_diff_endpoint_records_usage(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "jobs.db"
    monkeypatch.setenv("COMMERCELENS_REQUIRE_API_KEY", "true")
    monkeypatch.setenv("COMMERCELENS_JOBS_DB", str(db_path))
    key = JobStore(db_path).create_api_key(ApiKeyCreate(name="diff", scopes=["*"]))
    client = TestClient(app)

    response = client.post(
        "/v1/catalog/diff",
        headers={"X-API-Key": key.token},
        json={
            "before": [{"url": "https://shop.test/a", "name": "A", "amount": 10}],
            "after": [{"url": "https://shop.test/a", "name": "A", "amount": 8}],
        },
    )

    assert response.status_code == 200
    assert response.json()["total_changes"] == 1
    assert JobStore(db_path).usage_summary().total_quantity == 1
