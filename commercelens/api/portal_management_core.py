from __future__ import annotations

import csv
import io
from email.parser import BytesParser
from email.policy import default as email_policy
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse

from commercelens.alerts.rules import AlertCondition, AlertDestination, AlertDestinationType, AlertRule
from commercelens.api.domain_limits import require_domain_quota, url_domain
from commercelens.api.portal_auth import PortalSessionContext
from commercelens.api.presentation import escape_html as esc, portal_shell
from commercelens.api.quota import require_quota
from commercelens.core.fetcher import fetch_html
from commercelens.extractors.listing import extract_listing, extract_listing_from_html
from commercelens.extractors.product import extract_product, extract_product_from_html
from commercelens.jobs.models import (
    ExtractionCreate,
    ExtractionKind,
    ExtractionStatus,
    JobStatus,
    MonitoringJob,
    ProjectRecord,
    UsageEvent,
    UsageMetric,
    utc_now_iso,
)

_MAX_FORM_BYTES = 2 * 1024 * 1024
_MAX_CATEGORY_URLS = 10
_MAX_TARGETS = 500


def _page(title: str, content: str, context: PortalSessionContext, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(
        portal_shell(title, content, csrf_token=context.csrf_token),
        status_code=status_code,
        headers={
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "Referrer-Policy": "no-referrer",
            "X-Frame-Options": "DENY",
            "X-Content-Type-Options": "nosniff",
            "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
                "base-uri 'none'; frame-ancestors 'none'"
            ),
        },
    )


async def _form(request: Request) -> dict[str, str]:
    body = await request.body()
    if len(body) > _MAX_FORM_BYTES:
        raise HTTPException(status_code=413, detail="Portal form is too large.")
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("application/x-www-form-urlencoded"):
        parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True)
        return {key: values[-1] for key, values in parsed.items() if values}
    if content_type.startswith("multipart/form-data"):
        envelope = (
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + body
        )
        message = BytesParser(policy=email_policy).parsebytes(envelope)
        result: dict[str, str] = {}
        if not message.is_multipart():
            return result
        for part in message.iter_parts():
            disposition = part.get_content_disposition()
            if disposition != "form-data":
                continue
            name = part.get_param("name", header="content-disposition")
            if not name:
                continue
            payload = part.get_payload(decode=True) or b""
            charset = part.get_content_charset() or "utf-8"
            result[name] = payload.decode(charset, errors="replace")
        return result
    raise HTTPException(status_code=415, detail="Unsupported portal form encoding.")


def _write_allowed(context: PortalSessionContext) -> bool:
    scopes = set(context.key.scopes)
    return "*" in scopes or "jobs:write" in scopes


def _preview_allowed(context: PortalSessionContext) -> bool:
    scopes = set(context.key.scopes)
    return "*" in scopes or "extract:write" in scopes


def _require_account(context: PortalSessionContext) -> str:
    if not context.key.account_id:
        raise HTTPException(status_code=403, detail="Portal management requires an account-scoped key.")
    return context.key.account_id


def _available_projects(store: Any, context: PortalSessionContext) -> list[ProjectRecord]:
    account_id = _require_account(context)
    if context.key.project_id:
        project = store.get_project(context.key.project_id, account_id=account_id)
        return [project] if project else []
    return store.list_projects(account_id=account_id, limit=100)


