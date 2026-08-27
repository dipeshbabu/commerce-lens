from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from commercelens.domain.models import (
    ChangeEventRecord,
    DomainIngestResult,
    MonitorRecord,
    ObservationRecord,
    OfferRecord,
    ProductRecord,
    SourceRecord,
)
from commercelens.jobs.models import JobRun, MonitoringJob, MonitoringJobCreate
from commercelens.schemas.product import Price, Product, ProductExtractionResult
from commercelens.storage.price_store import (
    ProductSnapshot,
    compare_snapshots,
    product_key_for,
)


def _stable_id(prefix: str, *parts: str) -> str:
    payload = "|".join(parts).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(payload).hexdigest()[:20]}"


def _normalized_url(url: str) -> str:
    parsed = urlsplit(url.strip())
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    if not scheme or not hostname:
        return url.strip()
    port = parsed.port
    default_port = 443 if scheme == "https" else 80
    netloc = hostname if port in {None, default_port} else f"{hostname}:{port}"
    return urlunsplit((scheme, netloc, parsed.path or "/", parsed.query, ""))


def _source_parts(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    domain = (parsed.hostname or parsed.netloc).lower()
    base_url = f"{parsed.scheme.lower()}://{domain}" if parsed.scheme and domain else url
    return domain, base_url


def _product_identity(result: ProductExtractionResult) -> tuple[str, str]:
    product = result.product
    metadata = product.metadata or {}
    for key in ("gtin", "gtin13", "gtin12", "ean", "upc", "isbn", "mpn"):
        value = metadata.get(key)
        if value:
            strong = f"{key}:{str(value).strip().lower()}"
            return strong, product_key_for(None, product.name, product.brand)
    url = product.canonical_url or product.source_url or result.url
    legacy = product_key_for(url, product.name, product.brand)
    return f"legacy:{legacy}", legacy


def ingest_product_extraction(
    repo: Any,
    result: ProductExtractionResult,
    *,
    account_id: str,
    project_id: str,
    monitor_id: str | None = None,
    job_id: str | None = None,
    run_id: str | None = None,
    extraction_id: str | None = None,
    captured_at: str | None = None,
    provenance: dict[str, Any] | None = None,
) -> DomainIngestResult:
    product = result.product
    raw_url = product.canonical_url or product.source_url or result.url
    if not raw_url:
        raise ValueError("A source or canonical URL is required to persist a commerce offer.")
    offer_url = _normalized_url(raw_url)
    domain, base_url = _source_parts(offer_url)
    if not domain:
        raise ValueError("The extracted product URL must include a hostname.")

    source = repo.find_source_by_domain(domain, account_id=account_id, project_id=project_id)
    if source is None:
        source = SourceRecord(
            id=_stable_id("src", account_id, project_id, domain),
            account_id=account_id,
            project_id=project_id,
            name=domain,
            domain=domain,
            base_url=base_url,
            metadata={"created_from": "extraction"},
        )
    else:
        source.base_url = source.base_url or base_url
    source = repo.save_source(source)

    identity_key, legacy_key = _product_identity(result)
    domain_product = repo.find_product_by_identity(
        identity_key, account_id=account_id, project_id=project_id
    )
    if domain_product is None:
        domain_product = ProductRecord(
            id=_stable_id("prod", account_id, project_id, identity_key),
            account_id=account_id,
            project_id=project_id,
            name=product.name,
            brand=product.brand,
            sku=product.sku,
            identity_key=identity_key,
            legacy_product_key=legacy_key,
            metadata={"identity_policy": "strong_identifier_or_legacy_offer_identity"},
        )
    else:
        domain_product.name = product.name or domain_product.name
        domain_product.brand = product.brand or domain_product.brand
        domain_product.sku = product.sku or domain_product.sku
        domain_product.legacy_product_key = domain_product.legacy_product_key or legacy_key
    domain_product = repo.save_product(domain_product)

    existing_offer = repo.find_offer_by_url(
        offer_url,
        source_id=source.id,
        account_id=account_id,
        project_id=project_id,
    )
    amount = product.price.amount if product.price else None
    currency = product.price.currency if product.price else None
    availability = product.availability.value if product.availability else None
    captured = captured_at or _captured_at_from_result(result)
    if existing_offer is None:
        offer = OfferRecord(
            id=_stable_id("offer", account_id, project_id, source.id, offer_url),
            account_id=account_id,
            project_id=project_id,
            product_id=domain_product.id,
            source_id=source.id,
            url=offer_url,
            canonical_url=product.canonical_url,
            seller_sku=product.sku,
            current_amount=amount,
            current_currency=currency,
            current_availability=availability,
            last_observed_at=captured,
            metadata={"legacy_product_key": legacy_key},
        )
    else:
        offer = existing_offer
        offer.product_id = domain_product.id
        offer.canonical_url = product.canonical_url or offer.canonical_url
        offer.seller_sku = product.sku or offer.seller_sku
        offer.current_amount = amount
        offer.current_currency = currency
        offer.current_availability = availability
        offer.last_observed_at = captured
    previous = repo.latest_observation(offer.id, account_id=account_id, project_id=project_id)
    offer = repo.save_offer(offer)

    raw_payload = result.model_dump(mode="json", exclude_none=True)
    observation_fingerprint = hashlib.sha256(
        json.dumps(raw_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    observation = ObservationRecord(
        id=_stable_id(
            "obs", account_id, project_id, offer.id, captured, observation_fingerprint
        ),
        account_id=account_id,
        project_id=project_id,
        source_id=source.id,
        product_id=domain_product.id,
        offer_id=offer.id,
        monitor_id=monitor_id,
        job_id=job_id,
        run_id=run_id,
        extraction_id=extraction_id,
        captured_at=captured,
        amount=amount,
        currency=currency,
        availability=availability,
        name=product.name,
        brand=product.brand,
        source_url=product.source_url or result.url,
        canonical_url=product.canonical_url,
        confidence=result.confidence,
        provenance={
            "extraction_confidence": result.confidence,
            "warnings": list(result.warnings),
            "field_sources": {
                name: field.source for name, field in result.fields.items() if field.source
            },
            **(provenance or {}),
        },
        raw_payload=raw_payload,
    )
    observation = repo.save_observation(observation)

    change = (
        _change_from_observations(previous, observation)
        if previous and previous.id != observation.id
        else None
    )
    if change:
        change = repo.save_change_event(change)
    return DomainIngestResult(
        source=source,
        product=domain_product,
        offer=offer,
        observation=observation,
        change=change,
    )


def _captured_at_from_result(result: ProductExtractionResult) -> str:
    captured = result.product.metadata.get("captured_at") if result.product.metadata else None
    if captured:
        return str(captured)
    from commercelens.domain.models import utc_now_iso

    return utc_now_iso()


def _observation_snapshot(observation: ObservationRecord) -> ProductSnapshot:
    return ProductSnapshot(
        product_key=observation.product_id,
        source_url=observation.source_url,
        canonical_url=observation.canonical_url,
        name=observation.name,
        brand=observation.brand,
        amount=observation.amount,
        currency=observation.currency,
        availability=observation.availability,
        image_url=None,
        captured_at=observation.captured_at,
        raw=observation.raw_payload,
    )


def _change_from_observations(
    previous: ObservationRecord, current: ObservationRecord
) -> ChangeEventRecord | None:
    price_change = compare_snapshots(
        _observation_snapshot(previous), _observation_snapshot(current)
    )
    if not price_change:
        return None
    dedupe_key = hashlib.sha256(
        f"{previous.id}|{current.id}|{price_change.change_type}".encode("utf-8")
    ).hexdigest()
    return ChangeEventRecord(
        id=_stable_id("chg", current.account_id, current.project_id, dedupe_key),
        account_id=current.account_id,
        project_id=current.project_id,
        source_id=current.source_id,
        product_id=current.product_id,
        offer_id=current.offer_id,
        observation_id=current.id,
        previous_observation_id=previous.id,
        monitor_id=current.monitor_id,
        job_id=current.job_id,
        run_id=current.run_id,
        event_type=price_change.change_type,
        severity=_change_severity(price_change.change_type, current.availability),
        previous_amount=price_change.previous_amount,
        current_amount=price_change.current_amount,
        currency=price_change.currency,
        delta=price_change.delta,
        delta_percent=price_change.delta_percent,
        previous_availability=price_change.previous_availability,
        current_availability=price_change.current_availability,
        changed_at=price_change.changed_at,
        dedupe_key=dedupe_key,
        provenance={"comparison": "legacy_snapshot_semantics"},
    )


def _change_severity(event_type: str, availability: str | None) -> str:
    if availability == "out_of_stock" or event_type == "availability_change":
        return "warning"
    if event_type in {"price_drop", "price_increase", "back_in_stock"}:
        return "info"
    return "info"


def monitor_from_job_create(request: MonitoringJobCreate) -> MonitorRecord | None:
    if not request.account_id or not request.project_id:
        return None
    return MonitorRecord(
        account_id=request.account_id,
        project_id=request.project_id,
        name=request.name,
        config=request.config,
        schedule_kind=request.schedule_kind.value,
        interval_minutes=request.interval_minutes,
        status="active",
        tags=list(request.tags),
        metadata={"compatibility_config_shadow": True},
    )


def bind_monitor_to_job(repo: Any, monitor: MonitorRecord, job: MonitoringJob) -> MonitorRecord:
    monitor.job_id = job.id
    monitor.name = job.name
    monitor.config = job.config
    monitor.schedule_kind = job.schedule_kind.value
    monitor.interval_minutes = job.interval_minutes
    monitor.status = job.status.value
    monitor.tags = list(job.tags)
    return repo.save_monitor(monitor)


def sync_monitor_from_job(repo: Any, job: MonitoringJob) -> MonitorRecord | None:
    if not job.account_id or not job.project_id:
        return None
    monitor = None
    if job.monitor_id:
        monitor = repo.get_monitor(
            job.monitor_id, account_id=job.account_id, project_id=job.project_id
        )
    if monitor is None:
        monitor = repo.find_monitor_by_job(
            job.id, account_id=job.account_id, project_id=job.project_id
        )
    if monitor is None:
        monitor = MonitorRecord(
            account_id=job.account_id,
            project_id=job.project_id,
            job_id=job.id,
            name=job.name,
            config=job.config,
            schedule_kind=job.schedule_kind.value,
            interval_minutes=job.interval_minutes,
            status=job.status.value,
            tags=list(job.tags),
            metadata={"migrated_from_job": True, "compatibility_config_shadow": True},
        )
    return bind_monitor_to_job(repo, monitor, job)


def effective_job_config(repo: Any, job: MonitoringJob):
    if not job.monitor_id or not job.account_id or not job.project_id:
        return job.config
    monitor = repo.get_monitor(
        job.monitor_id, account_id=job.account_id, project_id=job.project_id
    )
    return monitor.config if monitor else job.config


def ingest_monitor_snapshot(
    repo: Any,
    snapshot: ProductSnapshot,
    *,
    account_id: str,
    project_id: str,
    monitor_id: str | None = None,
    job_id: str | None = None,
    run_id: str | None = None,
    provenance: dict[str, Any] | None = None,
) -> DomainIngestResult:
    try:
        result = ProductExtractionResult.model_validate(snapshot.raw)
    except Exception:
        price = (
            Price(amount=snapshot.amount, currency=snapshot.currency)
            if snapshot.amount is not None or snapshot.currency
            else None
        )
        result = ProductExtractionResult(
            url=snapshot.source_url,
            product=Product(
                name=snapshot.name,
                brand=snapshot.brand,
                price=price,
                availability=snapshot.availability or "unknown",
                canonical_url=snapshot.canonical_url,
                source_url=snapshot.source_url,
            ),
        )
    return ingest_product_extraction(
        repo,
        result,
        account_id=account_id,
        project_id=project_id,
        monitor_id=monitor_id,
        job_id=job_id,
        run_id=run_id,
        captured_at=snapshot.captured_at,
        provenance={"legacy_snapshot_key": snapshot.product_key, **(provenance or {})},
    )


def make_job_result_sink(repo: Any, job: MonitoringJob, run: JobRun):
    if not job.account_id or not job.project_id:
        return None

    def _sink(monitor_result: Any) -> None:
        ingest_monitor_snapshot(
            repo,
            monitor_result.snapshot,
            account_id=job.account_id or "",
            project_id=job.project_id or "",
            monitor_id=job.monitor_id,
            job_id=job.id,
            run_id=run.id,
            provenance={"capture_path": "monitor_worker"},
        )

    return _sink
