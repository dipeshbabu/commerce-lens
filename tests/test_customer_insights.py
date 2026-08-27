from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from commercelens.alerts.config import MonitorConfig, MonitorTarget
from commercelens.api.main import app
from commercelens.api.portal_auth import CSRF_COOKIE_NAME, LOGIN_CSRF_COOKIE_NAME
from commercelens.domain.insights import ChangeFeedFilters, build_change_feed, build_product_comparison
from commercelens.domain.models import ChangeEventRecord, ProductMatchRecord, ProductMatchStatus
from commercelens.domain.repository import domain_repository_for_store
from commercelens.domain.service import ingest_product_extraction
from commercelens.jobs.models import (
    AccountCreate,
    AccountStatus,
    ApiKeyCreate,
    MonitoringJobCreate,
    ProjectCreate,
)
from commercelens.jobs.store import JobStore
from commercelens.schemas.product import Availability, Price, Product, ProductExtractionResult


def _workspace(store: JobStore, name: str = "Acme"):
    account = store.create_account(
        AccountCreate(name=name, owner=f"{name.lower()}@example.com", status=AccountStatus.active)
    )
    project = store.create_project(account.id, ProjectCreate(name="Competitive"))
    return account, project


def _key(store: JobStore, account_id: str, project_id: str | None):
    return store.create_api_key(
        ApiKeyCreate(
            name="insights",
            account_id=account_id,
            project_id=project_id,
            scopes=["*"],
        )
    )


