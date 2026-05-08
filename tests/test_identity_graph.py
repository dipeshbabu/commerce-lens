from __future__ import annotations

from fastapi.testclient import TestClient

from commercelens.api.main import app
from commercelens.connectors.datasets import ProductRecord
from commercelens.jobs.models import ApiKeyCreate
from commercelens.jobs.store import JobStore
from commercelens.matching.identity import build_identity_graph


def test_build_identity_graph_clusters_matching_products() -> None:
    records = [
        ProductRecord(name="Nike Air Max 90", brand="Nike", amount=120, currency="USD", url="https://a.test/1"),
        ProductRecord(name="Nike Air Max 90 Shoes", brand="Nike", amount=125, currency="USD", url="https://b.test/2"),
        ProductRecord(name="Adidas Samba", brand="Adidas", amount=90, currency="USD", url="https://c.test/3"),
    ]

    graph = build_identity_graph(records, threshold=0.72)

    assert len(graph.clusters) == 2
    assert len(graph.clusters[0].records) == 2
    assert graph.clusters[0].min_amount == 120
    assert graph.clusters[0].max_amount == 125
    assert graph.edges[0].score >= 0.72


def test_identity_graph_endpoint_records_usage(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "jobs.db"
    monkeypatch.setenv("COMMERCELENS_REQUIRE_API_KEY", "true")
    monkeypatch.setenv("COMMERCELENS_JOBS_DB", str(db_path))
    key = JobStore(db_path).create_api_key(ApiKeyCreate(name="match", scopes=["*"]))
    client = TestClient(app)

    response = client.post(
        "/v1/identity/graph",
        headers={"X-API-Key": key.token},
        json={
            "threshold": 0.72,
            "records": [
                {"name": "Nike Air Max 90", "brand": "Nike", "amount": 120, "currency": "USD"},
                {"name": "Nike Air Max 90 Shoes", "brand": "Nike", "amount": 125, "currency": "USD"},
            ],
        },
    )

    assert response.status_code == 200
    assert len(response.json()["clusters"]) == 1
    assert JobStore(db_path).usage_summary().total_quantity == 1
