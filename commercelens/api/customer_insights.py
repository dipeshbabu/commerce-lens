from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response

from commercelens.api.auth import get_job_store, require_api_key
from commercelens.api.portal_auth import require_portal_session, set_private_response_headers
from commercelens.api.portal_management_core import _available_projects, _page, _select_project
from commercelens.api.presentation import escape_html as esc, table
from commercelens.api.quota import require_scope
from commercelens.domain.insights import (
    ChangeFeedEntry,
    ChangeFeedFilters,
    ProductComparison,
    build_change_feed,
    build_product_comparison,
    observation_is_stale,
    parse_datetime,
)
from commercelens.domain.repository import domain_repository_for_store
from commercelens.jobs.models import ApiKeyRecord

router = APIRouter()


def _api_project(store: Any, key: ApiKeyRecord | None, requested: str | None) -> tuple[str, str]:
    if key is None or not key.account_id:
        raise HTTPException(
            status_code=400,
            detail="Customer insight APIs require an account scoped API key.",
        )
    if key.project_id:
        if requested and requested != key.project_id:
            raise HTTPException(status_code=404, detail="Project not found.")
        return key.account_id, key.project_id
    if not requested:
        raise HTTPException(
            status_code=400,
            detail="project_id is required for an account scoped API key.",
        )
    project = store.get_project(requested, account_id=key.account_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    return key.account_id, project.id


def _filters(
    *,
    source_id: str | None,
    event_type: str | None,
    severity: str | None,
    since: str | None,
    until: str | None,
    limit: int,
) -> ChangeFeedFilters:
    try:
        filters = ChangeFeedFilters(
            source_id=source_id or None,
            event_type=event_type or None,
            severity=severity or None,
            since=since or None,
            until=until or None,
            limit=limit,
        )
        parse_datetime(filters.since)
        parse_datetime(filters.until)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return filters


def _feed(
    store: Any,
    *,
    account_id: str,
    project_id: str,
    filters: ChangeFeedFilters,
) -> list[ChangeFeedEntry]:
    repo = domain_repository_for_store(store)
    try:
        return build_change_feed(
            repo,
            account_id=account_id,
            project_id=project_id,
            filters=filters,
            job_store=store,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _comparison(
    store: Any,
    *,
    account_id: str,
    project_id: str,
    product_id: str,
) -> ProductComparison:
    repo = domain_repository_for_store(store)
    comparison = build_product_comparison(
        repo,
        account_id=account_id,
        project_id=project_id,
        product_id=product_id,
        job_store=store,
    )
    if comparison is None:
        raise HTTPException(status_code=404, detail="Product not found.")
    return comparison


def _download(name: str, payload: object) -> Response:
    response = Response(
        json.dumps(payload, indent=2, sort_keys=True, default=str),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
    set_private_response_headers(response)
    return response


def _project_selector(projects: list[Any], selected_id: str, path: str) -> str:
    if len(projects) <= 1:
        return ""
    options = "".join(
        f'<option value="{esc(project.id)}" {"selected" if project.id == selected_id else ""}>{esc(project.name)}</option>'
        for project in projects
    )
    return f"""
    <form class="inline-form insight-filter" method="get" action="{esc(path)}">
      <label>Project<select name="project_id">{options}</select></label>
      <button type="submit">Switch project</button>
    </form>
    """


def _query(params: dict[str, object | None]) -> str:
    values = {key: str(value) for key, value in params.items() if value not in {None, ""}}
    return "?" + urlencode(values) if values else ""


def _state_badges(*, stale: bool, partial: bool) -> str:
    badges: list[str] = []
    if stale:
        badges.append('<span class="badge stale">stale</span>')
    if partial:
        badges.append('<span class="badge partial">partial</span>')
    if not badges:
        badges.append('<span class="badge current">current</span>')
    return " ".join(badges)


def _price(amount: float | None, currency: str | None) -> str:
    if amount is None:
        return "—"
    suffix = f" {esc(currency)}" if currency else ""
    return f"{esc(f'{amount:g}')}{suffix}"


def _external_offer(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return f"<code>{esc(url)}</code>"
    return f'<a href="{esc(url)}" rel="noreferrer">{esc(url)}</a>'


def _sparkline(points: list[Any]) -> str:
    priced = [point for point in reversed(points) if point.amount is not None]
    if len(priced) < 2:
        return '<p class="muted">Not enough price history for a trend line yet.</p>'
    values = [float(point.amount) for point in priced if point.amount is not None]
    low, high = min(values), max(values)
    spread = high - low or 1.0
    width, height = 640.0, 160.0
    coords: list[str] = []
    for index, value in enumerate(values):
        x = 12.0 + (width - 24.0) * index / max(1, len(values) - 1)
        y = 12.0 + (height - 24.0) * (high - value) / spread
        coords.append(f"{x:.1f},{y:.1f}")
    label = f"Price history from {low:g} to {high:g}"
    return f"""
    <figure class="history-chart">
      <svg viewBox="0 0 640 160" role="img" aria-label="{esc(label)}" preserveAspectRatio="none">
        <polyline points="{" ".join(coords)}" fill="none" stroke="currentColor" stroke-width="3" vector-effect="non-scaling-stroke"></polyline>
      </svg>
      <figcaption class="muted">{esc(label)} across {len(values)} observations.</figcaption>
    </figure>
    """


def _change_rows(entries: list[ChangeFeedEntry]) -> list[list[object]]:
    rows: list[list[object]] = []
    for entry in entries:
        event = entry.event
        source = entry.source.name if entry.source else event.source_id
        links = [
            f'<a href="/portal/products/{esc(event.product_id)}?project_id={esc(event.project_id)}">Product</a>',
            f'<a href="/portal/observations/{esc(event.observation_id)}?project_id={esc(event.project_id)}">Observation</a>',
        ]
        if event.run_id:
            links.append(f'<a href="/portal/runs/{esc(event.run_id)}">Run</a>')
        details = ""
        if entry.warnings:
            details = (
                '<div class="help">' + " ".join(esc(item) for item in entry.warnings) + "</div>"
            )
        rows.append(
            [
                esc(event.changed_at),
                f"<strong>{esc(entry.summary)}</strong>{details}",
                esc(source),
                esc(event.event_type.replace("_", " ")),
                esc(event.severity),
                _price(event.previous_amount, event.currency),
                _price(event.current_amount, event.currency),
                esc(entry.extraction_confidence),
                _state_badges(stale=entry.stale, partial=entry.partial),
                " · ".join(links),
            ]
        )
    return rows


@router.get("/v1/change-feed", response_model=list[ChangeFeedEntry])
def change_feed_api(
    project_id: str | None = None,
    source_id: str | None = None,
    event_type: str | None = None,
    severity: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 100,
    store: Any = Depends(get_job_store),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> list[ChangeFeedEntry]:
    require_scope(key, "runs:read")
    account_id, selected_project_id = _api_project(store, key, project_id)
    filters = _filters(
        source_id=source_id,
        event_type=event_type,
        severity=severity,
        since=since,
        until=until,
        limit=limit,
    )
    return _feed(
        store,
        account_id=account_id,
        project_id=selected_project_id,
        filters=filters,
    )


@router.get("/v1/products/{product_id}/comparison", response_model=ProductComparison)
def product_comparison_api(
    product_id: str,
    project_id: str | None = None,
    store: Any = Depends(get_job_store),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> ProductComparison:
    require_scope(key, "extractions:read")
    account_id, selected_project_id = _api_project(store, key, project_id)
    return _comparison(
        store,
        account_id=account_id,
        project_id=selected_project_id,
        product_id=product_id,
    )


@router.get("/v1/products/{product_id}/history")
def product_history_api(
    product_id: str,
    project_id: str | None = None,
    store: Any = Depends(get_job_store),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> list[dict[str, Any]]:
    require_scope(key, "extractions:read")
    account_id, selected_project_id = _api_project(store, key, project_id)
    comparison = _comparison(
        store,
        account_id=account_id,
        project_id=selected_project_id,
        product_id=product_id,
    )
    return [point.model_dump(mode="json") for point in comparison.price_history]


@router.get("/portal/changes", response_class=HTMLResponse)
def portal_changes(
    request: Request,
    project_id: str | None = None,
    source_id: str | None = None,
    event_type: str | None = None,
    severity: str | None = None,
    since: str | None = None,
    until: str | None = None,
    store: Any = Depends(get_job_store),
) -> HTMLResponse:
    context = require_portal_session(request, store)
    selected = _select_project(store, context, project_id)
    if not selected:
        return _page(
            "Changes",
            '<h1>Change feed</h1><section class="notice warning" role="status">Create or select a project before viewing changes.</section>',
            context,
        )
    repo = domain_repository_for_store(store)
    projects = _available_projects(store, context)
    sources = repo.list_sources(
        account_id=context.key.account_id or "",
        project_id=selected.id,
        limit=200,
    )
    filters = _filters(
        source_id=source_id,
        event_type=event_type,
        severity=severity,
        since=since,
        until=until,
        limit=200,
    )
    entries = _feed(
        store,
        account_id=context.key.account_id or "",
        project_id=selected.id,
        filters=filters,
    )
    source_options = '<option value="">All sources</option>' + "".join(
        f'<option value="{esc(source.id)}" {"selected" if source.id == source_id else ""}>{esc(source.name)}</option>'
        for source in sources
    )
    event_values = [
        "price_drop",
        "price_increase",
        "back_in_stock",
        "availability_change",
        "price_and_availability_change",
    ]
    event_options = '<option value="">All changes</option>' + "".join(
        f'<option value="{esc(value)}" {"selected" if value == event_type else ""}>{esc(value.replace("_", " "))}</option>'
        for value in event_values
    )
    severity_options = '<option value="">All severities</option>' + "".join(
        f'<option value="{value}" {"selected" if value == severity else ""}>{value}</option>'
        for value in ("info", "warning", "critical")
    )
    export_query = _query(
        {
            "project_id": selected.id,
            "source_id": source_id,
            "event_type": event_type,
            "severity": severity,
            "since": since,
            "until": until,
        }
    )
    empty = (
        '<section class="notice warning" role="status"><strong>No matching changes.</strong> Adjust the filters or wait for another monitor observation.</section>'
        if not entries
        else ""
    )
    content = f"""
    <div class="page-heading">
      <div><h1>Change feed</h1><p class="muted">Business changes across monitored offers, newest first.</p></div>
      <a class="button-link" href="/portal/export/changes{export_query}">Export JSON</a>
    </div>
    {_project_selector(projects, selected.id, "/portal/changes")}
    <form class="form-grid insight-filter" method="get" action="/portal/changes" aria-label="Change feed filters">
      <input type="hidden" name="project_id" value="{esc(selected.id)}">
      <label>Source<select name="source_id">{source_options}</select></label>
      <label>Event type<select name="event_type">{event_options}</select></label>
      <label>Severity<select name="severity">{severity_options}</select></label>
      <label>Since<input type="datetime-local" name="since" value="{esc(since)}"></label>
      <label>Until<input type="datetime-local" name="until" value="{esc(until)}"></label>
      <button class="primary" type="submit">Apply filters</button>
    </form>
    {empty}
    <form id="change-export-form" class="action-row" method="get" action="/portal/export/changes">
      <input type="hidden" name="project_id" value="{esc(selected.id)}">
      <input type="hidden" name="source_id" value="{esc(source_id)}">
      <input type="hidden" name="event_type" value="{esc(event_type)}">
      <input type="hidden" name="severity" value="{esc(severity)}">
      <input type="hidden" name="since" value="{esc(since)}">
      <input type="hidden" name="until" value="{esc(until)}">
      <button type="submit">Export selected changes</button>
    </form>
    <section class="panel">
      {table(["Select", "Changed", "What happened", "Source", "Type", "Severity", "Before", "Now", "Confidence", "State", "Evidence"], [[f'<input type="checkbox" name="change_id" value="{esc(entry.event.id)}" form="change-export-form" aria-label="Select change {esc(entry.event.id)}">', *row] for entry, row in zip(entries, _change_rows(entries))])}
    </section>
    """
    return _page("Changes", content, context)


@router.get("/portal/products", response_class=HTMLResponse)
def portal_products(
    request: Request,
    project_id: str | None = None,
    store: Any = Depends(get_job_store),
) -> HTMLResponse:
    context = require_portal_session(request, store)
    selected = _select_project(store, context, project_id)
    if not selected:
        return _page(
            "Products",
            '<h1>Products</h1><section class="notice warning" role="status">Create or select a project before viewing products.</section>',
            context,
        )
    projects = _available_projects(store, context)
    repo = domain_repository_for_store(store)
    products = repo.list_products(
        account_id=context.key.account_id or "",
        project_id=selected.id,
        limit=500,
    )
    matches = repo.list_product_matches(
        account_id=context.key.account_id or "", project_id=selected.id, limit=2000
    )
    rows: list[list[object]] = []
    for product in products:
        direct_offers = repo.list_offers(
            account_id=context.key.account_id or "",
            project_id=selected.id,
            product_id=product.id,
            limit=500,
        )
        active_matches = [
            match
            for match in matches
            if match.status.value != "rejected"
            and product.id in {match.left_product_id, match.right_product_id}
        ]
        stale_flags: list[bool] = []
        partial = not direct_offers
        for offer in direct_offers:
            latest = repo.latest_observation(
                offer.id,
                account_id=context.key.account_id or "",
                project_id=selected.id,
            )
            stale, _ = observation_is_stale(repo, latest)
            stale_flags.append(stale)
            partial = partial or latest is None
        state = _state_badges(stale=(all(stale_flags) if stale_flags else True), partial=partial)
        rows.append(
            [
                f'<a href="/portal/products/{esc(product.id)}?project_id={esc(selected.id)}">{esc(product.name or product.id)}</a>',
                esc(product.brand),
                esc(product.sku),
                esc(len(direct_offers)),
                esc(len(active_matches)),
                state,
                esc(product.updated_at),
            ]
        )
    empty = (
        '<section class="notice warning" role="status"><strong>No products yet.</strong> Activate a monitor and run an extraction to populate comparisons.</section>'
        if not products
        else ""
    )
    content = f"""
    <div class="page-heading"><div><h1>Products</h1><p class="muted">Current monitored products and cross-store comparison coverage.</p></div></div>
    {_project_selector(projects, selected.id, "/portal/products")}
    {empty}
    <section class="panel">{table(["Product", "Brand", "SKU", "Offers", "Equivalent products", "State", "Updated"], rows)}</section>
    """
    return _page("Products", content, context)


@router.get("/portal/products/{product_id}", response_class=HTMLResponse)
def portal_product_comparison(
    product_id: str,
    request: Request,
    project_id: str | None = None,
    store: Any = Depends(get_job_store),
) -> HTMLResponse:
    context = require_portal_session(request, store)
    selected = _select_project(store, context, project_id)
    if not selected:
        raise HTTPException(status_code=404, detail="Project not found.")
    comparison = _comparison(
        store,
        account_id=context.key.account_id or "",
        project_id=selected.id,
        product_id=product_id,
    )
    all_offers = [(None, item) for item in comparison.offers]
    for equivalent in comparison.equivalent_products:
        all_offers.extend((equivalent, item) for item in equivalent.offers)
    offer_rows: list[list[object]] = []
    for equivalent, view in all_offers:
        observation = view.latest_observation
        match = equivalent.match if equivalent else None
        relation = "direct"
        if equivalent and match:
            relation = f"{esc(match.status.value)} match · {esc(match.confidence)}" + (
                f" · {esc(match.method)}" if match.method else ""
            )
        offer_rows.append(
            [
                esc(view.source.name if view.source else view.offer.source_id),
                _external_offer(view.offer.url),
                _price(
                    observation.amount if observation else view.offer.current_amount,
                    observation.currency if observation else view.offer.current_currency,
                ),
                esc(observation.availability if observation else view.offer.current_availability),
                esc(observation.captured_at if observation else view.offer.last_observed_at),
                esc(observation.confidence if observation else None),
                relation,
                _state_badges(stale=view.stale, partial=view.partial),
            ]
        )
    match_rows = [
        [
            esc(item.product.name or item.product.id),
            esc(item.match.status.value),
            esc(item.match.confidence),
            esc(item.match.method),
            esc(item.match.metadata),
        ]
        for item in comparison.equivalent_products
    ]
    history_rows = [
        [
            esc(point.captured_at),
            esc(point.source_id),
            _price(point.amount, point.currency),
            esc(point.availability),
            esc(point.confidence),
            f'<a href="/portal/observations/{esc(point.observation_id)}?project_id={esc(selected.id)}">Evidence</a>',
        ]
        for point in comparison.price_history[:100]
    ]
    notices = ""
    if comparison.stale:
        notices += '<section class="notice warning" role="status"><strong>Stale comparison.</strong> All available offers are past their expected observation window.</section>'
    if comparison.partial:
        notices += (
            '<section class="notice error" role="status"><strong>Partial data.</strong> '
            + " ".join(esc(item) for item in comparison.warnings)
            + "</section>"
        )
    if not all_offers:
        notices += '<section class="notice warning" role="status"><strong>No offers yet.</strong> This product exists but has no observed store offers.</section>'
    export_url = f"/portal/export/products/{esc(comparison.product.id)}/comparison?project_id={esc(selected.id)}"
    content = f"""
    <div class="page-heading">
      <div><h1>{esc(comparison.product.name or comparison.product.id)}</h1><p class="muted">{esc(comparison.product.brand)} · {esc(comparison.product.sku or "no SKU")}</p></div>
      <a class="button-link" href="{export_url}">Export comparison</a>
    </div>
    {notices}
    <section class="grid">
      <div class="metric">Direct offers<strong>{len(comparison.offers)}</strong></div>
      <div class="metric">Equivalent products<strong>{len(comparison.equivalent_products)}</strong></div>
      <div class="metric">History points<strong>{len(comparison.price_history)}</strong></div>
      <div class="metric">Recent changes<strong>{len(comparison.recent_changes)}</strong></div>
    </section>
    <h2>Cross-store offers</h2>
    <section class="panel">{table(["Source", "Offer", "Current price", "Availability", "Observed", "Extraction confidence", "Relationship", "State"], offer_rows)}</section>
    <h2>Price history</h2>
    <section class="panel">{_sparkline(comparison.price_history)}{table(["Observed", "Source", "Price", "Availability", "Confidence", "Evidence"], history_rows)}</section>
    <h2>Equivalent product evidence</h2>
    <section class="panel">{table(["Product", "Match status", "Match confidence", "Method", "Provenance"], match_rows)}</section>
    <h2>Recent changes</h2>
    <section class="panel">{table(["Changed", "What happened", "Source", "Type", "Severity", "Before", "Now", "Confidence", "State", "Evidence"], _change_rows(comparison.recent_changes))}</section>
    """
    return _page(comparison.product.name or "Product comparison", content, context)


@router.get("/portal/observations/{observation_id}", response_class=HTMLResponse)
def portal_observation(
    observation_id: str,
    request: Request,
    project_id: str | None = None,
    store: Any = Depends(get_job_store),
) -> HTMLResponse:
    context = require_portal_session(request, store)
    selected = _select_project(store, context, project_id)
    if not selected:
        raise HTTPException(status_code=404, detail="Project not found.")
    repo = domain_repository_for_store(store)
    observation = repo.get_observation(
        observation_id,
        account_id=context.key.account_id or "",
        project_id=selected.id,
    )
    if not observation:
        raise HTTPException(status_code=404, detail="Observation not found.")
    source = repo.get_source(
        observation.source_id,
        account_id=context.key.account_id or "",
        project_id=selected.id,
    )
    product = repo.get_product(
        observation.product_id,
        account_id=context.key.account_id or "",
        project_id=selected.id,
    )
    run_link = (
        f'<a href="/portal/runs/{esc(observation.run_id)}"><code>{esc(observation.run_id)}</code></a>'
        if observation.run_id
        else "—"
    )
    rows = [
        ["Captured", esc(observation.captured_at)],
        [
            "Product",
            f'<a href="/portal/products/{esc(observation.product_id)}?project_id={esc(selected.id)}">{esc(product.name if product else observation.product_id)}</a>',
        ],
        ["Source", esc(source.name if source else observation.source_id)],
        ["Offer", esc(observation.source_url or observation.offer_id)],
        ["Price", _price(observation.amount, observation.currency)],
        ["Availability", esc(observation.availability)],
        ["Extraction confidence", esc(observation.confidence)],
        ["Extraction", esc(observation.extraction_id)],
        ["Monitor run", run_link],
        [
            "Provenance",
            f"<pre>{esc(json.dumps(observation.provenance, indent=2, sort_keys=True))}</pre>",
        ],
    ]
    return _page(
        "Observation",
        f'<div class="page-heading"><div><h1>Observation evidence</h1><p class="muted"><code>{esc(observation.id)}</code></p></div></div><section class="panel">{table(["Field", "Value"], rows)}</section>',
        context,
    )


@router.get("/portal/export/changes")
def export_changes(
    request: Request,
    project_id: str | None = None,
    source_id: str | None = None,
    event_type: str | None = None,
    severity: str | None = None,
    since: str | None = None,
    until: str | None = None,
    change_id: list[str] = Query(default=[]),
    store: Any = Depends(get_job_store),
) -> Response:
    context = require_portal_session(request, store)
    selected = _select_project(store, context, project_id)
    if not selected:
        raise HTTPException(status_code=404, detail="Project not found.")
    filters = _filters(
        source_id=source_id,
        event_type=event_type,
        severity=severity,
        since=since,
        until=until,
        limit=1000,
    )
    entries = _feed(
        store,
        account_id=context.key.account_id or "",
        project_id=selected.id,
        filters=filters,
    )
    if change_id:
        selected_ids = set(change_id)
        entries = [entry for entry in entries if entry.event.id in selected_ids]
    payload = {
        "account_id": context.key.account_id,
        "project_id": selected.id,
        "filters": filters.model_dump(mode="json", exclude_none=True),
        "changes": [entry.model_dump(mode="json") for entry in entries],
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }
    return _download("commercelens-changes.json", payload)


@router.get("/portal/export/products/{product_id}/comparison")
def export_product_comparison(
    product_id: str,
    request: Request,
    project_id: str | None = None,
    store: Any = Depends(get_job_store),
) -> Response:
    context = require_portal_session(request, store)
    selected = _select_project(store, context, project_id)
    if not selected:
        raise HTTPException(status_code=404, detail="Project not found.")
    comparison = _comparison(
        store,
        account_id=context.key.account_id or "",
        project_id=selected.id,
        product_id=product_id,
    )
    return _download(
        f"commercelens-product-{product_id}-comparison.json",
        comparison.model_dump(mode="json"),
    )