def _login(client: TestClient, token: str) -> str:
    page = client.get("/portal/login")
    login_csrf = page.cookies[LOGIN_CSRF_COOKIE_NAME]
    response = client.post(
        "/portal/login",
        data={"api_key": token, "csrf_token": login_csrf},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return client.cookies[CSRF_COOKIE_NAME]


def _product(url: str, amount: float, gtin: str, name: str = "Trail Shoe"):
    return ProductExtractionResult(
        url=url,
        product=Product(
            name=name,
            brand="Example",
            price=Price(amount=amount, currency="USD"),
            availability=Availability.IN_STOCK,
            source_url=url,
            metadata={"gtin": gtin},
        ),
        confidence=0.96,
    )


def _seed(store: JobStore, account_id: str, project_id: str):
    repo = domain_repository_for_store(store)
    job = store.create_job(
        MonitoringJobCreate(
            name="Footwear watch",
            config=MonitorConfig(targets=[MonitorTarget(url="https://store-a.example/trail")]),
            account_id=account_id,
            project_id=project_id,
            interval_minutes=60,
        )
    )
    run_one = store.mark_job_run_started(job)
    first = ingest_product_extraction(
        repo,
        _product("https://store-a.example/trail", 100.0, "00011111111111"),
        account_id=account_id,
        project_id=project_id,
        monitor_id=job.monitor_id,
        job_id=job.id,
        run_id=run_one.id,
        captured_at="2026-08-27T01:00:00+00:00",
        provenance={"fixture": "baseline"},
    )
    store.complete_run(run_one, result={}, event_count=0, delivery_count=0, warning_count=0)

    run_two = store.mark_job_run_started(job)
    second_store = ingest_product_extraction(
        repo,
        _product("https://store-b.example/trail", 95.0, "00011111111111"),
        account_id=account_id,
        project_id=project_id,
        monitor_id=job.monitor_id,
        job_id=job.id,
        run_id=run_two.id,
        captured_at="2026-08-27T01:30:00+00:00",
        provenance={"fixture": "second-store"},
    )
    store.complete_run(run_two, result={}, event_count=0, delivery_count=0, warning_count=0)

    run_three = store.mark_job_run_started(job)
    changed = ingest_product_extraction(
        repo,
        _product("https://store-a.example/trail", 80.0, "00011111111111"),
        account_id=account_id,
        project_id=project_id,
        monitor_id=job.monitor_id,
        job_id=job.id,
        run_id=run_three.id,
        captured_at="2026-08-27T02:00:00+00:00",
        provenance={"fixture": "price-drop", "parser": "jsonld"},
    )
    store.complete_run(run_three, result={}, event_count=1, delivery_count=0, warning_count=0)
    assert changed.change is not None

    equivalent = ingest_product_extraction(
        repo,
        _product(
            "https://store-c.example/trail-pro",
            90.0,
            "00022222222222",
            name="Trail Shoe Pro",
        ),
        account_id=account_id,
        project_id=project_id,
        captured_at="2026-08-27T02:15:00+00:00",
        provenance={"fixture": "equivalent"},
    )
    match = repo.save_product_match(
        ProductMatchRecord(
            account_id=account_id,
            project_id=project_id,
            left_product_id=min(first.product.id, equivalent.product.id),
            right_product_id=max(first.product.id, equivalent.product.id),
            confidence=0.93,
            status=ProductMatchStatus.confirmed,
            method="catalog-review",
            metadata={"reviewer": "fixture"},
        )
    )
    return repo, job, first, second_store, changed, equivalent, match, run_three


def test_change_feed_summarizes_changes_and_filters_source_and_time(tmp_path) -> None:
    store = JobStore(tmp_path / "jobs.db")
    account, project = _workspace(store)
    repo, _, _, _, changed, _, _, run = _seed(store, account.id, project.id)

    entries = build_change_feed(
        repo,
        account_id=account.id,
        project_id=project.id,
        filters=ChangeFeedFilters(
            source_id=changed.source.id,
            event_type="price_drop",
            since="2026-08-27T01:59:00+00:00",
            until="2026-08-27T02:01:00+00:00",
        ),
        job_store=store,
        now=datetime(2026, 8, 27, 2, 30, tzinfo=timezone.utc),
    )

    assert len(entries) == 1
    entry = entries[0]
    assert "dropped from 100 USD to 80 USD" in entry.summary
    assert entry.event.run_id == run.id
    assert entry.observation is not None
    assert entry.extraction_confidence == 0.96
    assert entry.extraction_provenance["fixture"] == "price-drop"
    assert entry.partial is False
    assert entry.stale is False

    assert (
        build_change_feed(
            repo,
            account_id=account.id,
            project_id=project.id,
            filters=ChangeFeedFilters(source_id="src_missing"),
            job_store=store,
        )
        == []
    )


def test_product_comparison_groups_store_offers_matches_and_history(tmp_path) -> None:
    store = JobStore(tmp_path / "jobs.db")
    account, project = _workspace(store)
    repo, _, first, _, _, equivalent, match, _ = _seed(store, account.id, project.id)

    comparison = build_product_comparison(
        repo,
        account_id=account.id,
        project_id=project.id,
        product_id=first.product.id,
        job_store=store,
        now=datetime(2026, 8, 27, 2, 30, tzinfo=timezone.utc),
    )
    assert comparison is not None
    assert len(comparison.offers) == 2
    assert {view.source.domain for view in comparison.offers if view.source} == {
        "store-a.example",
        "store-b.example",
    }
    assert len(comparison.equivalent_products) == 1
    matched = comparison.equivalent_products[0]
    assert matched.product.id == equivalent.product.id
    assert matched.match.id == match.id
    assert matched.match.confidence == 0.93
    assert matched.match.method == "catalog-review"
    assert len(matched.offers) == 1
    assert comparison.price_history
    assert comparison.recent_changes[0].event.event_type == "price_drop"
    assert comparison.stale is False


def test_insights_report_stale_and_partial_data_without_crashing(tmp_path) -> None:
    store = JobStore(tmp_path / "jobs.db")
    account, project = _workspace(store)
    repo, _, first, _, changed, _, _, _ = _seed(store, account.id, project.id)

    stale = build_product_comparison(
        repo,
        account_id=account.id,
        project_id=project.id,
        product_id=first.product.id,
        now=datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc),
    )
    assert stale is not None
    assert stale.stale is True
    assert all(view.stale for view in stale.offers)

    repo.save_change_event(
        ChangeEventRecord(
            account_id=account.id,
            project_id=project.id,
            source_id="src_missing",
            product_id="prod_missing",
            offer_id="offer_missing",
            observation_id="obs_missing",
            previous_observation_id=changed.observation.id,
            event_type="availability_change",
            severity="warning",
            changed_at="2026-08-27T02:30:00+00:00",
            dedupe_key="partial-fixture",
        )
    )
    partial = build_change_feed(
        repo,
        account_id=account.id,
        project_id=project.id,
        filters=ChangeFeedFilters(severity="warning"),
        job_store=store,
    )
    assert len(partial) == 1
    assert partial[0].partial is True
    assert partial[0].warnings


