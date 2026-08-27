from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, Field

from commercelens.domain.models import (
    ChangeEventRecord,
    ObservationRecord,
    OfferRecord,
    ProductMatchRecord,
    ProductRecord,
    SourceRecord,
)


class ChangeFeedFilters(BaseModel):
    source_id: str | None = None
    event_type: str | None = None
    severity: str | None = None
    since: str | None = None
    until: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)


class PriceHistoryPoint(BaseModel):
    observation_id: str
    captured_at: str
    amount: float | None = None
    currency: str | None = None
    availability: str | None = None
    confidence: float | None = None
    source_id: str
    offer_id: str


class OfferComparison(BaseModel):
    offer: OfferRecord
    source: SourceRecord | None = None
    latest_observation: ObservationRecord | None = None
    history: list[PriceHistoryPoint] = Field(default_factory=list)
    stale: bool = False
    stale_after_minutes: int | None = None
    partial: bool = False
    warnings: list[str] = Field(default_factory=list)


class EquivalentProduct(BaseModel):
    product: ProductRecord
    match: ProductMatchRecord
    offers: list[OfferComparison] = Field(default_factory=list)


class ProductComparison(BaseModel):
    product: ProductRecord
    offers: list[OfferComparison] = Field(default_factory=list)
    equivalent_products: list[EquivalentProduct] = Field(default_factory=list)
    recent_changes: list[ChangeFeedEntry] = Field(default_factory=list)
    price_history: list[PriceHistoryPoint] = Field(default_factory=list)
    stale: bool = False
    partial: bool = False
    warnings: list[str] = Field(default_factory=list)


class ChangeFeedEntry(BaseModel):
    event: ChangeEventRecord
    product: ProductRecord | None = None
    offer: OfferRecord | None = None
    source: SourceRecord | None = None
    observation: ObservationRecord | None = None
    previous_observation: ObservationRecord | None = None
    monitor_name: str | None = None
    extraction_confidence: float | None = None
    extraction_provenance: dict[str, Any] = Field(default_factory=dict)
    summary: str
    stale: bool = False
    partial: bool = False
    warnings: list[str] = Field(default_factory=list)


ProductComparison.model_rebuild()


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid datetime: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _default_stale_minutes() -> int:
    raw = os.getenv("COMMERCELENS_STALE_AFTER_MINUTES", "1440")
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError("COMMERCELENS_STALE_AFTER_MINUTES must be an integer.") from exc
    if value < 1:
        raise RuntimeError("COMMERCELENS_STALE_AFTER_MINUTES must be at least 1.")
    return value


def stale_after_minutes(repo: Any, observation: ObservationRecord | None) -> int:
    if observation and observation.monitor_id:
        monitor = repo.get_monitor(
            observation.monitor_id,
            account_id=observation.account_id,
            project_id=observation.project_id,
        )
        if monitor and monitor.schedule_kind == "interval":
            return max(60, monitor.interval_minutes * 2)
    return _default_stale_minutes()


def observation_is_stale(
    repo: Any,
    observation: ObservationRecord | None,
    *,
    now: datetime | None = None,
) -> tuple[bool, int]:
    threshold = stale_after_minutes(repo, observation)
    if observation is None:
        return True, threshold
    captured = parse_datetime(observation.captured_at)
    if captured is None:
        return True, threshold
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return current - captured > timedelta(minutes=threshold), threshold


def _price_text(amount: float | None, currency: str | None) -> str:
    if amount is None:
        return "unknown price"
    suffix = f" {currency}" if currency else ""
    return f"{amount:g}{suffix}"


def summarize_change(event: ChangeEventRecord, product_name: str | None = None) -> str:
    name = product_name or "Product"
    if event.event_type == "price_drop":
        return (
            f"{name} dropped from {_price_text(event.previous_amount, event.currency)} "
            f"to {_price_text(event.current_amount, event.currency)}."
        )
    if event.event_type == "price_increase":
        return (
            f"{name} increased from {_price_text(event.previous_amount, event.currency)} "
            f"to {_price_text(event.current_amount, event.currency)}."
        )
    if event.event_type == "back_in_stock":
        return f"{name} is back in stock."
    if event.event_type in {"availability_change", "price_and_availability_change"}:
        before = event.previous_availability or "unknown"
        after = event.current_availability or "unknown"
        return f"{name} availability changed from {before} to {after}."
    return f"{name} changed ({event.event_type.replace('_', ' ')})."


