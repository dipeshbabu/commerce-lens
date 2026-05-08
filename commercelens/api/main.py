from __future__ import annotations

import os
from collections import Counter
from html import escape
from typing import Sequence
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

from commercelens.alerts.runner import MonitorRunResult, run_monitor_config, run_monitor_config_file
from commercelens.api.auth import get_job_store, require_admin_access, require_admin_token, require_api_key
from commercelens.api.domain_limits import require_domain_quota, url_domain
from commercelens.api.quota import quota_decision, require_quota, require_scope
from commercelens.connectors.datasets import DatasetLoadResult
from commercelens.core.crawler import CatalogCrawlResult, crawl_catalog
from commercelens.core.fetcher import FetchError, fetch_html
from commercelens.core.monitor import BatchMonitorResult, MonitorResult, monitor_product, monitor_products
from commercelens.core.renderer import RenderError
from commercelens.extractors.listing import extract_listing, extract_listing_from_html
from commercelens.extractors.product import extract_product, extract_product_from_html
from commercelens.jobs.models import AccountCreate, AccountRecord, ApiKeyCreate, ApiKeyCreateResult, ApiKeyRecord, BillingUsageItem, BillingUsageSnapshot, ExtractionCreate, ExtractionKind, ExtractionRecord, ExtractionStatus, JobRun, JobStatus, MemberCreate, MemberRecord, MonitoringJob, MonitoringJobCreate, MonitoringJobUpdate, ProjectCreate, ProjectRecord, UsageEvent, UsageMetric, UsageSummary, WorkerTickResult
from commercelens.jobs.store import JobStore
from commercelens.jobs.worker import MonitoringWorker, run_job_now
from commercelens.matching.products import ProductMatchResult, match_products
from commercelens.schemas.alerts import RunMonitorConfigFileRequest, RunMonitorConfigRequest
from commercelens.schemas.connectors import MatchProductsRequest, NormalizeRecordsRequest
from commercelens.schemas.listing import CatalogCrawlRequest, ListingExtractionRequest, ListingExtractionResult
from commercelens.schemas.monitor import MonitorBatchRequest, MonitorProductRequest, PriceHistoryRequest
from commercelens.schemas.product import ProductExtractionRequest, ProductExtractionResult
from commercelens.storage.price_store import PriceSnapshotStore, ProductSnapshot
from commercelens.version import __version__

API_VERSION = __version__

app = FastAPI(title="CommerceLens API", description="Commercial product, catalog, monitoring, alerting, matching, and price intelligence extraction for developers.", version=API_VERSION)


def _usage_context(key: ApiKeyRecord | None) -> dict[str, str | None]:
    if not key:
        return {"account_id": None, "project_id": None, "owner": None, "api_key_id": None}
    return {"account_id": key.account_id, "project_id": key.project_id, "owner": key.owner, "api_key_id": key.id}


def _record_usage(store: JobStore, key: ApiKeyRecord | None, metric: UsageMetric, quantity: int = 1, route: str | None = None, status_code: int | None = None, metadata: dict | None = None) -> None:
    context = _usage_context(key)
    store.record_usage(UsageEvent(metric=metric, quantity=quantity, account_id=context["account_id"], project_id=context["project_id"], owner=context["owner"], api_key_id=context["api_key_id"], route=route, status_code=status_code, metadata=metadata or {}))


def _record_extraction(
    store: JobStore,
    key: ApiKeyRecord | None,
    kind: ExtractionKind,
    status: ExtractionStatus,
    url: str | None = None,
    confidence: float | None = None,
    product_count: int | None = None,
    payload: dict | None = None,
    error: str | None = None,
    metadata: dict | None = None,
) -> ExtractionRecord:
    context = _usage_context(key)
    return store.record_extraction(
        ExtractionCreate(
            kind=kind,
            status=status,
            url=url,
            account_id=context["account_id"],
            project_id=context["project_id"],
            owner=context["owner"],
            api_key_id=context["api_key_id"],
            confidence=confidence,
            product_count=product_count,
            payload=payload,
            error=error,
            metadata=metadata or {},
        )
    )


def _meter(key: ApiKeyRecord | None, metric: UsageMetric, quantity: int = 1, scope: str | None = None) -> None:
    if scope:
        require_scope(key, scope)
    require_quota(key, metric, quantity)


def _esc(value: object) -> str:
    return escape("" if value is None else str(value))


