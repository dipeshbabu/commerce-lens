from __future__ import annotations

from fastapi.testclient import TestClient

from commercelens.api.main import app
from commercelens.domain.repository import domain_repository_for_store
from commercelens.jobs.models import AccountCreate, AccountStatus, ApiKeyCreate, ProjectCreate
from commercelens.jobs.store import JobStore


def test_product_extraction_mirrors_observation_without_changing_response(
    monkeypatch, tmp_path
) -> None:
    db_path = tmp_path / "jobs.db"
    monkeypatch.setenv("COMMERCELENS_JOBS_DB", str(db_path))
    monkeypatch.setenv("COMMERCELENS_REQUIRE_API_KEY", "true")
    store = JobStore(db_path)
    account = store.create_account(
        AccountCreate(name="Acme", owner="owner@example.com", status=AccountStatus.active)
    )
    project = store.create_project(account.id, ProjectCreate(name="Competitors"))
    access = store.create_api_key(
        ApiKeyCreate(
            name="extract-test",
            account_id=account.id,
            project_id=project.id,
            scopes=["*"],
        )
    )
    client = TestClient(app, base_url="https://testserver")
    html = """
    <html><head><script type="application/ld+json">
    {"@context":"https://schema.org","@type":"Product","name":"Trail Shoe","brand":{"@type":"Brand","name":"Example"},"gtin13":"00012345678905","offers":{"@type":"Offer","price":"89.99","priceCurrency":"USD","availability":"https://schema.org/InStock","url":"https://shop.example/products/trail"}}
    </script></head><body></body></html>
    """

    response = client.post(
        "/v1/extract/product",
        headers={"X-API-Key": access.token},
        json={"url": "https://shop.example/products/trail", "html": html},
    )
    assert response.status_code == 200
    assert response.json()["product"]["name"] == "Trail Shoe"

    repo = domain_repository_for_store(JobStore(db_path))
    observations = repo.list_observations(account_id=account.id, project_id=project.id)
    assert len(observations) == 1
    assert observations[0].source_url == "https://shop.example/products/trail"
    assert observations[0].extraction_id is not None