def build_change_feed(
    repo: Any,
    *,
    account_id: str,
    project_id: str,
    filters: ChangeFeedFilters | None = None,
    job_store: Any | None = None,
    now: datetime | None = None,
) -> list[ChangeFeedEntry]:
    filters = filters or ChangeFeedFilters()
    since = parse_datetime(filters.since)
    until = parse_datetime(filters.until)
    if since and until and since > until:
        raise ValueError("since must be before until")

    events = repo.list_change_events(
        account_id=account_id,
        project_id=project_id,
        event_type=filters.event_type,
        limit=max(filters.limit * 10, 1000),
    )
    products: dict[str, ProductRecord | None] = {}
    offers: dict[str, OfferRecord | None] = {}
    sources: dict[str, SourceRecord | None] = {}
    observations: dict[str, ObservationRecord | None] = {}
    monitors: dict[str, Any] = {}
    entries: list[ChangeFeedEntry] = []

    for event in events:
        changed_at = parse_datetime(event.changed_at)
        if filters.source_id and event.source_id != filters.source_id:
            continue
        if filters.severity and event.severity != filters.severity:
            continue
        if since and (changed_at is None or changed_at < since):
            continue
        if until and (changed_at is None or changed_at > until):
            continue

        if event.product_id not in products:
            products[event.product_id] = repo.get_product(
                event.product_id, account_id=account_id, project_id=project_id
            )
        if event.offer_id not in offers:
            offers[event.offer_id] = repo.get_offer(
                event.offer_id, account_id=account_id, project_id=project_id
            )
        if event.source_id not in sources:
            sources[event.source_id] = repo.get_source(
                event.source_id, account_id=account_id, project_id=project_id
            )
        for observation_id in (event.observation_id, event.previous_observation_id):
            if observation_id not in observations:
                observations[observation_id] = repo.get_observation(
                    observation_id, account_id=account_id, project_id=project_id
                )

        product = products[event.product_id]
        offer = offers[event.offer_id]
        source = sources[event.source_id]
        observation = observations[event.observation_id]
        previous = observations[event.previous_observation_id]
        warnings: list[str] = []
        if product is None:
            warnings.append("Product record is unavailable.")
        if offer is None:
            warnings.append("Offer record is unavailable.")
        if source is None:
            warnings.append("Source record is unavailable.")
        if observation is None:
            warnings.append("Responsible observation is unavailable.")
        if previous is None:
            warnings.append("Previous observation is unavailable.")
        if event.run_id and job_store is not None:
            run = job_store.get_run(event.run_id, account_id=account_id, project_id=project_id)
            if run is None:
                warnings.append("Responsible monitor run is unavailable.")
        monitor_name = None
        if event.monitor_id:
            if event.monitor_id not in monitors:
                monitors[event.monitor_id] = repo.get_monitor(
                    event.monitor_id, account_id=account_id, project_id=project_id
                )
            monitor = monitors[event.monitor_id]
            monitor_name = monitor.name if monitor else None
            if monitor is None:
                warnings.append("Monitor record is unavailable.")
        stale, _ = observation_is_stale(repo, observation, now=now)
        entries.append(
            ChangeFeedEntry(
                event=event,
                product=product,
                offer=offer,
                source=source,
                observation=observation,
                previous_observation=previous,
                monitor_name=monitor_name,
                extraction_confidence=observation.confidence if observation else None,
                extraction_provenance=observation.provenance if observation else {},
                summary=summarize_change(event, product.name if product else None),
                stale=stale,
                partial=bool(warnings),
                warnings=warnings,
            )
        )
        if len(entries) >= filters.limit:
            break
    return entries