def _select_project(
    store: Any,
    context: PortalSessionContext,
    requested_project_id: str | None,
) -> ProjectRecord | None:
    projects = _available_projects(store, context)
    if context.key.project_id:
        if requested_project_id and requested_project_id != context.key.project_id:
            raise HTTPException(status_code=404, detail="Project not found.")
        return projects[0] if projects else None
    if requested_project_id:
        project = store.get_project(requested_project_id, account_id=context.key.account_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found.")
        return project
    return projects[0] if projects else None


def _project_query(project_id: str | None) -> str:
    return "?" + urlencode({"project_id": project_id}) if project_id else ""


def _normal_url(url: str) -> str:
    value = url.strip()
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Use a complete http:// or https:// URL.")
    if parsed.username or parsed.password:
        raise ValueError("URLs containing credentials are not allowed.")
    return value


def _urls_from_text(raw: str) -> list[str]:
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _urls_from_csv(raw: str) -> tuple[list[str], list[str]]:
    if not raw.strip():
        return [], []
    rows = list(csv.reader(io.StringIO(raw)))
    if not rows:
        return [], []
    warnings: list[str] = []
    header = [cell.strip().lower() for cell in rows[0]]
    url_index = next(
        (index for index, name in enumerate(header) if name in {"url", "product_url", "product url"}),
        None,
    )
    start = 1 if url_index is not None else 0
    if url_index is None:
        url_index = 0
        warnings.append("No URL column header was found, so CommerceLens used the first CSV column.")
    urls: list[str] = []
    for row_number, row in enumerate(rows[start:], start=start + 1):
        if url_index >= len(row):
            warnings.append(f"CSV row {row_number} does not contain a URL column.")
            continue
        value = row[url_index].strip()
        if value:
            urls.append(value)
    return urls, warnings


def _validate_targets(
    direct_urls: list[str],
    existing_urls: set[str],
    *,
    allow_existing: set[str] | None = None,
) -> tuple[list[str], list[str], list[str]]:
    allowed = {url.casefold() for url in (allow_existing or set())}
    existing = {url.casefold() for url in existing_urls}
    valid: list[str] = []
    errors: list[str] = []
    duplicates: list[str] = []
    seen: set[str] = set()
    for raw in direct_urls:
        try:
            url = _normal_url(raw)
        except ValueError as exc:
            errors.append(f"{raw or '(blank)'}: {exc}")
            continue
        lowered = url.casefold()
        if lowered in seen:
            duplicates.append(f"{url}: duplicated in this import.")
            continue
        seen.add(lowered)
        if lowered in existing and lowered not in allowed:
            duplicates.append(f"{url}: already monitored in this project.")
            continue
        valid.append(url)
    return valid, errors, duplicates


def _existing_target_urls(
    store: Any,
    account_id: str | None,
    project_id: str | None,
    *,
    exclude_job_id: str | None = None,
) -> set[str]:
    urls: set[str] = set()
    for job in store.list_jobs(limit=1000, account_id=account_id, project_id=project_id):
        if exclude_job_id and job.id == exclude_job_id:
            continue
        urls.update(str(target.url) for target in job.config.targets)
    return urls


def _destination(form: dict[str, str]) -> AlertDestination | None:
    kind = form.get("destination_type", "").strip()
    value = form.get("destination_value", "").strip()
    if not kind:
        return None
    destination_type = AlertDestinationType(kind)
    if destination_type in {AlertDestinationType.WEBHOOK, AlertDestinationType.SLACK}:
        if not value:
            raise ValueError("Enter the destination URL.")
        return AlertDestination(type=destination_type, url=value)
    if destination_type == AlertDestinationType.EMAIL:
        if not value:
            raise ValueError("Enter the alert email address.")
        return AlertDestination(type=destination_type, email_to=value)
    if destination_type == AlertDestinationType.FILE:
        raise ValueError("File destinations are not available from the hosted customer portal.")
    return AlertDestination(type=destination_type)


def _rules_from_form(form: dict[str, str]) -> list[AlertRule]:
    condition_raw = form.get("alert_condition", "").strip()
    if not condition_raw:
        return []
    condition = AlertCondition(condition_raw)
    threshold_raw = form.get("alert_threshold", "").strip()
    threshold = float(threshold_raw) if threshold_raw else None
    needs_threshold = condition in {
        AlertCondition.PRICE_BELOW,
        AlertCondition.PRICE_ABOVE,
        AlertCondition.PERCENT_DROP_AT_LEAST,
        AlertCondition.PERCENT_INCREASE_AT_LEAST,
    }
    if needs_threshold and threshold is None:
        raise ValueError("This alert condition requires a threshold.")
    destination = _destination(form)
    destinations = [destination] if destination else [AlertDestination(type=AlertDestinationType.STDOUT)]
    return [
        AlertRule(
            name=form.get("alert_name", "").strip() or "Portal alert",
            condition=condition,
            threshold=threshold,
            destinations=destinations,
        )
    ]


def _audit(
    store: Any,
    context: PortalSessionContext,
    operation: str,
    *,
    project_id: str | None = None,
    job_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    target_project_id = project_id or context.key.project_id
    if not target_project_id or not context.key.account_id:
        return
    project = store.get_project(target_project_id, account_id=context.key.account_id)
    if not project:
        return
    events = list(project.metadata.get("portal_audit_events") or [])
    events.append(
        {
            "operation": operation,
            "job_id": job_id,
            "api_key_id": context.key.id,
            "owner": context.key.owner,
            "created_at": utc_now_iso(),
            "metadata": metadata or {},
        }
    )
    project.metadata["portal_audit_events"] = events[-500:]
    store.save_project(project)


def _record_preview(
    store: Any,
    context: PortalSessionContext,
    *,
    kind: ExtractionKind,
    url: str,
    payload: dict[str, Any],
    confidence: float | None,
    product_count: int | None = None,
    render: bool,
    project_id: str,
) -> None:
    store.record_extraction(
        ExtractionCreate(
            kind=kind,
            status=ExtractionStatus.succeeded,
            url=url,
            account_id=context.key.account_id,
            project_id=project_id,
            owner=context.key.owner,
            api_key_id=context.key.id,
            confidence=confidence,
            product_count=product_count,
            payload=payload,
            metadata={"render": render, "portal_preview": True},
        )
    )
    metric = UsageMetric.product_extract if kind == ExtractionKind.product else UsageMetric.listing_extract
    store.record_usage(
        UsageEvent(
            metric=metric,
            account_id=context.key.account_id,
            project_id=project_id,
            owner=context.key.owner,
            api_key_id=context.key.id,
            route="/portal/manage/preview",
            metadata={
                "render": render,
                "portal_preview": True,
                "domain": url_domain(url),
            },
        )
    )


def _record_preview_failure(
    store: Any,
    context: PortalSessionContext,
    *,
    kind: ExtractionKind,
    url: str,
    error: str,
    render: bool,
    project_id: str,
) -> None:
    store.record_extraction(
        ExtractionCreate(
            kind=kind,
            status=ExtractionStatus.failed,
            url=url,
            account_id=context.key.account_id,
            project_id=project_id,
            owner=context.key.owner,
            api_key_id=context.key.id,
            error=error,
            metadata={"render": render, "portal_preview": True},
        )
    )


def _extract_product_preview(url: str, render: bool) -> Any:
    if render:
        return extract_product(url, render=True)
    html = fetch_html(url)
    return extract_product_from_html(html, url=url)


def _extract_listing_preview(url: str, render: bool) -> Any:
    if render:
        return extract_listing(url, render=True)
    html = fetch_html(url)
    return extract_listing_from_html(html, url=url)


def _hidden(name: str, value: object) -> str:
    return f'<input type="hidden" name="{esc(name)}" value="{esc(value)}">'


def _monitor_form(
    context: PortalSessionContext,
    project: ProjectRecord,
    *,
    message: str = "",
) -> str:
    csrf = esc(context.csrf_token)
    notice = f'<p class="danger" role="alert">{esc(message)}</p>' if message else ""
    return f"""
    <section class="panel">
      <h2>Create a monitor</h2>
      <p class="muted">Add product URLs directly, paste a CSV, or add category pages and preview the extraction before activation.</p>
      {notice}
      <form class="form-grid" method="post" action="/portal/manage/preview" enctype="multipart/form-data">
        <input type="hidden" name="csrf_token" value="{csrf}">
        <input type="hidden" name="project_id" value="{esc(project.id)}">
        <label class="span-2">Monitor name
          <input name="name" required maxlength="120" placeholder="Key competitors">
        </label>
        <label>Schedule
          <select name="schedule_kind">
            <option value="interval">Recurring interval</option>
            <option value="manual">Manual only</option>
          </select>
        </label>
        <label>Interval minutes
          <input name="interval_minutes" type="number" min="1" value="360">
        </label>
        <label>Extraction mode
          <select name="render">
            <option value="false">Standard HTML</option>
            <option value="true">Browser rendered</option>
          </select>
        </label>
        <label class="span-2">Product URLs, one per line
          <textarea name="urls" rows="7" placeholder="https://store.example/product-a&#10;https://store.example/product-b"></textarea>
        </label>
        <label class="span-2">Category URLs, one per line
          <textarea name="category_urls" rows="4" placeholder="https://store.example/category/shoes"></textarea>
        </label>
        <label class="span-2">CSV URL import
          <input name="csv_file" type="file" accept=".csv,text/csv">
          <span class="help">Use a column named url or product_url. Files are capped at 2 MB.</span>
        </label>
        <fieldset class="span-2">
          <legend>Alert rule</legend>
          <label>Rule name<input name="alert_name" value="Price change"></label>
          <label>Condition
            <select name="alert_condition">
              <option value="">No alert</option>
              <option value="any_change" selected>Any change</option>
              <option value="price_drop">Price drop</option>
              <option value="price_increase">Price increase</option>
              <option value="back_in_stock">Back in stock</option>
              <option value="availability_change">Availability change</option>
              <option value="price_below">Price below</option>
              <option value="price_above">Price above</option>
              <option value="percent_drop_at_least">Percent drop at least</option>
              <option value="percent_increase_at_least">Percent increase at least</option>
            </select>
          </label>
          <label>Threshold<input name="alert_threshold" type="number" step="any" placeholder="10"></label>
          <label>Destination
            <select name="destination_type">
              <option value="stdout">Portal / stdout</option>
              <option value="slack">Slack webhook</option>
              <option value="webhook">Webhook</option>
              <option value="email">Email</option>
            </select>
          </label>
          <label class="span-2">Destination value
            <input name="destination_value" placeholder="Webhook URL or email address">
          </label>
        </fieldset>
        <button class="primary" type="submit">Validate and preview</button>
      </form>
    </section>
    """


def _job_rows(
    jobs: list[MonitoringJob],
    project_id: str,
    context: PortalSessionContext,
) -> list[list[object]]:
    rows: list[list[object]] = []
    for job in jobs:
        hidden = _hidden("csrf_token", context.csrf_token) + _hidden("project_id", project_id)
        status_action = "resume" if job.status == JobStatus.paused else "pause"
        status_label = "Resume" if status_action == "resume" else "Pause"
        actions = (
            f'<div class="table-actions">'
            f'<a href="/portal/manage/jobs/{esc(job.id)}/edit?project_id={esc(project_id)}">Edit</a>'
            f'<form class="action-form" method="post" action="/portal/manage/jobs/{esc(job.id)}/run">{hidden}<button type="submit">Run</button></form>'
            f'<form class="action-form" method="post" action="/portal/manage/jobs/{esc(job.id)}/{status_action}">{hidden}<button type="submit">{status_label}</button></form>'
            f'<form class="action-form" method="post" action="/portal/manage/jobs/{esc(job.id)}/delete">{hidden}<button class="danger-button" type="submit">Delete</button></form>'
            f'</div>'
        )
        rows.append(
            [
                f'<a href="/portal/jobs/{esc(job.id)}"><code>{esc(job.id)}</code></a>',
                esc(job.name),
                esc(job.status.value),
                esc(job.schedule_kind.value),
                esc(job.interval_minutes),
                esc(len(job.config.targets)),
                actions,
            ]
        )
    return rows


def _resolve_category_urls(
    store: Any,
    context: PortalSessionContext,
    category_urls: list[str],
    *,
    render: bool,
    project_id: str,
) -> tuple[list[str], list[dict[str, Any]], list[str]]:
    discovered: list[str] = []
    previews: list[dict[str, Any]] = []
    warnings: list[str] = []
    if len(category_urls) > _MAX_CATEGORY_URLS:
        raise ValueError(f"Use at most {_MAX_CATEGORY_URLS} category URLs per onboarding.")
    for category_url in category_urls:
        require_quota(context.key, UsageMetric.listing_extract, 1)
        require_domain_quota(store, context.key, category_url)
        try:
            result = _extract_listing_preview(category_url, render)
        except Exception as exc:
            _record_preview_failure(
                store,
                context,
                kind=ExtractionKind.listing,
                url=category_url,
                error=str(exc),
                render=render,
                project_id=project_id,
            )
            warnings.append(f"{category_url}: category preview failed: {exc}")
            continue
        payload = result.model_dump(mode="json", exclude_none=True)
        _record_preview(
            store,
            context,
            kind=ExtractionKind.listing,
            url=category_url,
            payload=payload,
            confidence=result.confidence,
            product_count=result.product_count,
            render=render,
            project_id=project_id,
        )
        previews.append(payload)
        for product in result.products:
            if product.url:
                discovered.append(str(product.url))
        warnings.extend(result.warnings)
    return discovered, previews, warnings


def _preview_product(
    store: Any,
    context: PortalSessionContext,
    url: str,
    *,
    render: bool,
    project_id: str,
) -> tuple[dict[str, Any] | None, str | None]:
    require_quota(context.key, UsageMetric.product_extract, 1)
    require_domain_quota(store, context.key, url)
    try:
        result = _extract_product_preview(url, render)
    except Exception as exc:
        _record_preview_failure(
            store,
            context,
            kind=ExtractionKind.product,
            url=url,
            error=str(exc),
            render=render,
            project_id=project_id,
        )
        return None, str(exc)
    payload = result.model_dump(mode="json", exclude_none=True)
    _record_preview(
        store,
        context,
        kind=ExtractionKind.product,
        url=url,
        payload=payload,
        confidence=result.confidence,
        render=render,
        project_id=project_id,
    )
    return payload, None


def _tenant_job(
    store: Any,
    context: PortalSessionContext,
    job_id: str,
    project_id: str | None,
) -> MonitoringJob:
    selected = _select_project(store, context, project_id)
    if not selected:
        raise HTTPException(status_code=404, detail="Project not found.")
    job = store.get_job(job_id, account_id=context.key.account_id, project_id=selected.id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job
