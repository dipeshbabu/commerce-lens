from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"Patch anchor not found in {path}: {old[:120]!r}")
    file.write_text(text.replace(old, new, 1))


# Resolve the forward reference used by ProductComparison after all insight models exist.
replace_once(
    "commercelens/domain/insights.py",
    """class ChangeFeedEntry(BaseModel):
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


def parse_datetime""",
    """class ChangeFeedEntry(BaseModel):
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


def parse_datetime""",
)

# Customer insight route safety, selected exports, and a lighter product-index query path.
path = Path("commercelens/api/customer_insights.py")
text = path.read_text()
text = text.replace(
    "from urllib.parse import urlencode\n", "from urllib.parse import urlencode, urlsplit\n"
)
text = text.replace(
    "from fastapi import APIRouter, Depends, HTTPException, Request\n",
    "from fastapi import APIRouter, Depends, HTTPException, Query, Request\n",
)
text = text.replace(
    "    build_product_comparison,\n    parse_datetime,\n)",
    "    build_product_comparison,\n    observation_is_stale,\n    parse_datetime,\n)",
)
text = text.replace(
    "account_id=context.key.account_id,\n",
    'account_id=context.key.account_id or "",\n',
)

price_anchor = """def _price(amount: float | None, currency: str | None) -> str:
    if amount is None:
        return "—"
    suffix = f" {esc(currency)}" if currency else ""
    return f"{esc(f'{amount:g}')}{suffix}"


def _sparkline"""
price_replacement = """def _price(amount: float | None, currency: str | None) -> str:
    if amount is None:
        return "—"
    suffix = f" {esc(currency)}" if currency else ""
    return f"{esc(f'{amount:g}')}{suffix}"


def _external_offer(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return f"<code>{esc(url)}</code>"
    return f'<a href="{esc(url)}" rel="noreferrer">{esc(url)}</a>'


def _sparkline"""
if price_replacement not in text:
    if price_anchor not in text:
        raise RuntimeError("External offer helper anchor not found")
    text = text.replace(price_anchor, price_replacement, 1)

text = text.replace(
    'f\'<a href="{esc(view.offer.url)}" rel="noreferrer">{esc(view.offer.url)}</a>\'',
    "_external_offer(view.offer.url)",
)

old_products = """    rows: list[list[object]] = []
    for product in products:
        comparison = build_product_comparison(
            repo,
            account_id=context.key.account_id or "",
            project_id=selected.id,
            product_id=product.id,
            job_store=store,
            history_limit=1,
            change_limit=1,
        )
        offer_count = 0
        equivalent_count = 0
        state = ""
        if comparison:
            offer_count = len(comparison.offers) + sum(
                len(item.offers) for item in comparison.equivalent_products
            )
            equivalent_count = len(comparison.equivalent_products)
            state = _state_badges(stale=comparison.stale, partial=comparison.partial)
        rows.append(
            [
                f'<a href="/portal/products/{esc(product.id)}?project_id={esc(selected.id)}">{esc(product.name or product.id)}</a>',
                esc(product.brand),
                esc(product.sku),
                esc(offer_count),
                esc(equivalent_count),
                state,
                esc(product.updated_at),
            ]
        )
"""
new_products = """    matches = repo.list_product_matches(
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
        state = _state_badges(
            stale=(all(stale_flags) if stale_flags else True), partial=partial
        )
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
"""
if new_products not in text:
    if old_products not in text:
        raise RuntimeError("Product index optimization anchor not found")
    text = text.replace(old_products, new_products, 1)

