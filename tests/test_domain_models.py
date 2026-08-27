from __future__ import annotations

from commercelens.alerts.config import MonitorConfig, MonitorTarget
from commercelens.domain.repository import SQLiteDomainRepository, domain_repository_for_store
from commercelens.domain.service import effective_job_config, ingest_product_extraction
from commercelens.jobs.models import (
    AccountCreate,
    AccountStatus,
    MonitoringJob,
    MonitoringJobCreate,
    MonitoringJobUpdate,
    ProjectCreate,
)
from commercelens.jobs.store import JobStore
from commercelens.schemas.product import Availability, Price, Product, ProductExtractionResult


def _extraction(
    url: str, *, amount: float, gtin: str = "00012345678905"
) -> ProductExtractionResult:
    return ProductExtractionResult(
        url=url,
        product=Product(
            name="Trail Shoe",
            brand="Example",
            price=Price(amount=amount, currency="usd"),
            availability=Availability.IN_STOCK,
            source_url=url,
            metadata={"gtin": gtin},
        ),
        confidence=0.96,
    )


def _workspace(store: JobStore):
    account = store.create_account(
        AccountCreate(name="Acme", owner="owner@example.com", status=AccountStatus.active)
    )
    project = store.create_project(account.id, ProjectCreate(name="Competitors"))
    return account, project


def test_domain_ingest_supports_multiple_offers_and_deduplicated_changes(tmp_path) -> None:
    repo = SQLiteDomainRepository(tmp_path / "domain.db")
    account_id = "acct_test"
    project_id = "proj_test"

    first = ingest_product_extraction(
        repo,
        _extraction("https://store-a.example/products/trail", amount=100.0),
        account_id=account_id,
        project_id=project_id,
        captured_at="2026-08-26T10:00:00+00:00",
        provenance={"fixture": "first"},
    )
    second_store = ingest_product_extraction(
        repo,
        _extraction("https://store-b.example/item/trail", amount=95.0),
        account_id=account_id,
        project_id=project_id,
        captured_at="2026-08-26T10:01:00+00:00",
    )

    assert first.product.id == second_store.product.id
    offers = repo.list_offers(
        account_id=account_id,
        project_id=project_id,
        product_id=first.product.id,
    )
    assert len(offers) == 2
    assert {offer.source_id for offer in offers} == {first.source.id, second_store.source.id}

    changed = ingest_product_extraction(
        repo,
        _extraction("https://store-a.example/products/trail", amount=80.0),
        account_id=account_id,
        project_id=project_id,
        captured_at="2026-08-26T11:00:00+00:00",
        provenance={"fixture": "price-drop"},
    )
    assert changed.change is not None
    assert changed.change.event_type == "price_drop"
    assert changed.change.previous_amount == 100.0
    assert changed.change.current_amount == 80.0

    replay = ingest_product_extraction(
        repo,
        _extraction("https://store-a.example/products/trail", amount=80.0),
        account_id=account_id,
        project_id=project_id,
        captured_at="2026-08-26T11:00:00+00:00",
        provenance={"fixture": "price-drop"},
    )
    assert replay.change is None
    assert len(repo.list_change_events(account_id=account_id, project_id=project_id)) == 1

    observations = repo.list_observations(
        account_id=account_id,
        project_id=project_id,
        offer_id=first.offer.id,
    )
    assert len(observations) == 2
    latest = observations[0]
    assert latest.source_id == first.source.id
    assert latest.amount == 80.0
    assert latest.currency == "USD"
    assert latest.availability == "in_stock"
    assert latest.provenance["fixture"] == "price-drop"


def test_domain_repository_enforces_tenant_scope(tmp_path) -> None:
    repo = SQLiteDomainRepository(tmp_path / "domain.db")
    ingested = ingest_product_extraction(
        repo,
        _extraction("https://store.example/products/trail", amount=100.0),
        account_id="acct_one",
        project_id="proj_one",
    )

    assert (
        repo.get_product(
            ingested.product.id,
            account_id="acct_other",
            project_id="proj_one",
        )
        is None
    )
    assert (
        repo.get_offer(
            ingested.offer.id,
            account_id="acct_one",
            project_id="proj_other",
        )
        is None
    )


def test_new_jobs_reference_persisted_monitors_and_legacy_jobs_keep_config(tmp_path) -> None:
    db_path = tmp_path / "jobs.db"
    store = JobStore(db_path)
    account, project = _workspace(store)
    config = MonitorConfig(targets=[MonitorTarget(url="https://store.example/product")])

    job = store.create_job(
        MonitoringJobCreate(
            name="Competitor watch",
            config=config,
            account_id=account.id,
            project_id=project.id,
        )
    )
    assert job.monitor_id is not None
    repo = domain_repository_for_store(store)
    monitor = repo.get_monitor(job.monitor_id, account_id=account.id, project_id=project.id)
    assert monitor is not None
    assert monitor.job_id == job.id
    assert monitor.config == config

    updated = store.update_job(
        job.id,
        MonitoringJobUpdate(name="Updated watch", interval_minutes=45),
        account_id=account.id,
        project_id=project.id,
    )
    assert updated is not None
    monitor = repo.get_monitor(job.monitor_id, account_id=account.id, project_id=project.id)
    assert monitor is not None
    assert monitor.name == "Updated watch"
    assert monitor.interval_minutes == 45

    legacy = MonitoringJob(name="Legacy", config=config)
    assert legacy.monitor_id is None
    assert effective_job_config(repo, legacy) == config