def _dashboard_token_query(request: Request) -> str:
    token = request.query_params.get("admin_token")
    return "?" + urlencode({"admin_token": token}) if token else ""


def _dashboard_shell(title: str, content: str, token_query: str = "") -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_esc(title)} - CommerceLens</title>
  <style>
    body {{ margin: 0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif; color: #17202a; background: #f6f8fb; }}
    header {{ background: #111827; color: white; padding: 18px 28px; display: flex; justify-content: space-between; align-items: center; }}
    header a {{ color: #dbeafe; text-decoration: none; margin-left: 18px; }}
    main {{ padding: 28px; max-width: 1280px; margin: 0 auto; }}
    h1 {{ font-size: 28px; margin: 0 0 20px; }}
    h2 {{ font-size: 18px; margin: 26px 0 10px; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; }}
    .metric {{ background: white; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; }}
    .metric strong {{ display: block; font-size: 26px; margin-top: 8px; }}
    table {{ width: 100%; border-collapse: collapse; background: white; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid #e5e7eb; text-align: left; vertical-align: top; font-size: 14px; }}
    th {{ background: #f9fafb; color: #4b5563; font-weight: 600; }}
    tr:last-child td {{ border-bottom: 0; }}
    code {{ background: #eef2ff; padding: 2px 5px; border-radius: 4px; }}
    .muted {{ color: #6b7280; }}
    .danger {{ color: #b91c1c; }}
    @media (max-width: 900px) {{ .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} main {{ padding: 18px; }} }}
  </style>
</head>
<body>
  <header>
    <div><strong>CommerceLens</strong> <span class="muted">operator dashboard</span></div>
    <nav><a href="/dashboard{token_query}">Dashboard</a><a href="/docs">API Docs</a></nav>
  </header>
  <main>{content}</main>
</body>
</html>"""


def _table(headers: list[str], rows: Sequence[Sequence[object]]) -> str:
    head = "".join(f"<th>{_esc(header)}</th>" for header in headers)
    if not rows:
        return f"<table><thead><tr>{head}</tr></thead><tbody><tr><td colspan='{len(headers)}' class='muted'>No records</td></tr></tbody></table>"
    body = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "commercelens", "version": API_VERSION}


@app.get("/ready")
def readiness(store: JobStore = Depends(get_job_store)) -> dict[str, str | bool]:
    store.usage_summary()
    return {
        "status": "ready",
        "service": "commercelens",
        "version": API_VERSION,
        "store_backend": os.getenv("COMMERCELENS_STORE_BACKEND", "sqlite").lower(),
        "api_key_required": os.getenv("COMMERCELENS_REQUIRE_API_KEY", "false").lower()
        in {"1", "true", "yes"},
        "admin_token_configured": bool(os.getenv("COMMERCELENS_ADMIN_TOKEN")),
    }


@app.post("/v1/accounts", response_model=AccountRecord, dependencies=[Depends(require_admin_access)])
def create_account_endpoint(request: AccountCreate, store: JobStore = Depends(get_job_store)) -> AccountRecord:
    return store.create_account(request)


@app.get("/v1/accounts", response_model=list[AccountRecord], dependencies=[Depends(require_admin_access)])
def list_accounts_endpoint(limit: int = 100, store: JobStore = Depends(get_job_store)) -> list[AccountRecord]:
    return store.list_accounts(limit=limit)


@app.get("/v1/accounts/{account_id}", response_model=AccountRecord, dependencies=[Depends(require_admin_access)])
def get_account_endpoint(account_id: str, store: JobStore = Depends(get_job_store)) -> AccountRecord:
    account = store.get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")
    return account


@app.post("/v1/accounts/{account_id}/projects", response_model=ProjectRecord, dependencies=[Depends(require_admin_access)])
def create_project_endpoint(account_id: str, request: ProjectCreate, store: JobStore = Depends(get_job_store)) -> ProjectRecord:
    try:
        return store.create_project(account_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/v1/accounts/{account_id}/projects", response_model=list[ProjectRecord], dependencies=[Depends(require_admin_access)])
def list_projects_endpoint(account_id: str, limit: int = 100, store: JobStore = Depends(get_job_store)) -> list[ProjectRecord]:
    if not store.get_account(account_id):
        raise HTTPException(status_code=404, detail="Account not found.")
    return store.list_projects(account_id=account_id, limit=limit)


@app.post("/v1/accounts/{account_id}/members", response_model=MemberRecord, dependencies=[Depends(require_admin_access)])
def create_member_endpoint(account_id: str, request: MemberCreate, store: JobStore = Depends(get_job_store)) -> MemberRecord:
    try:
        return store.create_member(account_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/v1/accounts/{account_id}/members", response_model=list[MemberRecord], dependencies=[Depends(require_admin_access)])
def list_members_endpoint(account_id: str, limit: int = 100, store: JobStore = Depends(get_job_store)) -> list[MemberRecord]:
    if not store.get_account(account_id):
        raise HTTPException(status_code=404, detail="Account not found.")
    return store.list_members(account_id=account_id, limit=limit)


@app.get("/dashboard", response_class=HTMLResponse, dependencies=[Depends(require_admin_access)])
def dashboard(request: Request, store: JobStore = Depends(get_job_store)) -> HTMLResponse:
    accounts = store.list_accounts(limit=50)
    jobs = store.list_jobs(limit=50)
    runs = store.list_runs(limit=50)
    api_keys = store.list_api_keys(limit=50)
    extractions = store.list_extractions(limit=50)
    usage = store.usage_summary()
    active_jobs = sum(1 for job in jobs if job.status == JobStatus.active)
    failed_runs = sum(1 for run in runs if str(run.status) == "RunStatus.failed" or run.status.value == "failed")
    failed_extractions = sum(1 for record in extractions if record.status == ExtractionStatus.failed)

    token_query = _dashboard_token_query(request)
    account_rows = [
        [
            f"<a href='/dashboard/accounts/{_esc(account.id)}{token_query}'><code>{_esc(account.id)}</code></a>",
            _esc(account.name),
            _esc(account.owner),
            _esc(account.billing_plan.value),
            _esc(account.status.value),
            _esc(account.updated_at),
        ]
        for account in accounts
    ]
    job_rows = [
        [
            f"<code>{_esc(job.id)}</code>",
            _esc(job.name),
            _esc(job.account_id),
            _esc(job.project_id),
            _esc(job.status.value),
            _esc(job.next_run_at),
        ]
        for job in jobs[:12]
    ]
    run_rows = [
        [
            f"<code>{_esc(run.id)}</code>",
            f"<code>{_esc(run.job_id)}</code>",
            _esc(run.account_id),
            _esc(run.status.value),
            _esc(run.duration_ms),
            _esc(run.created_at),
        ]
        for run in runs[:12]
    ]
    key_rows = [
        [
            f"<code>{_esc(key.id)}</code>",
            _esc(key.name),
            _esc(key.account_id),
            _esc(key.project_id),
            _esc(key.billing_plan.value),
            _esc("disabled" if key.disabled else "active"),
        ]
        for key in api_keys[:12]
    ]
    usage_rows = [[_esc(item.metric.value), _esc(item.quantity)] for item in usage.items]
    extraction_rows = [
        [
            f"<a href='/dashboard/extractions/{_esc(record.id)}{token_query}'><code>{_esc(record.id)}</code></a>",
            _esc(record.kind.value),
            _esc(record.status.value),
            _esc(record.account_id),
            _esc(record.project_id),
            _esc(record.url),
            _esc(record.confidence),
            _esc(record.created_at),
        ]
        for record in extractions[:12]
    ]

    content = f"""
    <h1>Dashboard</h1>
    <section class="grid">
      <div class="metric">Accounts<strong>{len(accounts)}</strong></div>
      <div class="metric">API keys<strong>{len(api_keys)}</strong></div>
      <div class="metric">Active jobs<strong>{active_jobs}</strong></div>
      <div class="metric">Failed runs<strong>{failed_runs}</strong></div>
      <div class="metric">Extractions<strong>{len(extractions)}</strong></div>
      <div class="metric">Failed extractions<strong>{failed_extractions}</strong></div>
    </section>
    <h2>Accounts</h2>
    {_table(["ID", "Name", "Owner", "Plan", "Status", "Updated"], account_rows)}
    <h2>Recent Extractions</h2>
    {_table(["ID", "Kind", "Status", "Account", "Project", "URL", "Confidence", "Created"], extraction_rows)}
    <h2>Recent Jobs</h2>
    {_table(["ID", "Name", "Account", "Project", "Status", "Next Run"], job_rows)}
    <h2>Recent Runs</h2>
    {_table(["ID", "Job", "Account", "Status", "Duration ms", "Created"], run_rows)}
    <h2>API Keys</h2>
    {_table(["ID", "Name", "Account", "Project", "Plan", "State"], key_rows)}
    <h2>Usage</h2>
    {_table(["Metric", "Quantity"], usage_rows)}
    """
    return HTMLResponse(_dashboard_shell("Dashboard", content, token_query=token_query))


@app.get("/dashboard/accounts/{account_id}", response_class=HTMLResponse, dependencies=[Depends(require_admin_access)])
def account_dashboard(account_id: str, request: Request, store: JobStore = Depends(get_job_store)) -> HTMLResponse:
    account = store.get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")
    projects = store.list_projects(account_id=account.id, limit=50)
    members = store.list_members(account_id=account.id, limit=50)
    jobs = store.list_jobs(limit=50, account_id=account.id)
    runs = store.list_runs(limit=50, account_id=account.id)
    api_keys = store.list_api_keys(limit=50, account_id=account.id)
    extractions = store.list_extractions(limit=50, account_id=account.id)
    usage = store.usage_summary(account_id=account.id)

    token_query = _dashboard_token_query(request)
    project_rows = [[f"<code>{_esc(project.id)}</code>", _esc(project.name), _esc(project.slug), _esc(project.updated_at)] for project in projects]
    member_rows = [[_esc(member.email), _esc(member.role.value), _esc(member.name), _esc(member.updated_at)] for member in members]
    job_rows = [[f"<code>{_esc(job.id)}</code>", _esc(job.name), _esc(job.project_id), _esc(job.status.value), _esc(job.next_run_at)] for job in jobs]
    run_rows = [[f"<code>{_esc(run.id)}</code>", f"<code>{_esc(run.job_id)}</code>", _esc(run.status.value), _esc(run.duration_ms), _esc(run.created_at)] for run in runs]
    key_rows = [[f"<code>{_esc(key.id)}</code>", _esc(key.name), _esc(key.project_id), _esc(key.billing_plan.value), _esc("disabled" if key.disabled else "active")] for key in api_keys]
    extraction_rows = [[f"<a href='/dashboard/extractions/{_esc(record.id)}{token_query}'><code>{_esc(record.id)}</code></a>", _esc(record.kind.value), _esc(record.status.value), _esc(record.project_id), _esc(record.url), _esc(record.confidence), _esc(record.created_at)] for record in extractions]
    usage_rows = [[_esc(item.metric.value), _esc(item.quantity)] for item in usage.items]

    content = f"""
    <p><a href="/dashboard{token_query}">Dashboard</a></p>
    <h1>{_esc(account.name)}</h1>
    <section class="grid">
      <div class="metric">Account ID<strong>{_esc(account.id)}</strong></div>
      <div class="metric">Plan<strong>{_esc(account.billing_plan.value)}</strong></div>
      <div class="metric">Status<strong>{_esc(account.status.value)}</strong></div>
      <div class="metric">Owner<strong>{_esc(account.owner)}</strong></div>
    </section>
    <h2>Projects</h2>
    {_table(["ID", "Name", "Slug", "Updated"], project_rows)}
    <h2>Members</h2>
    {_table(["Email", "Role", "Name", "Updated"], member_rows)}
    <h2>Extractions</h2>
    {_table(["ID", "Kind", "Status", "Project", "URL", "Confidence", "Created"], extraction_rows)}
    <h2>Jobs</h2>
    {_table(["ID", "Name", "Project", "Status", "Next Run"], job_rows)}
    <h2>Runs</h2>
    {_table(["ID", "Job", "Status", "Duration ms", "Created"], run_rows)}
    <h2>API Keys</h2>
    {_table(["ID", "Name", "Project", "Plan", "State"], key_rows)}
    <h2>Usage</h2>
    {_table(["Metric", "Quantity"], usage_rows)}
    """
    return HTMLResponse(_dashboard_shell(account.name, content, token_query=token_query))


@app.get("/dashboard/extractions/{extraction_id}", response_class=HTMLResponse, dependencies=[Depends(require_admin_access)])
def extraction_dashboard(extraction_id: str, request: Request, store: JobStore = Depends(get_job_store)) -> HTMLResponse:
    record = store.get_extraction(extraction_id)
    if not record:
        raise HTTPException(status_code=404, detail="Extraction not found.")
    token_query = _dashboard_token_query(request)
    payload = record.payload or {}
    product = payload.get("product") or {}
    rows = [
        ["ID", f"<code>{_esc(record.id)}</code>"],
        ["Kind", _esc(record.kind.value)],
        ["Status", _esc(record.status.value)],
        ["Account", _esc(record.account_id)],
        ["Project", _esc(record.project_id)],
        ["URL", _esc(record.url)],
        ["Confidence", _esc(record.confidence)],
        ["Product Count", _esc(record.product_count)],
        ["Error", f"<span class='danger'>{_esc(record.error)}</span>" if record.error else ""],
        ["Created", _esc(record.created_at)],
    ]
    product_rows = [
        ["Name", _esc(product.get("name"))],
        ["Brand", _esc(product.get("brand"))],
        ["Availability", _esc(product.get("availability"))],
        ["Price", _esc((product.get("price") or {}).get("amount"))],
        ["Currency", _esc((product.get("price") or {}).get("currency"))],
    ] if product else []
    content = f"""
    <p><a href="/dashboard{token_query}">Dashboard</a></p>
    <h1>Extraction</h1>
    {_table(["Field", "Value"], rows)}
    <h2>Product Summary</h2>
    {_table(["Field", "Value"], product_rows)}
    <h2>Payload</h2>
    <pre>{_esc(payload)}</pre>
    """
    return HTMLResponse(_dashboard_shell("Extraction", content, token_query=token_query))


@app.post("/v1/extract/product", response_model=ProductExtractionResult)
def extract_product_endpoint(request: ProductExtractionRequest, store: JobStore = Depends(get_job_store), key: ApiKeyRecord | None = Depends(require_api_key)) -> ProductExtractionResult:
    url = str(request.url) if request.url else None
    _meter(key, UsageMetric.product_extract, scope="extract:write")
    domain = require_domain_quota(store, key, url)
    if not request.url and not request.html:
        _record_extraction(store, key, ExtractionKind.product, ExtractionStatus.failed, error="Provide either 'url' or 'html'.")
        raise HTTPException(status_code=400, detail="Provide either 'url' or 'html'.")
    if request.llm_fallback:
        _record_extraction(store, key, ExtractionKind.product, ExtractionStatus.failed, url=str(request.url) if request.url else None, error="LLM fallback is planned for a later phase.")
        raise HTTPException(status_code=501, detail="LLM fallback is planned for a later phase. Use llm_fallback=false for now.")
    try:
        if request.render:
            if not url:
                _record_extraction(store, key, ExtractionKind.product, ExtractionStatus.failed, error="render=true requires a URL.", metadata={"render": request.render})
                raise HTTPException(status_code=400, detail="render=true requires a URL.")
            result = extract_product(url, render=True, screenshot_path=request.screenshot_path, html_snapshot_path=request.html_snapshot_path)
        else:
            html = request.html or (fetch_html(url) if url else None)
            assert html is not None
            result = extract_product_from_html(html, url=url)
        payload = result.model_dump(mode="json", exclude_none=True)
        _record_extraction(store, key, ExtractionKind.product, ExtractionStatus.succeeded, url=result.url or url, confidence=result.confidence, payload=payload, metadata={"render": request.render, "domain": domain})
        _record_usage(store, key, UsageMetric.product_extract, route="/v1/extract/product", metadata={"render": request.render, "domain": domain})
        return result
    except FetchError as exc:
        _record_extraction(store, key, ExtractionKind.product, ExtractionStatus.failed, url=url, error=str(exc), metadata={"render": request.render})
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RenderError as exc:
        _record_extraction(store, key, ExtractionKind.product, ExtractionStatus.failed, url=url, error=str(exc), metadata={"render": request.render})
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@app.post("/v1/extract/listing", response_model=ListingExtractionResult)
def extract_listing_endpoint(request: ListingExtractionRequest, store: JobStore = Depends(get_job_store), key: ApiKeyRecord | None = Depends(require_api_key)) -> ListingExtractionResult:
    url = str(request.url) if request.url else None
    _meter(key, UsageMetric.listing_extract, scope="extract:write")
    domain = require_domain_quota(store, key, url)
    if not request.url and not request.html:
        _record_extraction(store, key, ExtractionKind.listing, ExtractionStatus.failed, error="Provide either 'url' or 'html'.")
        raise HTTPException(status_code=400, detail="Provide either 'url' or 'html'.")
    try:
        if request.render:
            if not url:
                _record_extraction(store, key, ExtractionKind.listing, ExtractionStatus.failed, error="render=true requires a URL.", metadata={"render": request.render})
                raise HTTPException(status_code=400, detail="render=true requires a URL.")
            result = extract_listing(url, render=True, screenshot_path=request.screenshot_path, html_snapshot_path=request.html_snapshot_path)
        else:
            html = request.html or (fetch_html(url) if url else None)
            assert html is not None
            result = extract_listing_from_html(html, url=url)
        payload = result.model_dump(mode="json", exclude_none=True)
        _record_extraction(store, key, ExtractionKind.listing, ExtractionStatus.succeeded, url=result.url or url, confidence=result.confidence, product_count=result.product_count, payload=payload, metadata={"render": request.render, "domain": domain})
        _record_usage(store, key, UsageMetric.listing_extract, route="/v1/extract/listing", metadata={"products": len(result.products), "render": request.render, "domain": domain})
        return result
    except FetchError as exc:
        _record_extraction(store, key, ExtractionKind.listing, ExtractionStatus.failed, url=url, error=str(exc), metadata={"render": request.render})
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RenderError as exc:
        _record_extraction(store, key, ExtractionKind.listing, ExtractionStatus.failed, url=url, error=str(exc), metadata={"render": request.render})
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@app.get("/v1/extractions", response_model=list[ExtractionRecord])
def list_extractions_endpoint(
    kind: ExtractionKind | None = None,
    status: ExtractionStatus | None = None,
    limit: int = 100,
    store: JobStore = Depends(get_job_store),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> list[ExtractionRecord]:
    require_scope(key, "extractions:read")
    return store.list_extractions(
        kind=kind,
        status=status,
        account_id=key.account_id if key else None,
        project_id=key.project_id if key else None,
        limit=limit,
    )


@app.get("/v1/extractions/{extraction_id}", response_model=ExtractionRecord)
def get_extraction_endpoint(
    extraction_id: str,
    store: JobStore = Depends(get_job_store),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> ExtractionRecord:
    require_scope(key, "extractions:read")
    record = store.get_extraction(
        extraction_id,
        account_id=key.account_id if key else None,
        project_id=key.project_id if key else None,
    )
    if not record:
        raise HTTPException(status_code=404, detail="Extraction not found.")
    return record


@app.post("/v1/crawl/catalog", response_model=CatalogCrawlResult)
def crawl_catalog_endpoint(request: CatalogCrawlRequest, store: JobStore = Depends(get_job_store), key: ApiKeyRecord | None = Depends(require_api_key)) -> CatalogCrawlResult:
    _meter(key, UsageMetric.catalog_crawl, scope="crawl:write")
    domain = require_domain_quota(store, key, str(request.url))
    try:
        result = crawl_catalog(start_url=str(request.url), max_pages=request.max_pages, follow_next_pages=request.follow_next_pages, render=request.render, debug_dir=request.debug_dir)
        _record_usage(store, key, UsageMetric.catalog_crawl, route="/v1/crawl/catalog", metadata={"pages": result.pages_crawled, "products": len(result.products), "domain": domain})
        return result
    except FetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RenderError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@app.post("/v1/monitor/product", response_model=MonitorResult)
def monitor_product_endpoint(request: MonitorProductRequest, store: JobStore = Depends(get_job_store), key: ApiKeyRecord | None = Depends(require_api_key)) -> MonitorResult:
    _meter(key, UsageMetric.monitor_run, scope="monitor:write")
    domain = require_domain_quota(store, key, str(request.url))
    try:
        result = monitor_product(str(request.url), db_path=request.db_path, render=request.render)
        _record_usage(store, key, UsageMetric.monitor_run, route="/v1/monitor/product", metadata={"render": request.render, "changed": result.has_change, "domain": domain})
        return result
    except FetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RenderError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@app.post("/v1/monitor/batch", response_model=BatchMonitorResult)
def monitor_batch_endpoint(request: MonitorBatchRequest, store: JobStore = Depends(get_job_store), key: ApiKeyRecord | None = Depends(require_api_key)) -> BatchMonitorResult:
    _meter(key, UsageMetric.monitor_run, quantity=max(1, len(request.urls)), scope="monitor:write")
    domain_counts = Counter(url_domain(str(url)) for url in request.urls)
    for domain, count in domain_counts.items():
        if domain:
            require_domain_quota(store, key, f"https://{domain}", quantity=count)
    result = monitor_products([str(url) for url in request.urls], db_path=request.db_path, render=request.render)
    for domain, count in domain_counts.items():
        _record_usage(store, key, UsageMetric.monitor_run, quantity=count, route="/v1/monitor/batch", metadata={"urls": len(request.urls), "domain": domain})
    return result


@app.post("/v1/monitor/history", response_model=list[ProductSnapshot])
def price_history_endpoint(request: PriceHistoryRequest) -> list[ProductSnapshot]:
    if not request.product_key and not request.url:
        raise HTTPException(status_code=400, detail="Provide either 'product_key' or 'url'.")
    price_store = PriceSnapshotStore(request.db_path)
    return price_store.history(request.product_key, limit=request.limit) if request.product_key else price_store.history_for_url(str(request.url), limit=request.limit)


@app.post("/v1/alerts/run", response_model=MonitorRunResult)
def run_alert_config_endpoint(request: RunMonitorConfigRequest, store: JobStore = Depends(get_job_store), key: ApiKeyRecord | None = Depends(require_api_key)) -> MonitorRunResult:
    _meter(key, UsageMetric.monitor_run, scope="monitor:write")
    result = run_monitor_config(request.config, dry_run=request.dry_run, deliver=request.deliver)
    _record_usage(store, key, UsageMetric.monitor_run, route="/v1/alerts/run", metadata={"events": len(result.events), "warnings": len(result.warnings)})
    return result


@app.post("/v1/alerts/run-file", response_model=MonitorRunResult)
def run_alert_config_file_endpoint(request: RunMonitorConfigFileRequest) -> MonitorRunResult:
    return run_monitor_config_file(request.path, dry_run=request.dry_run, deliver=request.deliver)


@app.post("/v1/jobs", response_model=MonitoringJob)
def create_job_endpoint(request: MonitoringJobCreate, store: JobStore = Depends(get_job_store), key: ApiKeyRecord | None = Depends(require_api_key)) -> MonitoringJob:
    _meter(key, UsageMetric.api_request, scope="jobs:write")
    if key:
        request.account_id = request.account_id or key.account_id
        request.project_id = request.project_id or key.project_id
        request.owner = request.owner or key.owner
    return store.create_job(request)


@app.get("/v1/jobs", response_model=list[MonitoringJob])
def list_jobs_endpoint(status: JobStatus | None = None, limit: int = 100, store: JobStore = Depends(get_job_store), key: ApiKeyRecord | None = Depends(require_api_key)) -> list[MonitoringJob]:
    require_scope(key, "jobs:read")
    return store.list_jobs(status=status, limit=limit, account_id=key.account_id if key else None, project_id=key.project_id if key else None)


@app.get("/v1/jobs/{job_id}", response_model=MonitoringJob)
def get_job_endpoint(job_id: str, store: JobStore = Depends(get_job_store), key: ApiKeyRecord | None = Depends(require_api_key)) -> MonitoringJob:
    require_scope(key, "jobs:read")
    job = store.get_job(job_id, account_id=key.account_id if key else None, project_id=key.project_id if key else None)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


@app.patch("/v1/jobs/{job_id}", response_model=MonitoringJob)
def update_job_endpoint(job_id: str, request: MonitoringJobUpdate, store: JobStore = Depends(get_job_store), key: ApiKeyRecord | None = Depends(require_api_key)) -> MonitoringJob:
    require_scope(key, "jobs:write")
    job = store.update_job(job_id, request, account_id=key.account_id if key else None, project_id=key.project_id if key else None)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


@app.delete("/v1/jobs/{job_id}")
def delete_job_endpoint(job_id: str, store: JobStore = Depends(get_job_store), key: ApiKeyRecord | None = Depends(require_api_key)) -> dict[str, bool]:
    require_scope(key, "jobs:write")
    deleted = store.delete_job(job_id, account_id=key.account_id if key else None, project_id=key.project_id if key else None)
    if not deleted:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"deleted": True}


@app.post("/v1/jobs/{job_id}/run", response_model=JobRun)
def run_job_endpoint(job_id: str, dry_run: bool = False, deliver: bool = True, store: JobStore = Depends(get_job_store), key: ApiKeyRecord | None = Depends(require_api_key)) -> JobRun:
    _meter(key, UsageMetric.job_run, scope="jobs:write")
    job = store.get_job(job_id, account_id=key.account_id if key else None, project_id=key.project_id if key else None)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return run_job_now(store, job.id, dry_run=dry_run, deliver=deliver)


@app.get("/v1/runs", response_model=list[JobRun])
def list_runs_endpoint(job_id: str | None = None, limit: int = 100, store: JobStore = Depends(get_job_store), key: ApiKeyRecord | None = Depends(require_api_key)) -> list[JobRun]:
    require_scope(key, "runs:read")
    return store.list_runs(job_id=job_id, limit=limit, account_id=key.account_id if key else None, project_id=key.project_id if key else None)


@app.get("/v1/runs/{run_id}", response_model=JobRun)
def get_run_endpoint(run_id: str, store: JobStore = Depends(get_job_store), key: ApiKeyRecord | None = Depends(require_api_key)) -> JobRun:
    require_scope(key, "runs:read")
    run = store.get_run(run_id, account_id=key.account_id if key else None, project_id=key.project_id if key else None)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")
    return run


@app.post("/v1/worker/tick", response_model=WorkerTickResult)
def worker_tick_endpoint(limit: int = 25, dry_run: bool = False, deliver: bool = True, store: JobStore = Depends(get_job_store), key: ApiKeyRecord | None = Depends(require_api_key)) -> WorkerTickResult:
    require_scope(key, "worker:write")
    return MonitoringWorker(store=store).tick(limit=limit, dry_run=dry_run, deliver=deliver)


@app.post("/v1/api-keys", response_model=ApiKeyCreateResult, dependencies=[Depends(require_admin_token)])
def create_api_key_endpoint(request: ApiKeyCreate, store: JobStore = Depends(get_job_store)) -> ApiKeyCreateResult:
    return store.create_api_key(request)


@app.get("/v1/usage/events", response_model=list[UsageEvent])
def list_usage_events_endpoint(metric: UsageMetric | None = None, since: str | None = None, until: str | None = None, limit: int = 100, store: JobStore = Depends(get_job_store), key: ApiKeyRecord | None = Depends(require_api_key)) -> list[UsageEvent]:
    require_scope(key, "usage:read")
    return store.list_usage_events(account_id=key.account_id if key else None, project_id=key.project_id if key else None, metric=metric, since=since, until=until, limit=limit)


@app.get("/v1/usage/summary", response_model=UsageSummary)
def usage_summary_endpoint(since: str | None = None, until: str | None = None, store: JobStore = Depends(get_job_store), key: ApiKeyRecord | None = Depends(require_api_key)) -> UsageSummary:
    require_scope(key, "usage:read")
    return store.usage_summary(account_id=key.account_id if key else None, project_id=key.project_id if key else None, since=since, until=until)


@app.get("/v1/billing/usage", response_model=BillingUsageSnapshot)
def billing_usage_endpoint(key: ApiKeyRecord | None = Depends(require_api_key)) -> BillingUsageSnapshot:
    if key is None:
        raise HTTPException(status_code=400, detail="Billing usage requires API key auth. Set COMMERCELENS_REQUIRE_API_KEY=true.")
    require_scope(key, "usage:read")
    decisions = [quota_decision(key, metric, 0) for metric in UsageMetric]
    return BillingUsageSnapshot(account_id=key.account_id, project_id=key.project_id, api_key_id=key.id, billing_plan=key.billing_plan, period_start=decisions[0].period_start, period_end=decisions[0].period_end, blocked=any(not decision.allowed for decision in decisions), items=[BillingUsageItem(metric=decision.metric, used=decision.used, limit=decision.limit, remaining=decision.remaining) for decision in decisions])


@app.post("/v1/records/normalize", response_model=DatasetLoadResult)
def normalize_records_endpoint(request: NormalizeRecordsRequest) -> DatasetLoadResult:
    return DatasetLoadResult(records=request.records)


@app.post("/v1/match/products", response_model=ProductMatchResult)
def match_products_endpoint(request: MatchProductsRequest, store: JobStore = Depends(get_job_store), key: ApiKeyRecord | None = Depends(require_api_key)) -> ProductMatchResult:
    _meter(key, UsageMetric.match_request, scope="match:write")
    result = match_products(request.left, request.right, threshold=request.threshold, top_k=request.top_k)
    _record_usage(store, key, UsageMetric.match_request, route="/v1/match/products", metadata={"left": len(request.left), "right": len(request.right), "matches": len(result.matches)})
    return result