def _offer_view(
    repo: Any,
    offer: OfferRecord,
    *,
    account_id: str,
    project_id: str,
    history_limit: int,
    now: datetime | None,
) -> OfferComparison:
    source = repo.get_source(offer.source_id, account_id=account_id, project_id=project_id)
    observations = repo.list_observations(
        account_id=account_id,
        project_id=project_id,
        offer_id=offer.id,
        limit=history_limit,
    )
    latest = observations[0] if observations else None
    stale, stale_minutes = observation_is_stale(repo, latest, now=now)
    warnings: list[str] = []
    if source is None:
        warnings.append("Source record is unavailable.")
    if latest is None:
        warnings.append("No observations are available for this offer yet.")
    history = [
        PriceHistoryPoint(
            observation_id=item.id,
            captured_at=item.captured_at,
            amount=item.amount,
            currency=item.currency,
            availability=item.availability,
            confidence=item.confidence,
            source_id=item.source_id,
            offer_id=item.offer_id,
        )
        for item in observations
    ]
    return OfferComparison(
        offer=offer,
        source=source,
        latest_observation=latest,
        history=history,
        stale=stale,
        stale_after_minutes=stale_minutes,
        partial=bool(warnings),
        warnings=warnings,
    )


def build_product_comparison(
    repo: Any,
    *,
    account_id: str,
    project_id: str,
    product_id: str,
    job_store: Any | None = None,
    history_limit: int = 100,
    change_limit: int = 25,
    now: datetime | None = None,
) -> ProductComparison | None:
    product = repo.get_product(product_id, account_id=account_id, project_id=project_id)
    if product is None:
        return None
    offers = repo.list_offers(
        account_id=account_id,
        project_id=project_id,
        product_id=product.id,
        limit=500,
    )
    offer_views = [
        _offer_view(
            repo,
            offer,
            account_id=account_id,
            project_id=project_id,
            history_limit=history_limit,
            now=now,
        )
        for offer in offers
    ]

    equivalents: list[EquivalentProduct] = []
    for match in repo.list_product_matches(
        account_id=account_id, project_id=project_id, limit=1000
    ):
        if match.status.value == "rejected":
            continue
        if product.id not in {match.left_product_id, match.right_product_id}:
            continue
        other_id = (
            match.right_product_id if match.left_product_id == product.id else match.left_product_id
        )
        other = repo.get_product(other_id, account_id=account_id, project_id=project_id)
        if other is None:
            continue
        other_offers = repo.list_offers(
            account_id=account_id,
            project_id=project_id,
            product_id=other.id,
            limit=500,
        )
        equivalents.append(
            EquivalentProduct(
                product=other,
                match=match,
                offers=[
                    _offer_view(
                        repo,
                        offer,
                        account_id=account_id,
                        project_id=project_id,
                        history_limit=history_limit,
                        now=now,
                    )
                    for offer in other_offers
                ],
            )
        )

    change_entries = build_change_feed(
        repo,
        account_id=account_id,
        project_id=project_id,
        filters=ChangeFeedFilters(limit=max(change_limit * 20, 500)),
        job_store=job_store,
        now=now,
    )
    related_ids = {product.id, *(item.product.id for item in equivalents)}
    recent_changes = [entry for entry in change_entries if entry.event.product_id in related_ids][
        :change_limit
    ]

    all_offer_views = offer_views + [offer for item in equivalents for offer in item.offers]
    history = [point for view in all_offer_views for point in view.history]
    history.sort(
        key=lambda item: (
            parse_datetime(item.captured_at) or datetime.min.replace(tzinfo=timezone.utc)
        ),
        reverse=True,
    )
    warnings: list[str] = []
    if not offers:
        warnings.append("No direct offers are available for this product yet.")
    if any(view.partial for view in all_offer_views):
        warnings.append("Some comparison data is incomplete.")
    stale = bool(all_offer_views) and all(view.stale for view in all_offer_views)
    if not all_offer_views:
        stale = True
    return ProductComparison(
        product=product,
        offers=offer_views,
        equivalent_products=equivalents,
        recent_changes=recent_changes,
        price_history=history,
        stale=stale,
        partial=bool(warnings),
        warnings=warnings,
    )