old_feed_table = """    <section class="panel">
      {table(["Changed", "What happened", "Source", "Type", "Severity", "Before", "Now", "Confidence", "State", "Evidence"], _change_rows(entries))}
    </section>
"""
new_feed_table = """    <form id="change-export-form" class="action-row" method="get" action="/portal/export/changes">
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
if new_feed_table not in text:
    if old_feed_table not in text:
        raise RuntimeError("Selected change export table anchor not found")
    text = text.replace(old_feed_table, new_feed_table, 1)

old_export_signature = """def export_changes(
    request: Request,
    project_id: str | None = None,
    source_id: str | None = None,
    event_type: str | None = None,
    severity: str | None = None,
    since: str | None = None,
    until: str | None = None,
    store: Any = Depends(get_job_store),
) -> Response:
"""
new_export_signature = """def export_changes(
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
"""
if new_export_signature not in text:
    if old_export_signature not in text:
        raise RuntimeError("Change export signature anchor not found")
    text = text.replace(old_export_signature, new_export_signature, 1)

old_entries = """    entries = _feed(
        store,
        account_id=context.key.account_id or "",
        project_id=selected.id,
        filters=filters,
    )
    payload = {
"""
new_entries = """    entries = _feed(
        store,
        account_id=context.key.account_id or "",
        project_id=selected.id,
        filters=filters,
    )
    if change_id:
        selected_ids = set(change_id)
        entries = [entry for entry in entries if entry.event.id in selected_ids]
    payload = {
"""
# Only replace the export occurrence by targeting the last occurrence before payload.
export_pos = text.find("def export_changes(")
if export_pos < 0:
    raise RuntimeError("Change export function not found")
prefix, suffix = text[:export_pos], text[export_pos:]
if new_entries not in suffix:
    if old_entries not in suffix:
        raise RuntimeError("Change export filtering anchor not found")
    suffix = suffix.replace(old_entries, new_entries, 1)
text = prefix + suffix
path.write_text(text)

# Add customer insight navigation and compact state/chart styling to the existing portal shell.
presentation = Path("commercelens/api/presentation.py")
text = presentation.read_text()
old_nav = '<nav><a href="/portal">Overview</a><a href="/portal/manage">Manage monitors</a><a href="/docs">API Docs</a>{session_actions}</nav>'
new_nav = '<nav><a href="/portal">Overview</a><a href="/portal/changes">Changes</a><a href="/portal/products">Products</a><a href="/portal/manage">Manage monitors</a><a href="/docs">API Docs</a>{session_actions}</nav>'
if new_nav not in text:
    if old_nav not in text:
        raise RuntimeError("Portal navigation anchor not found")
    text = text.replace(old_nav, new_nav, 1)
style_anchor = (
    "    .notice.warning {{ color: #854d0e; border-color: #fde68a; background: #fffbeb; }}\n"
)
style_new = (
    style_anchor
    + """    .badge {{ display: inline-block; border: 1px solid #cbd5e1; border-radius: 999px; padding: 2px 7px; font-size: 12px; font-weight: 600; }}
    .badge.current {{ color: #166534; background: #f0fdf4; border-color: #bbf7d0; }}
    .badge.stale {{ color: #854d0e; background: #fffbeb; border-color: #fde68a; }}
    .badge.partial {{ color: #991b1b; background: #fef2f2; border-color: #fecaca; }}
    .history-chart {{ margin: 0 0 16px; color: #334155; }}
    .history-chart svg {{ width: 100%; height: 160px; border: 1px solid #e2e8f0; border-radius: 8px; background: #f8fafc; }}
    .insight-filter {{ margin-bottom: 14px; }}
"""
)
if style_new not in text:
    if style_anchor not in text:
        raise RuntimeError("Portal style anchor not found")
    text = text.replace(style_anchor, style_new, 1)
presentation.write_text(text)

# Document the new customer value views and exports.
docs = Path("docs/customer_portal.md")
text = docs.read_text()
section = """

## Change Feed and Product Comparisons

The signed in portal exposes business changes directly instead of requiring customers to inspect raw run payloads.

Use `/portal/changes` for a chronological feed with project, source, event type, severity, and time filters. Each row summarizes the change and links to the responsible observation and monitor run when available. Stale and partial evidence is surfaced explicitly rather than silently hidden.

Use `/portal/products` to browse monitored product identities and `/portal/products/{product_id}` to compare current offers across stores. The comparison includes current price, availability, latest observation, extraction confidence, explicit product-match confidence and provenance, recent changes, and price history data. Confirmed and proposed matches are shown separately from the direct offers owned by the product; rejected matches are excluded.

Machine readable insight endpoints are available at:

```text
/v1/change-feed
/v1/products/{product_id}/comparison
/v1/products/{product_id}/history
```

Portal JSON exports use the same aggregation and tenant filters as the visible pages:

```text
/portal/export/changes
/portal/export/products/{product_id}/comparison
```

The change export accepts the visible filters and optional repeated `change_id` parameters for selected rows. Export responses remain `no-store` and use the browser session rather than putting API keys in URLs.

Staleness defaults to 24 hours for manual or unbound observations. Interval monitors use twice their configured interval with a one-hour minimum. Set `COMMERCELENS_STALE_AFTER_MINUTES` to change the fallback threshold.
"""
if "## Change Feed and Product Comparisons" not in text:
    docs.write_text(text.rstrip() + section + "\n")

print("Issue 22 integration patches applied")
