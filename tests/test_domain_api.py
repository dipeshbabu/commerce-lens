from __future__ import annotations

from fastapi.testclient import TestClient

from commercelens.api.main import app
from commercelens.jobs.models import AccountCreate, AccountStatus, ApiKeyCreate, ProjectCreate
from commercelens.jobs.store import JobStore


def _workspace(store: JobStore, name: str):
    account = store.create_account(
        AccountCreate(name=name, owner=f"{name.lower()}@example.com", status=AccountStatus.active)
    )
    project = store.create_project(account.id, ProjectCreate(name="Competitors"))
    access = store.create_api_key(
        ApiKeyCreate(
            name="domain-test",
            account_id=account.id,
            project_id=project.id,
            scopes=["*"],
        )
    )
    return account, project, access


def test_domain_api_hides_cross_tenant_records(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "jobs.db"
    monkeypatch.setenv("COMMERCELENS_JOBS_DB", str(db_path))
    monkeypatch.setenv("COMMERCELENS_REQUIRE_API_KEY", "true")
    store = JobStore(db_path)
    _, _, first_access = _workspace(store, "First")
    _, _, second_access = _workspace(store, "Second")
    client = TestClient(app, base_url="https://testserver")

    created = client.post(
        "/v1/products",
        headers={"X-API-Key": first_access.token},
        json={"name": "Trail Shoe", "brand": "Example", "identity_key": "gtin:123"},
    )
    assert created.status_code == 200
    product_id = created.json()["id"]

    hidden = client.get(
        f"/v1/products/{product_id}",
        headers={"X-API-Key": second_access.token},
    )
    assert hidden.status_code == 404

    visible = client.get(
        f"/v1/products/{product_id}",
        headers={"X-API-Key": first_access.token},
    )
    assert visible.status_code == 200


def test_product_match_crud_uses_canonical_pair_order(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "jobs.db"
    monkeypatch.setenv("COMMERCELENS_JOBS_DB", str(db_path))
    monkeypatch.setenv("COMMERCELENS_REQUIRE_API_KEY", "true")
    store = JobStore(db_path)
    _, _, access = _workspace(store, "Acme")
    client = TestClient(app, base_url="https://testserver")
    headers = {"X-API-Key": access.token}

    left = client.post("/v1/products", headers=headers, json={"name": "A"}).json()
    right = client.post("/v1/products", headers=headers, json={"name": "B"}).json()
    created = client.post(
        "/v1/product-matches",
        headers=headers,
        json={
            "left_product_id": right["id"],
            "right_product_id": left["id"],
            "confidence": 0.8,
            "status": "proposed",
            "method": "manual-test",
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["left_product_id"] < payload["right_product_id"]

    fetched = client.get(f"/v1/product-matches/{payload['id']}", headers=headers)
    assert fetched.status_code == 200
    updated = client.patch(
        f"/v1/product-matches/{payload['id']}",
        headers=headers,
        json={"status": "confirmed", "confidence": 1.0},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "confirmed"