def test_customer_insight_api_and_portal_preserve_tenant_scope(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "jobs.db"
    monkeypatch.setenv("COMMERCELENS_JOBS_DB", str(db_path))
    monkeypatch.setenv("COMMERCELENS_REQUIRE_API_KEY", "true")
    store = JobStore(db_path)
    account, project = _workspace(store, "First")
    other_account, other_project = _workspace(store, "Second")
    repo, _, first, _, changed, _, _, run = _seed(store, account.id, project.id)
    project_key = _key(store, account.id, project.id)
    account_key = _key(store, account.id, None)
    other_key = _key(store, other_account.id, other_project.id)
    client = TestClient(app, base_url="https://testserver")

    feed = client.get(
        "/v1/change-feed",
        headers={"X-API-Key": project_key.token},
        params={"event_type": "price_drop"},
    )
    assert feed.status_code == 200
    assert feed.json()[0]["event"]["run_id"] == run.id
    assert "dropped from" in feed.json()[0]["summary"]

    account_feed = client.get(
        "/v1/change-feed",
        headers={"X-API-Key": account_key.token},
        params={"project_id": project.id},
    )
    assert account_feed.status_code == 200
    wrong_project = client.get(
        "/v1/change-feed",
        headers={"X-API-Key": account_key.token},
        params={"project_id": other_project.id},
    )
    assert wrong_project.status_code == 404

    comparison = client.get(
        f"/v1/products/{first.product.id}/comparison",
        headers={"X-API-Key": project_key.token},
    )
    assert comparison.status_code == 200
    assert len(comparison.json()["offers"]) == 2
    history = client.get(
        f"/v1/products/{first.product.id}/history",
        headers={"X-API-Key": project_key.token},
    )
    assert history.status_code == 200
    assert len(history.json()) >= 3

    _login(client, project_key.token)
    page = client.get("/portal/changes")
    assert page.status_code == 200
    assert "Trail Shoe dropped from 100 USD to 80 USD" in page.text
    assert f"/portal/observations/{changed.observation.id}" in page.text
    assert f"/portal/runs/{run.id}" in page.text
    product_page = client.get(f"/portal/products/{first.product.id}")
    assert product_page.status_code == 200
    assert "store-a.example" in product_page.text
    assert "store-b.example" in product_page.text
    assert "Trail Shoe Pro" in product_page.text
    assert "0.93" in product_page.text
    assert "Price history" in product_page.text

    changes_export = client.get(
        "/portal/export/changes",
        params={"event_type": "price_drop", "source_id": changed.source.id},
    )
    assert changes_export.status_code == 200
    assert "attachment" in changes_export.headers["content-disposition"]
    exported = changes_export.json()
    assert exported["project_id"] == project.id
    assert len(exported["changes"]) == 1

    comparison_export = client.get(f"/portal/export/products/{first.product.id}/comparison")
    assert comparison_export.status_code == 200
    assert comparison_export.json()["product"]["id"] == first.product.id

    client = TestClient(app, base_url="https://testserver")
    _login(client, other_key.token)
    hidden = client.get(
        f"/portal/products/{first.product.id}", params={"project_id": project.id}
    )
    assert hidden.status_code == 404

    assert repo.list_change_events(account_id=account.id, project_id=project.id)


def test_portal_handles_empty_insight_states(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "jobs.db"
    monkeypatch.setenv("COMMERCELENS_JOBS_DB", str(db_path))
    monkeypatch.setenv("COMMERCELENS_REQUIRE_API_KEY", "true")
    store = JobStore(db_path)
    account, project = _workspace(store)
    access = _key(store, account.id, project.id)
    client = TestClient(app, base_url="https://testserver")
    _login(client, access.token)

    changes = client.get("/portal/changes")
    products = client.get("/portal/products")
    assert changes.status_code == 200
    assert "No matching changes" in changes.text
    assert products.status_code == 200
    assert "No products yet" in products.text
