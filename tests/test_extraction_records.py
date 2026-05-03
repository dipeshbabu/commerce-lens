from pathlib import Path

from fastapi.testclient import TestClient

from commercelens.api.main import app
from commercelens.jobs.models import AccountCreate, ExtractionCreate, ExtractionKind, ExtractionStatus
from commercelens.jobs.store import JobStore


PRODUCT_HTML = """
<html>
  <script type="application/ld+json">
  {
    "@context": "https://schema.org",
    "@type": "Product",
    "name": "Demo Shoe",
    "brand": {"@type": "Brand", "name": "Acme"},
    "offers": {
      "@type": "Offer",
      "price": "89.99",
      "priceCurrency": "USD",
      "availability": "https://schema.org/InStock"
    }
  }
  </script>
</html>
"""


LISTING_HTML = """
<html>
  <body>
    <article class="product-card">
      <h2><a href="/products/demo-shoe">Demo Shoe</a></h2>
      <span class="price">$89.99</span>
    </article>
  </body>
</html>
"""


def _create_key(client: TestClient, account_id: str, project_id: str | None = None) -> str:
    response = client.post(
        "/v1/api-keys",
        headers={"X-Admin-Token": "secret"},
        json={
            "name": "test key",
            "account_id": account_id,
            "project_id": project_id,
            "scopes": ["*"],
        },
    )
    assert response.status_code == 200
    return response.json()["token"]


def test_store_records_extractions(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.db")
    account = store.create_account(AccountCreate(name="Acme"))

    record = store.record_extraction(
        ExtractionCreate(
            kind=ExtractionKind.product,
            status=ExtractionStatus.succeeded,
            account_id=account.id,
            url="https://example.com/products/demo",
            confidence=0.91,
            payload={"product": {"name": "Demo Shoe"}},
        )
    )

    assert store.get_extraction(record.id, account_id=account.id) == record
    assert store.get_extraction(record.id, account_id="acct_other") is None
    assert store.list_extractions(account_id=account.id)[0].payload["product"]["name"] == "Demo Shoe"


def test_product_extraction_records_success_and_dashboard(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("COMMERCELENS_REQUIRE_API_KEY", "true")
    monkeypatch.setenv("COMMERCELENS_ADMIN_TOKEN", "secret")
    monkeypatch.setenv("COMMERCELENS_JOBS_DB", str(tmp_path / "jobs.db"))
    client = TestClient(app)
    account = client.post(
        "/v1/accounts",
        headers={"X-Admin-Token": "secret"},
        json={"name": "Acme"},
    ).json()
    project = client.post(
        f"/v1/accounts/{account['id']}/projects",
        headers={"X-Admin-Token": "secret"},
        json={"name": "Default"},
    ).json()
    token = _create_key(client, account["id"], project["id"])

    extract_response = client.post(
        "/v1/extract/product",
        headers={"X-API-Key": token},
        json={"html": PRODUCT_HTML, "url": "https://example.com/products/demo-shoe"},
    )
    records_response = client.get("/v1/extractions", headers={"X-API-Key": token})

    assert extract_response.status_code == 200
    assert records_response.status_code == 200
    records = records_response.json()
    assert len(records) == 1
    assert records[0]["status"] == "succeeded"
    assert records[0]["kind"] == "product"
    assert records[0]["payload"]["product"]["name"] == "Demo Shoe"

    dashboard_response = client.get("/dashboard?admin_token=secret")
    detail_response = client.get(f"/dashboard/extractions/{records[0]['id']}?admin_token=secret")
    assert dashboard_response.status_code == 200
    assert "Recent Extractions" in dashboard_response.text
    assert "Demo Shoe" in detail_response.text


def test_listing_extraction_records_success(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("COMMERCELENS_REQUIRE_API_KEY", "true")
    monkeypatch.setenv("COMMERCELENS_ADMIN_TOKEN", "secret")
    monkeypatch.setenv("COMMERCELENS_JOBS_DB", str(tmp_path / "jobs.db"))
    client = TestClient(app)
    account = client.post(
        "/v1/accounts",
        headers={"X-Admin-Token": "secret"},
        json={"name": "Acme"},
    ).json()
    token = _create_key(client, account["id"])

    response = client.post(
        "/v1/extract/listing",
        headers={"X-API-Key": token},
        json={"html": LISTING_HTML, "url": "https://example.com/category"},
    )
    records = client.get("/v1/extractions?kind=listing", headers={"X-API-Key": token}).json()

    assert response.status_code == 200
    assert records[0]["kind"] == "listing"
    assert records[0]["product_count"] == 1
    assert records[0]["payload"]["products"][0]["name"] == "Demo Shoe"


def test_failed_extraction_is_recorded(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("COMMERCELENS_REQUIRE_API_KEY", "true")
    monkeypatch.setenv("COMMERCELENS_ADMIN_TOKEN", "secret")
    monkeypatch.setenv("COMMERCELENS_JOBS_DB", str(tmp_path / "jobs.db"))
    client = TestClient(app)
    account = client.post(
        "/v1/accounts",
        headers={"X-Admin-Token": "secret"},
        json={"name": "Acme"},
    ).json()
    token = _create_key(client, account["id"])

    response = client.post(
        "/v1/extract/product",
        headers={"X-API-Key": token},
        json={"html": PRODUCT_HTML, "render": True},
    )
    records = client.get("/v1/extractions?status=failed", headers={"X-API-Key": token}).json()

    assert response.status_code == 400
    assert len(records) == 1
    assert records[0]["status"] == "failed"
    assert "render=true requires a URL" in records[0]["error"]
