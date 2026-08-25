from __future__ import annotations

import os
import json
import logging
import time
from collections import Counter
from html import escape
from typing import Sequence
from urllib.parse import parse_qs, urlencode
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from commercelens.alerts.runner import MonitorRunResult, run_monitor_config, run_monitor_config_file
from commercelens.api.auth import (
    get_job_store,
    require_account_active,
    require_admin_access,
    require_admin_token,
    require_api_key,
)
from commercelens.api.domain_limits import require_domain_quota, url_domain
from commercelens.api.quota import quota_decision, require_quota, require_scope
from commercelens.connectors.datasets import DatasetLoadResult
from commercelens.connectors.stripe import (
    apply_subscription_event,
    create_checkout_session,
    parse_stripe_event,
    verify_stripe_signature,
)
from commercelens.core.crawler import CatalogCrawlResult, crawl_catalog
from commercelens.core.fetcher import FetchError, fetch_html
from commercelens.core.monitor import (
    BatchMonitorResult,
    MonitorResult,
    monitor_product,
    monitor_products,
)
from commercelens.core.renderer import RenderError
from commercelens.extractors.listing import extract_listing, extract_listing_from_html
from commercelens.extractors.product import extract_product, extract_product_from_html
from commercelens.intelligence.price_summary import PriceIntelligenceSummary, summarize_prices
from commercelens.jobs.failures import (
    classify_failure,
    failed_extraction_issue,
    failed_run_issue,
    recommendation_for_failure,
)
from commercelens.jobs.models import (
    AccountCreate,
    AccountRecord,
    AccountStatus,
    ApiKeyCreate,
    ApiKeyCreateResult,
    ApiKeyRecord,
    BillingPlan,
    BillingUsageItem,
    BillingUsageSnapshot,
    ExtractionCreate,
    ExtractionKind,
    ExtractionRecord,
    ExtractionStatus,
    JobRun,
    JobStatus,
    MemberCreate,
    MemberRecord,
    MemberRole,
    MonitoringJob,
    MonitoringJobCreate,
    MonitoringJobUpdate,
    ProjectCreate,
    ProjectRecord,
    UsageEvent,
    UsageMetric,
    UsageSummary,
    WorkerTickResult,
)
from commercelens.jobs.store import JobStore
from commercelens.jobs.worker import MonitoringWorker, run_job_now
from commercelens.matching.catalog_diff import CatalogDiffResult, diff_catalogs
from commercelens.matching.identity import ProductIdentityGraph, build_identity_graph
from commercelens.matching.products import ProductMatchResult, match_products
from commercelens.schemas.alerts import RunMonitorConfigFileRequest, RunMonitorConfigRequest
from commercelens.schemas.connectors import (
    MatchProductsRequest,
    CatalogDiffRequest,
    NormalizeRecordsRequest,
    PriceSummaryRequest,
    ProductIdentityGraphRequest,
)
from commercelens.schemas.dashboard import (
    DashboardSummary,
    MonitoredTargetSummary,
    MonitoringOverview,
)
from commercelens.schemas.listing import (
    CatalogCrawlRequest,
    ListingExtractionRequest,
    ListingExtractionResult,
)
from commercelens.schemas.monitor import (
    MonitorBatchRequest,
    MonitorProductRequest,
    PriceHistoryRequest,
)
from commercelens.schemas.product import ProductExtractionRequest, ProductExtractionResult
from commercelens.storage.price_store import PriceSnapshotStore, ProductSnapshot
from commercelens.version import __version__

API_VERSION = __version__
LOGGER = logging.getLogger("commercelens.api")

app = FastAPI(
    title="CommerceLens API",
    description="Competitor price, availability, and catalog monitoring.",
    version=API_VERSION,
)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or f"req_{uuid4().hex[:16]}"
    started = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    response.headers["X-Request-ID"] = request_id
    LOGGER.info(
        "request_complete",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    return response


class OnboardingRequest(BaseModel):
    account_name: str
    owner_email: str
    project_name: str = "Default"
    project_slug: str | None = None
    billing_plan: BillingPlan = BillingPlan.free
    account_status: AccountStatus = AccountStatus.trialing
    member_name: str | None = None
    member_role: MemberRole = MemberRole.owner
    api_key_name: str = "customer portal key"
    scopes: list[str] = Field(default_factory=lambda: ["*"])
    monthly_domain_quotas: dict[str, int] = Field(default_factory=dict)


class OnboardingResult(BaseModel):
    account: AccountRecord
    project: ProjectRecord
    member: MemberRecord
    api_key: ApiKeyRecord
    token: str
    portal_path: str


class AccountUpdate(BaseModel):
    name: str | None = None
    owner: str | None = None
    billing_plan: BillingPlan | None = None
    status: AccountStatus | None = None
    metadata: dict | None = None


class StripeCheckoutRequest(BaseModel):
    account_id: str
    price_id: str
    success_url: str
    cancel_url: str
    billing_plan: BillingPlan
    customer_email: str | None = None
    trial_days: int | None = Field(default=None, ge=1, le=365)


class StripeCheckoutResponse(BaseModel):
    id: str
    url: str
    account_id: str
    billing_plan: BillingPlan


def _usage_context(key: ApiKeyRecord | None) -> dict[str, str | None]:
    if not key:
        return {"account_id": None, "project_id": None, "owner": None, "api_key_id": None}
    return {
        "account_id": key.account_id,
        "project_id": key.project_id,
        "owner": key.owner,
        "api_key_id": key.id,
    }


def _record_usage(
    store: JobStore,
    key: ApiKeyRecord | None,
    metric: UsageMetric,
    quantity: int = 1,
    route: str | None = None,
    status_code: int | None = None,
    metadata: dict | None = None,
) -> None:
    context = _usage_context(key)
    store.record_usage(
        UsageEvent(
            metric=metric,
            quantity=quantity,
            account_id=context["account_id"],
            project_id=context["project_id"],
            owner=context["owner"],
            api_key_id=context["api_key_id"],
            route=route,
            status_code=status_code,
            metadata=metadata or {},
        )
    )


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
    metadata = metadata or {}
    failure_class = classify_failure(error, confidence=confidence, metadata=metadata)
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
            failure_class=failure_class,
            recommendation=recommendation_for_failure(failure_class),
            metadata=metadata,
        )
    )


def _meter(
    key: ApiKeyRecord | None, metric: UsageMetric, quantity: int = 1, scope: str | None = None
) -> None:
    if scope:
        require_scope(key, scope)
    require_quota(key, metric, quantity)


def _esc(value: object) -> str:
    return escape("" if value is None else str(value))


def _dashboard_token_query(request: Request) -> str:
    token = request.query_params.get("admin_token")
    return "?" + urlencode({"admin_token": token}) if token else ""


def _dashboard_action(path: str, request: Request, **params: object) -> str:
    token = request.query_params.get("admin_token")
    query = {key: value for key, value in params.items() if value is not None}
    if token:
        query["admin_token"] = token
    suffix = "?" + urlencode(query) if query else ""
    return f"{path}{suffix}"


def _portal_key_query(request: Request) -> str:
    token = request.query_params.get("api_key")
    return "?" + urlencode({"api_key": token}) if token else ""


def _require_portal_key(request: Request, store: JobStore) -> ApiKeyRecord:
    token = request.headers.get("X-API-Key") or request.query_params.get("api_key")
    if not token:
        raise HTTPException(
            status_code=401, detail="Missing api_key query parameter or X-API-Key header."
        )
    key = store.verify_api_key(token)
    if not key:
        raise HTTPException(status_code=401, detail="Invalid API key.")
    require_account_active(store, key)
    require_scope(key, "usage:read")
    require_scope(key, "jobs:read")
    require_scope(key, "runs:read")
    require_scope(key, "extractions:read")
    return key


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
    form {{ background: white; border: 1px solid #e5e7eb; border-radius: 8px; padding: 14px; margin: 12px 0; display: grid; gap: 10px; grid-template-columns: repeat(3, minmax(0, 1fr)); }}
    label {{ display: grid; gap: 4px; font-size: 13px; color: #4b5563; }}
    input, select {{ font: inherit; padding: 8px 10px; border: 1px solid #d1d5db; border-radius: 6px; }}
    button {{ font: inherit; padding: 9px 12px; border: 1px solid #111827; border-radius: 6px; background: #111827; color: white; cursor: pointer; align-self: end; }}
    code {{ background: #eef2ff; padding: 2px 5px; border-radius: 4px; }}
    .muted {{ color: #6b7280; }}
    .danger {{ color: #b91c1c; }}
    @media (max-width: 900px) {{ .grid, form {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} main {{ padding: 18px; }} }}
    @media (max-width: 560px) {{ form {{ grid-template-columns: 1fr; }} }}
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


def _portal_shell(title: str, content: str, token_query: str = "") -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_esc(title)} - CommerceLens</title>
  <style>
    body {{ margin: 0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif; color: #18212f; background: #f7f8fa; }}
    header {{ background: #0f172a; color: white; padding: 16px 24px; display: flex; justify-content: space-between; align-items: center; }}
    header a {{ color: #bfdbfe; text-decoration: none; margin-left: 16px; }}
    main {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}
    h1 {{ font-size: 26px; margin: 0 0 18px; }}
    h2 {{ font-size: 17px; margin: 26px 0 10px; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }}
    .metric {{ background: white; border: 1px solid #dfe4ea; border-radius: 8px; padding: 14px; }}
    .metric strong {{ display: block; font-size: 24px; margin-top: 6px; }}
    .panel {{ background: white; border: 1px solid #dfe4ea; border-radius: 8px; padding: 16px; margin-top: 16px; }}
    table {{ width: 100%; border-collapse: collapse; background: white; border: 1px solid #dfe4ea; border-radius: 8px; overflow: hidden; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid #e6eaf0; text-align: left; vertical-align: top; font-size: 14px; }}
    th {{ background: #f1f5f9; color: #475569; font-weight: 600; }}
    tr:last-child td {{ border-bottom: 0; }}
    code {{ background: #eef2ff; padding: 2px 5px; border-radius: 4px; }}
    .muted {{ color: #64748b; }}
    .danger {{ color: #b91c1c; }}
    @media (max-width: 900px) {{ .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} main {{ padding: 16px; }} }}
    @media (max-width: 560px) {{ .grid {{ grid-template-columns: 1fr; }} th, td {{ font-size: 13px; }} }}
  </style>
</head>
<body>
  <header>
    <div><strong>CommerceLens</strong> <span class="muted">customer portal</span></div>
    <nav><a href="/portal{token_query}">Overview</a><a href="/docs">API Docs</a></nav>
  </header>
  <main>{content}</main>
</body>
</html>"""


def _table(headers: list[str], rows: Sequence[Sequence[object]]) -> str:
    head = "".join(f"<th>{_esc(header)}</th>" for header in headers)
    if not rows:
        return f"<table><thead><tr>{head}</tr></thead><tbody><tr><td colspan='{len(headers)}' class='muted'>No records</td></tr></tbody></table>"
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _pre_json(value: object) -> str:
    return f"<pre>{_esc(json.dumps(value, indent=2, sort_keys=True, default=str))}</pre>"


def _portal_href(path: str, token_query: str) -> str:
    return f"{path}{token_query}"


async def _urlencoded_form(request: Request) -> dict[str, str]:
    raw = (await request.body()).decode("utf-8")
    parsed = parse_qs(raw, keep_blank_values=True)
    return {key: values[-1] for key, values in parsed.items() if values}


def _recent_issues(
    runs: Sequence[JobRun],
    extractions: Sequence[ExtractionRecord],
    limit: int = 20,
) -> list[dict]:
    issues = [issue for run in runs for issue in [failed_run_issue(run)] if issue]
    issues.extend(
        issue for record in extractions for issue in [failed_extraction_issue(record)] if issue
    )
    return sorted(issues, key=lambda item: str(item.get("created_at") or ""), reverse=True)[:limit]


def _failure_summary(issues: Sequence[dict]) -> list[list[object]]:
    counts: Counter[tuple[str, str]] = Counter()
    for issue in issues:
        failure_class = str(issue.get("failure_class") or "unknown")
        domain = str(issue.get("domain") or "job-run")
        counts[(failure_class, domain)] += 1
    return [
        [_esc(failure_class), _esc(domain), _esc(count)]
        for (failure_class, domain), count in counts.most_common()
    ]


def _build_monitoring_overview(
    store: JobStore,
    key: ApiKeyRecord | None,
    limit: int = 100,
) -> MonitoringOverview:
    account_id = key.account_id if key else None
    project_id = key.project_id if key else None
    jobs = store.list_jobs(limit=limit, account_id=account_id, project_id=project_id)
    runs = store.list_runs(limit=limit, account_id=account_id, project_id=project_id)
    targets: list[MonitoredTargetSummary] = []
    rule_count = 0
    render_count = 0
    seen_urls: set[str] = set()
    for job in jobs:
        rule_count += len(job.config.rules)
        for target in job.config.targets:
            url = str(target.url)
            if url in seen_urls:
                continue
            seen_urls.add(url)
            render = bool(target.render or job.config.render)
            if render:
                render_count += 1
            targets.append(
                MonitoredTargetSummary(
                    url=url,
                    job_id=job.id,
                    job_name=job.name,
                    job_status=job.status.value,
                    render=render,
                    tags=target.tags,
                    last_run_at=job.last_run_at,
                    next_run_at=job.next_run_at,
                    last_error=job.last_error,
                )
            )
    failed_runs = [run for run in runs if run.status.value == "failed"]
    return MonitoringOverview(
        target_count=len(targets),
        active_job_count=sum(1 for job in jobs if job.status.value == "active"),
        failed_run_count=len(failed_runs),
        rule_count=rule_count,
        render_target_count=render_count,
        recent_failure_count=sum(1 for target in targets if target.last_error),
        targets=targets[:limit],
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "commercelens", "version": API_VERSION}


@app.get("/ready")
def readiness(store: JobStore = Depends(get_job_store)) -> dict[str, str | bool]:
    store.usage_summary()
    backend = os.getenv("COMMERCELENS_STORE_BACKEND", "sqlite").lower()
    stripe_secret_configured = bool(os.getenv("STRIPE_SECRET_KEY"))
    stripe_webhook_configured = bool(os.getenv("STRIPE_WEBHOOK_SECRET"))
    return {
        "status": "ready",
        "service": "commercelens",
        "version": API_VERSION,
        "store_backend": backend,
        "store_reachable": True,
        "api_key_required": os.getenv("COMMERCELENS_REQUIRE_API_KEY", "false").lower()
        in {"1", "true", "yes"},
        "admin_token_configured": bool(os.getenv("COMMERCELENS_ADMIN_TOKEN")),
        "stripe_secret_configured": stripe_secret_configured,
        "stripe_webhook_configured": stripe_webhook_configured,
        "domain_concurrency_configured": bool(os.getenv("COMMERCELENS_DOMAIN_CONCURRENCY_LIMIT")),
        "worker_concurrency_configured": bool(os.getenv("COMMERCELENS_WORKER_CONCURRENCY")),
        "migrations_checked": backend == "postgres",
    }


@app.post(
    "/v1/accounts", response_model=AccountRecord, dependencies=[Depends(require_admin_access)]
)
def create_account_endpoint(
    request: AccountCreate, store: JobStore = Depends(get_job_store)
) -> AccountRecord:
    return store.create_account(request)


@app.get(
    "/v1/accounts", response_model=list[AccountRecord], dependencies=[Depends(require_admin_access)]
)
def list_accounts_endpoint(
    limit: int = 100, store: JobStore = Depends(get_job_store)
) -> list[AccountRecord]:
    return store.list_accounts(limit=limit)


@app.get(
    "/v1/accounts/{account_id}",
    response_model=AccountRecord,
    dependencies=[Depends(require_admin_access)],
)
def get_account_endpoint(
    account_id: str, store: JobStore = Depends(get_job_store)
) -> AccountRecord:
    account = store.get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")
    return account


@app.patch(
    "/v1/accounts/{account_id}",
    response_model=AccountRecord,
    dependencies=[Depends(require_admin_access)],
)
def update_account_endpoint(
    account_id: str, request: AccountUpdate, store: JobStore = Depends(get_job_store)
) -> AccountRecord:
    account = store.get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")
    updates = request.model_dump(exclude_unset=True)
    for key, value in updates.items():
        if value is not None:
            setattr(account, key, value)
    return store.save_account(account)


@app.post(
    "/v1/accounts/{account_id}/projects",
    response_model=ProjectRecord,
    dependencies=[Depends(require_admin_access)],
)
def create_project_endpoint(
    account_id: str, request: ProjectCreate, store: JobStore = Depends(get_job_store)
) -> ProjectRecord:
    try:
        return store.create_project(account_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get(
    "/v1/accounts/{account_id}/projects",
    response_model=list[ProjectRecord],
    dependencies=[Depends(require_admin_access)],
)
def list_projects_endpoint(
    account_id: str, limit: int = 100, store: JobStore = Depends(get_job_store)
) -> list[ProjectRecord]:
    if not store.get_account(account_id):
        raise HTTPException(status_code=404, detail="Account not found.")
    return store.list_projects(account_id=account_id, limit=limit)


@app.post(
    "/v1/accounts/{account_id}/members",
    response_model=MemberRecord,
    dependencies=[Depends(require_admin_access)],
)
def create_member_endpoint(
    account_id: str, request: MemberCreate, store: JobStore = Depends(get_job_store)
) -> MemberRecord:
    try:
        return store.create_member(account_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get(
    "/v1/accounts/{account_id}/members",
    response_model=list[MemberRecord],
    dependencies=[Depends(require_admin_access)],
)
def list_members_endpoint(
    account_id: str, limit: int = 100, store: JobStore = Depends(get_job_store)
) -> list[MemberRecord]:
    if not store.get_account(account_id):
        raise HTTPException(status_code=404, detail="Account not found.")
    return store.list_members(account_id=account_id, limit=limit)


@app.post(
    "/v1/onboarding", response_model=OnboardingResult, dependencies=[Depends(require_admin_access)]
)
def onboarding_endpoint(
    request: OnboardingRequest, store: JobStore = Depends(get_job_store)
) -> OnboardingResult:
    account = store.create_account(
        AccountCreate(
            name=request.account_name,
            owner=request.owner_email,
            billing_plan=request.billing_plan,
            status=request.account_status,
        )
    )
    project = store.create_project(
        account.id,
        ProjectCreate(name=request.project_name, slug=request.project_slug),
    )
    member = store.create_member(
        account.id,
        MemberCreate(email=request.owner_email, role=request.member_role, name=request.member_name),
    )
    key_result = store.create_api_key(
        ApiKeyCreate(
            name=request.api_key_name,
            owner=request.owner_email,
            account_id=account.id,
            project_id=project.id,
            scopes=request.scopes,
            billing_plan=request.billing_plan,
            monthly_domain_quotas=request.monthly_domain_quotas,
        )
    )
    return OnboardingResult(
        account=account,
        project=project,
        member=member,
        api_key=key_result.key,
        token=key_result.token,
        portal_path=f"/portal?api_key={key_result.token}",
    )


@app.post(
    "/dashboard/onboarding",
    response_class=HTMLResponse,
    dependencies=[Depends(require_admin_access)],
)
async def dashboard_onboarding(
    request: Request, store: JobStore = Depends(get_job_store)
) -> HTMLResponse:
    form = await _urlencoded_form(request)
    domain_quotas = {}
    raw_domain_quota = form.get("domain_quota", "").strip()
    if raw_domain_quota:
        for item in raw_domain_quota.split(","):
            if "=" in item:
                domain, limit = item.split("=", 1)
                domain_quotas[domain.strip().lower()] = int(limit.strip())
    result = onboarding_endpoint(
        OnboardingRequest(
            account_name=form.get("account_name", "New Customer"),
            owner_email=form.get("owner_email", ""),
            project_name=form.get("project_name", "Default"),
            billing_plan=BillingPlan(form.get("billing_plan", BillingPlan.free.value)),
            monthly_domain_quotas=domain_quotas,
        ),
        store=store,
    )
    token_query = _dashboard_token_query(request)
    content = f"""
    <p><a href="/dashboard{token_query}">Dashboard</a></p>
    <h1>Customer Onboarded</h1>
    {
        _table(
            ["Field", "Value"],
            [
                [
                    "Account",
                    f"<a href='/dashboard/accounts/{_esc(result.account.id)}{token_query}'><code>{_esc(result.account.id)}</code></a>",
                ],
                ["Project", f"<code>{_esc(result.project.id)}</code>"],
                ["Owner", _esc(result.member.email)],
                ["API Key", f"<code>{_esc(result.api_key.id)}</code>"],
                ["Portal", f"<code>{_esc(result.portal_path)}</code>"],
            ],
        )
    }
    """
    return HTMLResponse(_dashboard_shell("Customer Onboarded", content, token_query=token_query))


@app.post("/dashboard/accounts/{account_id}/status", dependencies=[Depends(require_admin_access)])
def dashboard_account_status(
    account_id: str,
    status_value: AccountStatus,
    request: Request,
    store: JobStore = Depends(get_job_store),
) -> RedirectResponse:
    account = update_account_endpoint(account_id, AccountUpdate(status=status_value), store=store)
    return RedirectResponse(
        _dashboard_action(f"/dashboard/accounts/{account.id}", request), status_code=303
    )


@app.post(
    "/dashboard/accounts/{account_id}/checkout",
    response_class=HTMLResponse,
    dependencies=[Depends(require_admin_access)],
)
async def dashboard_checkout(
    account_id: str, request: Request, store: JobStore = Depends(get_job_store)
) -> HTMLResponse:
    form = await _urlencoded_form(request)
    response = stripe_checkout_session_endpoint(
        StripeCheckoutRequest(
            account_id=account_id,
            price_id=form.get("price_id", ""),
            success_url=form.get("success_url", ""),
            cancel_url=form.get("cancel_url", ""),
            billing_plan=BillingPlan(form.get("billing_plan", BillingPlan.team.value)),
            customer_email=form.get("customer_email") or None,
            trial_days=int(form["trial_days"]) if form.get("trial_days") else None,
        ),
        store=store,
    )
    token_query = _dashboard_token_query(request)
    content = f"""
    <p><a href="/dashboard/accounts/{_esc(account_id)}{token_query}">Account</a></p>
    <h1>Checkout Session</h1>
    {
        _table(
            ["Field", "Value"],
            [
                ["Session", f"<code>{_esc(response.id)}</code>"],
                ["Plan", _esc(response.billing_plan.value)],
                ["URL", f"<a href='{_esc(response.url)}'>{_esc(response.url)}</a>"],
            ],
        )
    }
    """
    return HTMLResponse(_dashboard_shell("Checkout Session", content, token_query=token_query))


@app.get("/dashboard", response_class=HTMLResponse, dependencies=[Depends(require_admin_access)])
def dashboard(request: Request, store: JobStore = Depends(get_job_store)) -> HTMLResponse:
    accounts = store.list_accounts(limit=50)
    jobs = store.list_jobs(limit=50)
    runs = store.list_runs(limit=50)
    api_keys = store.list_api_keys(limit=50)
    extractions = store.list_extractions(limit=50)
    usage = store.usage_summary()
    active_jobs = sum(1 for job in jobs if job.status == JobStatus.active)
    failed_runs = sum(
        1 for run in runs if str(run.status) == "RunStatus.failed" or run.status.value == "failed"
    )
    failed_extractions = sum(
        1 for record in extractions if record.status == ExtractionStatus.failed
    )
    issues = _recent_issues(runs, extractions, limit=20)

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
    issue_rows = [
        [
            _esc(issue.get("source")),
            _esc(issue.get("failure_class")),
            _esc(issue.get("domain") or issue.get("job_id")),
            _esc(issue.get("account_id")),
            _esc(issue.get("project_id")),
            f"<span class='danger'>{_esc(issue.get('error'))}</span>",
            _esc(issue.get("recommendation")),
        ]
        for issue in issues[:12]
    ]

    content = f"""
    <h1>Dashboard</h1>
    <h2>Onboard Customer</h2>
    <form method="post" action="{_dashboard_action("/dashboard/onboarding", request)}">
      <label>Account name<input name="account_name" required></label>
      <label>Owner email<input name="owner_email" type="email" required></label>
      <label>Project name<input name="project_name" value="Competitor Watch"></label>
      <label>Plan<select name="billing_plan"><option value="free">free</option><option value="developer">developer</option><option value="team">team</option><option value="enterprise">enterprise</option></select></label>
      <label>Domain quotas<input name="domain_quota" placeholder="example.com=500,*=100"></label>
      <button type="submit">Create Workspace</button>
    </form>
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
    <h2>Failure Triage</h2>
    {_table(["Class", "Domain", "Count"], _failure_summary(issues))}
    <h2>Recent Issues</h2>
    {_table(["Source", "Class", "Domain/Job", "Account", "Project", "Error", "Recommendation"], issue_rows)}
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


@app.get(
    "/dashboard/accounts/{account_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(require_admin_access)],
)
def account_dashboard(
    account_id: str, request: Request, store: JobStore = Depends(get_job_store)
) -> HTMLResponse:
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
    issues = _recent_issues(runs, extractions, limit=20)

    token_query = _dashboard_token_query(request)
    project_rows = [
        [
            f"<code>{_esc(project.id)}</code>",
            _esc(project.name),
            _esc(project.slug),
            _esc(project.updated_at),
        ]
        for project in projects
    ]
    member_rows = [
        [_esc(member.email), _esc(member.role.value), _esc(member.name), _esc(member.updated_at)]
        for member in members
    ]
    job_rows = [
        [
            f"<code>{_esc(job.id)}</code>",
            _esc(job.name),
            _esc(job.project_id),
            _esc(job.status.value),
            _esc(job.next_run_at),
        ]
        for job in jobs
    ]
    run_rows = [
        [
            f"<code>{_esc(run.id)}</code>",
            f"<code>{_esc(run.job_id)}</code>",
            _esc(run.status.value),
            _esc(run.duration_ms),
            _esc(run.created_at),
        ]
        for run in runs
    ]
    key_rows = [
        [
            f"<code>{_esc(key.id)}</code>",
            _esc(key.name),
            _esc(key.project_id),
            _esc(key.billing_plan.value),
            _esc("disabled" if key.disabled else "active"),
        ]
        for key in api_keys
    ]
    extraction_rows = [
        [
            f"<a href='/dashboard/extractions/{_esc(record.id)}{token_query}'><code>{_esc(record.id)}</code></a>",
            _esc(record.kind.value),
            _esc(record.status.value),
            _esc(record.project_id),
            _esc(record.url),
            _esc(record.confidence),
            _esc(record.created_at),
        ]
        for record in extractions
    ]
    usage_rows = [[_esc(item.metric.value), _esc(item.quantity)] for item in usage.items]
    issue_rows = [
        [
            _esc(issue.get("source")),
            _esc(issue.get("failure_class")),
            _esc(issue.get("domain") or issue.get("job_id")),
            f"<span class='danger'>{_esc(issue.get('error'))}</span>",
            _esc(issue.get("recommendation")),
        ]
        for issue in issues
    ]
    suspend_action = _dashboard_action(
        f"/dashboard/accounts/{account.id}/status",
        request,
        status_value=AccountStatus.suspended.value,
    )
    reactivate_action = _dashboard_action(
        f"/dashboard/accounts/{account.id}/status", request, status_value=AccountStatus.active.value
    )
    checkout_action = _dashboard_action(f"/dashboard/accounts/{account.id}/checkout", request)

    content = f"""
    <p><a href="/dashboard{token_query}">Dashboard</a></p>
    <h1>{_esc(account.name)}</h1>
    <section class="grid">
      <div class="metric">Account ID<strong>{_esc(account.id)}</strong></div>
      <div class="metric">Plan<strong>{_esc(account.billing_plan.value)}</strong></div>
      <div class="metric">Status<strong>{_esc(account.status.value)}</strong></div>
      <div class="metric">Owner<strong>{_esc(account.owner)}</strong></div>
    </section>
    <h2>Account Controls</h2>
    <form method="post" action="{suspend_action}">
      <button type="submit">Suspend Account</button>
    </form>
    <form method="post" action="{reactivate_action}">
      <button type="submit">Reactivate Account</button>
    </form>
    <h2>Create Checkout Session</h2>
    <form method="post" action="{checkout_action}">
      <label>Stripe price ID<input name="price_id" required></label>
      <label>Success URL<input name="success_url" required></label>
      <label>Cancel URL<input name="cancel_url" required></label>
      <label>Plan<select name="billing_plan"><option value="developer">developer</option><option value="team">team</option><option value="enterprise">enterprise</option></select></label>
      <label>Customer email<input name="customer_email" type="email" value="{_esc(account.owner)}"></label>
      <label>Trial days<input name="trial_days" type="number" min="1" max="365"></label>
      <button type="submit">Create Checkout</button>
    </form>
    <h2>Projects</h2>
    {_table(["ID", "Name", "Slug", "Updated"], project_rows)}
    <h2>Members</h2>
    {_table(["Email", "Role", "Name", "Updated"], member_rows)}
    <h2>Recent Issues</h2>
    {_table(["Source", "Class", "Domain/Job", "Error", "Recommendation"], issue_rows)}
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


@app.get(
    "/dashboard/extractions/{extraction_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(require_admin_access)],
)
def extraction_dashboard(
    extraction_id: str, request: Request, store: JobStore = Depends(get_job_store)
) -> HTMLResponse:
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
        ["Failure Class", _esc(record.failure_class.value if record.failure_class else None)],
        ["Recommendation", _esc(record.recommendation)],
        ["Created", _esc(record.created_at)],
    ]
    product_rows = (
        [
            ["Name", _esc(product.get("name"))],
            ["Brand", _esc(product.get("brand"))],
            ["Availability", _esc(product.get("availability"))],
            ["Price", _esc((product.get("price") or {}).get("amount"))],
            ["Currency", _esc((product.get("price") or {}).get("currency"))],
        ]
        if product
        else []
    )
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


@app.get("/portal", response_class=HTMLResponse)
def customer_portal(request: Request, store: JobStore = Depends(get_job_store)) -> HTMLResponse:
    key = _require_portal_key(request, store)
    token_query = _portal_key_query(request)
    account_id = key.account_id
    project_id = key.project_id
    jobs = store.list_jobs(limit=25, account_id=account_id, project_id=project_id)
    runs = store.list_runs(limit=25, account_id=account_id, project_id=project_id)
    extractions = store.list_extractions(limit=25, account_id=account_id, project_id=project_id)
    usage = store.usage_summary(account_id=account_id, project_id=project_id)
    billing = billing_usage_endpoint(key)
    monitoring = _build_monitoring_overview(store, key, limit=100)
    issues = _recent_issues(runs, extractions, limit=20)
    target_rows = [
        [
            _esc(target.url),
            f"<a href='{_portal_href(f'/portal/jobs/{_esc(target.job_id)}', token_query)}'>{_esc(target.job_name)}</a>",
            _esc(target.job_status),
            _esc("yes" if target.render else "no"),
            _esc(", ".join(target.tags)),
            _esc(target.next_run_at),
            f"<span class='danger'>{_esc(target.last_error)}</span>" if target.last_error else "",
        ]
        for target in monitoring.targets
    ]
    job_rows = [
        [
            f"<a href='{_portal_href(f'/portal/jobs/{_esc(job.id)}', token_query)}'><code>{_esc(job.id)}</code></a>",
            _esc(job.name),
            _esc(job.status.value),
            _esc(job.schedule_kind.value),
            _esc(job.interval_minutes),
            _esc(len(job.config.targets)),
            _esc(len(job.config.rules)),
            _esc(job.next_run_at),
        ]
        for job in jobs[:10]
    ]
    run_rows = [
        [
            f"<a href='{_portal_href(f'/portal/runs/{_esc(run.id)}', token_query)}'><code>{_esc(run.id)}</code></a>",
            f"<a href='{_portal_href(f'/portal/jobs/{_esc(run.job_id)}', token_query)}'><code>{_esc(run.job_id)}</code></a>",
            _esc(run.status.value),
            _esc(run.event_count),
            _esc(run.delivery_count),
            _esc(run.warning_count),
            _esc(run.duration_ms),
            _esc(run.created_at),
        ]
        for run in runs[:10]
    ]
    extraction_rows = [
        [
            f"<a href='{_portal_href(f'/portal/extractions/{_esc(record.id)}', token_query)}'><code>{_esc(record.id)}</code></a>",
            _esc(record.kind.value),
            _esc(record.status.value),
            _esc(record.url),
            _esc(record.confidence),
            _esc(record.product_count),
            _esc(record.created_at),
        ]
        for record in extractions[:10]
    ]
    usage_rows = [[_esc(item.metric.value), _esc(item.quantity)] for item in usage.items]
    billing_rows = [
        [
            _esc(item.metric.value),
            _esc(item.used),
            _esc("unlimited" if item.limit is None else item.limit),
            _esc("unlimited" if item.remaining is None else item.remaining),
        ]
        for item in billing.items
    ]
    export_rows = [
        ["Jobs", f"<a href='{_portal_href('/portal/export/jobs', token_query)}'>JSON</a>"],
        ["Runs", f"<a href='{_portal_href('/portal/export/runs', token_query)}'>JSON</a>"],
        [
            "Extractions",
            f"<a href='{_portal_href('/portal/export/extractions', token_query)}'>JSON</a>",
        ],
        ["Usage events", f"<a href='{_portal_href('/portal/export/usage', token_query)}'>JSON</a>"],
    ]
    issue_rows = [
        [
            _esc(issue.get("source")),
            _esc(issue.get("failure_class")),
            _esc(issue.get("domain") or issue.get("job_id")),
            f"<span class='danger'>{_esc(issue.get('error'))}</span>",
            _esc(issue.get("recommendation")),
        ]
        for issue in issues[:10]
    ]
    content = f"""
    <h1>Project Overview</h1>
    <section class="grid">
      <div class="metric">Monitored targets<strong>{monitoring.target_count}</strong></div>
      <div class="metric">Active jobs<strong>{monitoring.active_job_count}</strong></div>
      <div class="metric">Recent runs<strong>{len(runs)}</strong></div>
      <div class="metric">Failed runs<strong>{monitoring.failed_run_count}</strong></div>
      <div class="metric">Extractions<strong>{len(extractions)}</strong></div>
      <div class="metric">Usage events<strong>{usage.total_quantity}</strong></div>
      <div class="metric">Alert rules<strong>{monitoring.rule_count}</strong></div>
      <div class="metric">Rendered targets<strong>{monitoring.render_target_count}</strong></div>
      <div class="metric">Recent issues<strong>{len(issues)}</strong></div>
    </section>
    <section class="panel">
      <strong>Account</strong> <code>{_esc(account_id)}</code>
      <span class="muted">Project</span> <code>{_esc(project_id)}</code>
      <span class="muted">Plan</span> <code>{_esc(key.billing_plan.value)}</code>
    </section>
    <h2>Monitored Products</h2>
    {_table(["URL", "Job", "Status", "Render", "Tags", "Next Run", "Issue"], target_rows)}
    <h2>Recent Issues</h2>
    {_table(["Source", "Class", "Domain/Job", "Error", "Recommendation"], issue_rows)}
    <h2>Monitoring Jobs</h2>
    {_table(["ID", "Name", "Status", "Schedule", "Interval", "Targets", "Rules", "Next Run"], job_rows)}
    <h2>Recent Runs</h2>
    {_table(["ID", "Job", "Status", "Events", "Deliveries", "Warnings", "Duration ms", "Created"], run_rows)}
    <h2>Recent Extractions</h2>
    {_table(["ID", "Kind", "Status", "URL", "Confidence", "Products", "Created"], extraction_rows)}
    <h2>Exports</h2>
    {_table(["Dataset", "Download"], export_rows)}
    <h2>Usage</h2>
    {_table(["Metric", "Quantity"], usage_rows)}
    <h2>Quota</h2>
    {_table(["Metric", "Used", "Limit", "Remaining"], billing_rows)}
    """
    return HTMLResponse(_portal_shell("Customer Portal", content, token_query=token_query))


@app.get("/portal/jobs/{job_id}", response_class=HTMLResponse)
def customer_portal_job(
    job_id: str, request: Request, store: JobStore = Depends(get_job_store)
) -> HTMLResponse:
    key = _require_portal_key(request, store)
    token_query = _portal_key_query(request)
    job = store.get_job(job_id, account_id=key.account_id, project_id=key.project_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    runs = store.list_runs(
        job_id=job.id, limit=25, account_id=key.account_id, project_id=key.project_id
    )
    target_rows = [
        [
            _esc(target.url),
            _esc(getattr(target, "name", None)),
            _esc("yes" if target.render or job.config.render else "no"),
            _esc(", ".join(target.tags)),
        ]
        for target in job.config.targets
    ]
    rule_rows = [
        [
            _esc(rule.name),
            _esc(rule.condition.value if hasattr(rule.condition, "value") else rule.condition),
            _esc(rule.threshold),
        ]
        for rule in job.config.rules
    ]
    run_rows = [
        [
            f"<a href='{_portal_href(f'/portal/runs/{_esc(run.id)}', token_query)}'><code>{_esc(run.id)}</code></a>",
            _esc(run.status.value),
            _esc(run.event_count),
            _esc(run.delivery_count),
            _esc(run.warning_count),
            _esc(run.duration_ms),
            _esc(run.created_at),
        ]
        for run in runs
    ]
    failure_class = classify_failure(job.last_error) if job.last_error else None
    rows = [
        ["Name", _esc(job.name)],
        ["Status", _esc(job.status.value)],
        ["Schedule", _esc(job.schedule_kind.value)],
        ["Interval minutes", _esc(job.interval_minutes)],
        ["Next run", _esc(job.next_run_at)],
        ["Last run", _esc(job.last_run_at)],
        [
            "Last error",
            f"<span class='danger'>{_esc(job.last_error)}</span>" if job.last_error else "",
        ],
        [
            "Last failure class",
            _esc(failure_class.value if failure_class else None),
        ],
        ["Recommendation", _esc(recommendation_for_failure(failure_class))],
        ["Tags", _esc(", ".join(job.tags))],
        ["Retries", _esc(job.max_retries)],
        ["Retry backoff seconds", _esc(job.retry_backoff_seconds)],
    ]
    content = f"""
    <p><a href="{_portal_href("/portal", token_query)}">Overview</a></p>
    <h1>Monitoring Job</h1>
    {_table(["Field", "Value"], rows)}
    <h2>Targets</h2>
    {_table(["URL", "Name", "Render", "Tags"], target_rows)}
    <h2>Alert Rules</h2>
    {_table(["Name", "Condition", "Threshold"], rule_rows)}
    <h2>Recent Runs</h2>
    {_table(["ID", "Status", "Events", "Deliveries", "Warnings", "Duration ms", "Created"], run_rows)}
    """
    return HTMLResponse(_portal_shell(job.name, content, token_query=token_query))


@app.get("/portal/runs/{run_id}", response_class=HTMLResponse)
def customer_portal_run(
    run_id: str, request: Request, store: JobStore = Depends(get_job_store)
) -> HTMLResponse:
    key = _require_portal_key(request, store)
    token_query = _portal_key_query(request)
    run = store.get_run(run_id, account_id=key.account_id, project_id=key.project_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")
    rows = [
        ["ID", f"<code>{_esc(run.id)}</code>"],
        [
            "Job",
            f"<a href='{_portal_href(f'/portal/jobs/{_esc(run.job_id)}', token_query)}'><code>{_esc(run.job_id)}</code></a>",
        ],
        ["Status", _esc(run.status.value)],
        ["Attempt", _esc(run.attempt)],
        ["Events", _esc(run.event_count)],
        ["Deliveries", _esc(run.delivery_count)],
        ["Warnings", _esc(run.warning_count)],
        ["Duration ms", _esc(run.duration_ms)],
        ["Started", _esc(run.started_at)],
        ["Finished", _esc(run.finished_at)],
        ["Created", _esc(run.created_at)],
        ["Error", f"<span class='danger'>{_esc(run.error)}</span>" if run.error else ""],
        ["Failure Class", _esc(run.failure_class.value if run.failure_class else None)],
        ["Recommendation", _esc(run.recommendation)],
    ]
    content = f"""
    <p><a href="{_portal_href("/portal", token_query)}">Overview</a></p>
    <h1>Job Run</h1>
    {_table(["Field", "Value"], rows)}
    <h2>Result</h2>
    {_pre_json(run.result or {})}
    """
    return HTMLResponse(_portal_shell("Job Run", content, token_query=token_query))


@app.get("/portal/extractions/{extraction_id}", response_class=HTMLResponse)
def customer_portal_extraction(
    extraction_id: str, request: Request, store: JobStore = Depends(get_job_store)
) -> HTMLResponse:
    key = _require_portal_key(request, store)
    token_query = _portal_key_query(request)
    record = store.get_extraction(
        extraction_id, account_id=key.account_id, project_id=key.project_id
    )
    if not record:
        raise HTTPException(status_code=404, detail="Extraction not found.")
    product = (record.payload or {}).get("product", {}) if record.payload else {}
    rows = [
        ["ID", f"<code>{_esc(record.id)}</code>"],
        ["Kind", _esc(record.kind.value)],
        ["Status", _esc(record.status.value)],
        ["URL", _esc(record.url)],
        ["Confidence", _esc(record.confidence)],
        ["Product count", _esc(record.product_count)],
        ["Created", _esc(record.created_at)],
        ["Error", f"<span class='danger'>{_esc(record.error)}</span>" if record.error else ""],
        ["Failure Class", _esc(record.failure_class.value if record.failure_class else None)],
        ["Recommendation", _esc(record.recommendation)],
    ]
    product_rows = (
        [
            ["Name", _esc(product.get("name"))],
            ["Brand", _esc(product.get("brand"))],
            ["Availability", _esc(product.get("availability"))],
            ["Price", _esc((product.get("price") or {}).get("amount"))],
            ["Currency", _esc((product.get("price") or {}).get("currency"))],
        ]
        if product
        else []
    )
    content = f"""
    <p><a href="{_portal_href("/portal", token_query)}">Overview</a></p>
    <h1>Extraction</h1>
    {_table(["Field", "Value"], rows)}
    <h2>Product Summary</h2>
    {_table(["Field", "Value"], product_rows)}
    <h2>Payload</h2>
    {_pre_json(record.payload or {})}
    """
    return HTMLResponse(_portal_shell("Extraction", content, token_query=token_query))


@app.get("/portal/export/{resource}")
def customer_portal_export(
    resource: str, request: Request, store: JobStore = Depends(get_job_store)
) -> JSONResponse:
    key = _require_portal_key(request, store)
    account_id = key.account_id
    project_id = key.project_id
    if resource == "jobs":
        payload = [
            job.model_dump(mode="json", exclude_none=True)
            for job in store.list_jobs(limit=1000, account_id=account_id, project_id=project_id)
        ]
    elif resource == "runs":
        payload = [
            run.model_dump(mode="json", exclude_none=True)
            for run in store.list_runs(limit=1000, account_id=account_id, project_id=project_id)
        ]
    elif resource == "extractions":
        payload = [
            record.model_dump(mode="json", exclude_none=True)
            for record in store.list_extractions(
                limit=1000, account_id=account_id, project_id=project_id
            )
        ]
    elif resource == "usage":
        payload = [
            event.model_dump(mode="json", exclude_none=True)
            for event in store.list_usage_events(
                limit=1000, account_id=account_id, project_id=project_id
            )
        ]
    else:
        raise HTTPException(status_code=404, detail="Export not found.")
    return JSONResponse(
        content={
            "account_id": account_id,
            "project_id": project_id,
            "resource": resource,
            "items": payload,
        },
        headers={"Content-Disposition": f'attachment; filename="commercelens-{resource}.json"'},
    )


@app.post("/v1/extract/product", response_model=ProductExtractionResult)
def extract_product_endpoint(
    request: ProductExtractionRequest,
    store: JobStore = Depends(get_job_store),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> ProductExtractionResult:
    url = str(request.url) if request.url else None
    _meter(key, UsageMetric.product_extract, scope="extract:write")
    domain = require_domain_quota(store, key, url)
    if not request.url and not request.html:
        _record_extraction(
            store,
            key,
            ExtractionKind.product,
            ExtractionStatus.failed,
            error="Provide either 'url' or 'html'.",
        )
        raise HTTPException(status_code=400, detail="Provide either 'url' or 'html'.")
    if request.llm_fallback:
        _record_extraction(
            store,
            key,
            ExtractionKind.product,
            ExtractionStatus.failed,
            url=str(request.url) if request.url else None,
            error="LLM fallback is planned for a later phase.",
        )
        raise HTTPException(
            status_code=501,
            detail="LLM fallback is planned for a later phase. Use llm_fallback=false for now.",
        )
    try:
        if request.render:
            if not url:
                _record_extraction(
                    store,
                    key,
                    ExtractionKind.product,
                    ExtractionStatus.failed,
                    error="render=true requires a URL.",
                    metadata={"render": request.render},
                )
                raise HTTPException(status_code=400, detail="render=true requires a URL.")
            result = extract_product(
                url,
                render=True,
                screenshot_path=request.screenshot_path,
                html_snapshot_path=request.html_snapshot_path,
            )
        else:
            html = request.html or (fetch_html(url) if url else None)
            assert html is not None
            result = extract_product_from_html(html, url=url)
        payload = result.model_dump(mode="json", exclude_none=True)
        _record_extraction(
            store,
            key,
            ExtractionKind.product,
            ExtractionStatus.succeeded,
            url=result.url or url,
            confidence=result.confidence,
            payload=payload,
            metadata={"render": request.render, "domain": domain},
        )
        _record_usage(
            store,
            key,
            UsageMetric.product_extract,
            route="/v1/extract/product",
            metadata={"render": request.render, "domain": domain},
        )
        return result
    except FetchError as exc:
        _record_extraction(
            store,
            key,
            ExtractionKind.product,
            ExtractionStatus.failed,
            url=url,
            error=str(exc),
            metadata={"render": request.render},
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RenderError as exc:
        _record_extraction(
            store,
            key,
            ExtractionKind.product,
            ExtractionStatus.failed,
            url=url,
            error=str(exc),
            metadata={"render": request.render},
        )
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@app.post("/v1/extract/listing", response_model=ListingExtractionResult)
def extract_listing_endpoint(
    request: ListingExtractionRequest,
    store: JobStore = Depends(get_job_store),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> ListingExtractionResult:
    url = str(request.url) if request.url else None
    _meter(key, UsageMetric.listing_extract, scope="extract:write")
    domain = require_domain_quota(store, key, url)
    if not request.url and not request.html:
        _record_extraction(
            store,
            key,
            ExtractionKind.listing,
            ExtractionStatus.failed,
            error="Provide either 'url' or 'html'.",
        )
        raise HTTPException(status_code=400, detail="Provide either 'url' or 'html'.")
    try:
        if request.render:
            if not url:
                _record_extraction(
                    store,
                    key,
                    ExtractionKind.listing,
                    ExtractionStatus.failed,
                    error="render=true requires a URL.",
                    metadata={"render": request.render},
                )
                raise HTTPException(status_code=400, detail="render=true requires a URL.")
            result = extract_listing(
                url,
                render=True,
                screenshot_path=request.screenshot_path,
                html_snapshot_path=request.html_snapshot_path,
            )
        else:
            html = request.html or (fetch_html(url) if url else None)
            assert html is not None
            result = extract_listing_from_html(html, url=url)
        payload = result.model_dump(mode="json", exclude_none=True)
        _record_extraction(
            store,
            key,
            ExtractionKind.listing,
            ExtractionStatus.succeeded,
            url=result.url or url,
            confidence=result.confidence,
            product_count=result.product_count,
            payload=payload,
            metadata={"render": request.render, "domain": domain},
        )
        _record_usage(
            store,
            key,
            UsageMetric.listing_extract,
            route="/v1/extract/listing",
            metadata={"products": len(result.products), "render": request.render, "domain": domain},
        )
        return result
    except FetchError as exc:
        _record_extraction(
            store,
            key,
            ExtractionKind.listing,
            ExtractionStatus.failed,
            url=url,
            error=str(exc),
            metadata={"render": request.render},
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RenderError as exc:
        _record_extraction(
            store,
            key,
            ExtractionKind.listing,
            ExtractionStatus.failed,
            url=url,
            error=str(exc),
            metadata={"render": request.render},
        )
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
def crawl_catalog_endpoint(
    request: CatalogCrawlRequest,
    store: JobStore = Depends(get_job_store),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> CatalogCrawlResult:
    _meter(key, UsageMetric.catalog_crawl, scope="crawl:write")
    domain = require_domain_quota(store, key, str(request.url))
    try:
        result = crawl_catalog(
            start_url=str(request.url),
            max_pages=request.max_pages,
            follow_next_pages=request.follow_next_pages,
            render=request.render,
            debug_dir=request.debug_dir,
        )
        _record_usage(
            store,
            key,
            UsageMetric.catalog_crawl,
            route="/v1/crawl/catalog",
            metadata={
                "pages": result.pages_crawled,
                "products": len(result.products),
                "domain": domain,
            },
        )
        return result
    except FetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RenderError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@app.post("/v1/monitor/product", response_model=MonitorResult)
def monitor_product_endpoint(
    request: MonitorProductRequest,
    store: JobStore = Depends(get_job_store),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> MonitorResult:
    _meter(key, UsageMetric.monitor_run, scope="monitor:write")
    domain = require_domain_quota(store, key, str(request.url))
    try:
        result = monitor_product(str(request.url), db_path=request.db_path, render=request.render)
        _record_usage(
            store,
            key,
            UsageMetric.monitor_run,
            route="/v1/monitor/product",
            metadata={"render": request.render, "changed": result.has_change, "domain": domain},
        )
        return result
    except FetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RenderError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@app.post("/v1/monitor/batch", response_model=BatchMonitorResult)
def monitor_batch_endpoint(
    request: MonitorBatchRequest,
    store: JobStore = Depends(get_job_store),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> BatchMonitorResult:
    _meter(key, UsageMetric.monitor_run, quantity=max(1, len(request.urls)), scope="monitor:write")
    domain_counts = Counter(url_domain(str(url)) for url in request.urls)
    for domain, count in domain_counts.items():
        if domain:
            require_domain_quota(store, key, f"https://{domain}", quantity=count)
    result = monitor_products(
        [str(url) for url in request.urls], db_path=request.db_path, render=request.render
    )
    for domain, count in domain_counts.items():
        _record_usage(
            store,
            key,
            UsageMetric.monitor_run,
            quantity=count,
            route="/v1/monitor/batch",
            metadata={"urls": len(request.urls), "domain": domain},
        )
    return result


@app.post("/v1/monitor/history", response_model=list[ProductSnapshot])
def price_history_endpoint(request: PriceHistoryRequest) -> list[ProductSnapshot]:
    if not request.product_key and not request.url:
        raise HTTPException(status_code=400, detail="Provide either 'product_key' or 'url'.")
    price_store = PriceSnapshotStore(request.db_path)
    return (
        price_store.history(request.product_key, limit=request.limit)
        if request.product_key
        else price_store.history_for_url(str(request.url), limit=request.limit)
    )


@app.post("/v1/alerts/run", response_model=MonitorRunResult)
def run_alert_config_endpoint(
    request: RunMonitorConfigRequest,
    store: JobStore = Depends(get_job_store),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> MonitorRunResult:
    _meter(key, UsageMetric.monitor_run, scope="monitor:write")
    result = run_monitor_config(request.config, dry_run=request.dry_run, deliver=request.deliver)
    _record_usage(
        store,
        key,
        UsageMetric.monitor_run,
        route="/v1/alerts/run",
        metadata={"events": len(result.events), "warnings": len(result.warnings)},
    )
    return result


@app.post("/v1/alerts/run-file", response_model=MonitorRunResult)
def run_alert_config_file_endpoint(request: RunMonitorConfigFileRequest) -> MonitorRunResult:
    return run_monitor_config_file(request.path, dry_run=request.dry_run, deliver=request.deliver)


@app.post("/v1/jobs", response_model=MonitoringJob)
def create_job_endpoint(
    request: MonitoringJobCreate,
    store: JobStore = Depends(get_job_store),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> MonitoringJob:
    _meter(key, UsageMetric.api_request, scope="jobs:write")
    if key:
        request.account_id = request.account_id or key.account_id
        request.project_id = request.project_id or key.project_id
        request.owner = request.owner or key.owner
    return store.create_job(request)


@app.get("/v1/jobs", response_model=list[MonitoringJob])
def list_jobs_endpoint(
    status: JobStatus | None = None,
    limit: int = 100,
    store: JobStore = Depends(get_job_store),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> list[MonitoringJob]:
    require_scope(key, "jobs:read")
    return store.list_jobs(
        status=status,
        limit=limit,
        account_id=key.account_id if key else None,
        project_id=key.project_id if key else None,
    )


@app.get("/v1/jobs/{job_id}", response_model=MonitoringJob)
def get_job_endpoint(
    job_id: str,
    store: JobStore = Depends(get_job_store),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> MonitoringJob:
    require_scope(key, "jobs:read")
    job = store.get_job(
        job_id,
        account_id=key.account_id if key else None,
        project_id=key.project_id if key else None,
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


@app.patch("/v1/jobs/{job_id}", response_model=MonitoringJob)
def update_job_endpoint(
    job_id: str,
    request: MonitoringJobUpdate,
    store: JobStore = Depends(get_job_store),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> MonitoringJob:
    require_scope(key, "jobs:write")
    job = store.update_job(
        job_id,
        request,
        account_id=key.account_id if key else None,
        project_id=key.project_id if key else None,
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


@app.delete("/v1/jobs/{job_id}")
def delete_job_endpoint(
    job_id: str,
    store: JobStore = Depends(get_job_store),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> dict[str, bool]:
    require_scope(key, "jobs:write")
    deleted = store.delete_job(
        job_id,
        account_id=key.account_id if key else None,
        project_id=key.project_id if key else None,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"deleted": True}


@app.post("/v1/jobs/{job_id}/run", response_model=JobRun)
def run_job_endpoint(
    job_id: str,
    dry_run: bool = False,
    deliver: bool = True,
    store: JobStore = Depends(get_job_store),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> JobRun:
    _meter(key, UsageMetric.job_run, scope="jobs:write")
    job = store.get_job(
        job_id,
        account_id=key.account_id if key else None,
        project_id=key.project_id if key else None,
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return run_job_now(store, job.id, dry_run=dry_run, deliver=deliver)


@app.get("/v1/runs", response_model=list[JobRun])
def list_runs_endpoint(
    job_id: str | None = None,
    limit: int = 100,
    store: JobStore = Depends(get_job_store),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> list[JobRun]:
    require_scope(key, "runs:read")
    return store.list_runs(
        job_id=job_id,
        limit=limit,
        account_id=key.account_id if key else None,
        project_id=key.project_id if key else None,
    )


@app.get("/v1/runs/{run_id}", response_model=JobRun)
def get_run_endpoint(
    run_id: str,
    store: JobStore = Depends(get_job_store),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> JobRun:
    require_scope(key, "runs:read")
    run = store.get_run(
        run_id,
        account_id=key.account_id if key else None,
        project_id=key.project_id if key else None,
    )
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")
    return run


@app.post("/v1/worker/tick", response_model=WorkerTickResult)
def worker_tick_endpoint(
    limit: int = 25,
    dry_run: bool = False,
    deliver: bool = True,
    domain_concurrency: int | None = None,
    worker_concurrency: int | None = None,
    store: JobStore = Depends(get_job_store),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> WorkerTickResult:
    require_scope(key, "worker:write")
    return MonitoringWorker(store=store).tick(
        limit=limit,
        dry_run=dry_run,
        deliver=deliver,
        domain_concurrency=domain_concurrency,
        worker_concurrency=worker_concurrency,
    )


@app.post(
    "/v1/api-keys", response_model=ApiKeyCreateResult, dependencies=[Depends(require_admin_token)]
)
def create_api_key_endpoint(
    request: ApiKeyCreate, store: JobStore = Depends(get_job_store)
) -> ApiKeyCreateResult:
    return store.create_api_key(request)


@app.get("/v1/usage/events", response_model=list[UsageEvent])
def list_usage_events_endpoint(
    metric: UsageMetric | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 100,
    store: JobStore = Depends(get_job_store),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> list[UsageEvent]:
    require_scope(key, "usage:read")
    return store.list_usage_events(
        account_id=key.account_id if key else None,
        project_id=key.project_id if key else None,
        metric=metric,
        since=since,
        until=until,
        limit=limit,
    )


@app.get("/v1/usage/summary", response_model=UsageSummary)
def usage_summary_endpoint(
    since: str | None = None,
    until: str | None = None,
    store: JobStore = Depends(get_job_store),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> UsageSummary:
    require_scope(key, "usage:read")
    return store.usage_summary(
        account_id=key.account_id if key else None,
        project_id=key.project_id if key else None,
        since=since,
        until=until,
    )


@app.get("/v1/billing/usage", response_model=BillingUsageSnapshot)
def billing_usage_endpoint(
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> BillingUsageSnapshot:
    if key is None:
        raise HTTPException(
            status_code=400,
            detail="Billing usage requires API key auth. Set COMMERCELENS_REQUIRE_API_KEY=true.",
        )
    require_scope(key, "usage:read")
    decisions = [quota_decision(key, metric, 0) for metric in UsageMetric]
    return BillingUsageSnapshot(
        account_id=key.account_id,
        project_id=key.project_id,
        api_key_id=key.id,
        billing_plan=key.billing_plan,
        period_start=decisions[0].period_start,
        period_end=decisions[0].period_end,
        blocked=any(not decision.allowed for decision in decisions),
        items=[
            BillingUsageItem(
                metric=decision.metric,
                used=decision.used,
                limit=decision.limit,
                remaining=decision.remaining,
            )
            for decision in decisions
        ],
    )


@app.post(
    "/v1/billing/stripe/checkout-session",
    response_model=StripeCheckoutResponse,
    dependencies=[Depends(require_admin_token)],
)
def stripe_checkout_session_endpoint(
    request: StripeCheckoutRequest, store: JobStore = Depends(get_job_store)
) -> StripeCheckoutResponse:
    account = store.get_account(request.account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")
    secret_key = os.getenv("STRIPE_SECRET_KEY")
    if not secret_key:
        raise HTTPException(status_code=503, detail="STRIPE_SECRET_KEY is not configured.")
    try:
        session = create_checkout_session(
            secret_key=secret_key,
            price_id=request.price_id,
            success_url=request.success_url,
            cancel_url=request.cancel_url,
            account_id=request.account_id,
            billing_plan=request.billing_plan,
            customer_email=request.customer_email or account.owner,
            trial_days=request.trial_days,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Stripe checkout session failed: {exc}"
        ) from exc
    session_id = str(session.get("id") or "")
    session_url = str(session.get("url") or "")
    if not session_id or not session_url:
        raise HTTPException(
            status_code=502, detail="Stripe checkout session response did not include id and url."
        )
    account.metadata["stripe_checkout_session_id"] = session_id
    account.metadata["stripe_checkout_plan"] = request.billing_plan.value
    store.save_account(account)
    return StripeCheckoutResponse(
        id=session_id,
        url=session_url,
        account_id=request.account_id,
        billing_plan=request.billing_plan,
    )


@app.get("/v1/monitoring/overview", response_model=MonitoringOverview)
def monitoring_overview_endpoint(
    limit: int = 100,
    store: JobStore = Depends(get_job_store),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> MonitoringOverview:
    require_scope(key, "jobs:read")
    require_scope(key, "runs:read")
    return _build_monitoring_overview(store, key, limit=limit)


@app.get("/v1/issues")
def issues_endpoint(
    limit: int = 50,
    store: JobStore = Depends(get_job_store),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> dict:
    require_scope(key, "runs:read")
    require_scope(key, "extractions:read")
    account_id = key.account_id if key else None
    project_id = key.project_id if key else None
    runs = store.list_runs(limit=limit, account_id=account_id, project_id=project_id)
    extractions = store.list_extractions(limit=limit, account_id=account_id, project_id=project_id)
    issues = _recent_issues(runs, extractions, limit=limit)
    return {
        "account_id": account_id,
        "project_id": project_id,
        "count": len(issues),
        "summary": [
            {"failure_class": row[0], "domain": row[1], "count": row[2]}
            for row in _failure_summary(issues)
        ],
        "issues": issues,
    }


@app.get("/v1/ops/failure-metrics", dependencies=[Depends(require_admin_access)])
def failure_metrics_endpoint(store: JobStore = Depends(get_job_store)) -> dict:
    runs = store.list_runs(limit=1000)
    extractions = store.list_extractions(limit=1000)
    issues = _recent_issues(runs, extractions, limit=1000)
    by_class: Counter[str] = Counter(
        str(issue.get("failure_class") or "unknown") for issue in issues
    )
    by_domain: Counter[str] = Counter(str(issue.get("domain") or "job-run") for issue in issues)
    return {
        "issue_count": len(issues),
        "by_failure_class": dict(by_class),
        "by_domain": dict(by_domain),
    }


@app.get("/v1/dashboard/summary", response_model=DashboardSummary)
def dashboard_summary_endpoint(
    limit: int = 25,
    store: JobStore = Depends(get_job_store),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> DashboardSummary:
    if key is None:
        raise HTTPException(
            status_code=400,
            detail="Dashboard summary requires API key auth. Set COMMERCELENS_REQUIRE_API_KEY=true.",
        )
    require_scope(key, "usage:read")
    account_id = key.account_id
    project_id = key.project_id
    jobs = store.list_jobs(limit=limit, account_id=account_id, project_id=project_id)
    runs = store.list_runs(limit=limit, account_id=account_id, project_id=project_id)
    extractions = store.list_extractions(limit=limit, account_id=account_id, project_id=project_id)
    usage = store.usage_summary(account_id=account_id, project_id=project_id)
    monitoring = _build_monitoring_overview(store, key, limit=limit)
    decisions = [quota_decision(key, metric, 0) for metric in UsageMetric]
    billing = BillingUsageSnapshot(
        account_id=key.account_id,
        project_id=key.project_id,
        api_key_id=key.id,
        billing_plan=key.billing_plan,
        period_start=decisions[0].period_start,
        period_end=decisions[0].period_end,
        blocked=any(not decision.allowed for decision in decisions),
        items=[
            BillingUsageItem(
                metric=decision.metric,
                used=decision.used,
                limit=decision.limit,
                remaining=decision.remaining,
            )
            for decision in decisions
        ],
    )
    return DashboardSummary(
        account_id=account_id,
        project_id=project_id,
        counts={
            "jobs": len(jobs),
            "active_jobs": sum(1 for job in jobs if job.status == JobStatus.active),
            "runs": len(runs),
            "failed_runs": sum(1 for run in runs if run.status.value == "failed"),
            "extractions": len(extractions),
            "failed_extractions": sum(
                1 for record in extractions if record.status == ExtractionStatus.failed
            ),
        },
        billing=billing,
        usage=usage,
        monitoring=monitoring,
        jobs=jobs,
        runs=runs,
        extractions=extractions,
    )


@app.post("/v1/billing/stripe/webhook")
async def stripe_webhook_endpoint(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
    store: JobStore = Depends(get_job_store),
) -> dict:
    secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(status_code=503, detail="STRIPE_WEBHOOK_SECRET is not configured.")
    if not stripe_signature:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header.")
    payload = await request.body()
    try:
        verify_stripe_signature(payload, stripe_signature, secret)
        event = parse_stripe_event(payload)
        if not str(event["type"]).startswith("customer.subscription."):
            return {"applied": False, "reason": "ignored_event_type", "type": event["type"]}
        return apply_subscription_event(store, event)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/records/normalize", response_model=DatasetLoadResult)
def normalize_records_endpoint(request: NormalizeRecordsRequest) -> DatasetLoadResult:
    return DatasetLoadResult(records=request.records)


@app.post("/v1/match/products", response_model=ProductMatchResult)
def match_products_endpoint(
    request: MatchProductsRequest,
    store: JobStore = Depends(get_job_store),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> ProductMatchResult:
    _meter(key, UsageMetric.match_request, scope="match:write")
    result = match_products(
        request.left, request.right, threshold=request.threshold, top_k=request.top_k
    )
    _record_usage(
        store,
        key,
        UsageMetric.match_request,
        route="/v1/match/products",
        metadata={
            "left": len(request.left),
            "right": len(request.right),
            "matches": len(result.matches),
        },
    )
    return result


@app.post("/v1/identity/graph", response_model=ProductIdentityGraph)
def product_identity_graph_endpoint(
    request: ProductIdentityGraphRequest,
    store: JobStore = Depends(get_job_store),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> ProductIdentityGraph:
    _meter(key, UsageMetric.match_request, scope="match:write")
    graph = build_identity_graph(request.records, threshold=request.threshold)
    _record_usage(
        store,
        key,
        UsageMetric.match_request,
        route="/v1/identity/graph",
        metadata={"records": len(request.records), "clusters": len(graph.clusters)},
    )
    return graph


@app.post("/v1/catalog/diff", response_model=CatalogDiffResult)
def catalog_diff_endpoint(
    request: CatalogDiffRequest,
    store: JobStore = Depends(get_job_store),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> CatalogDiffResult:
    _meter(key, UsageMetric.match_request, scope="match:write")
    result = diff_catalogs(request.before, request.after)
    _record_usage(
        store,
        key,
        UsageMetric.match_request,
        route="/v1/catalog/diff",
        metadata={
            "before": len(request.before),
            "after": len(request.after),
            "changes": result.total_changes,
        },
    )
    return result


@app.post("/v1/intelligence/price-summary", response_model=PriceIntelligenceSummary)
def price_summary_endpoint(
    request: PriceSummaryRequest,
    store: JobStore = Depends(get_job_store),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> PriceIntelligenceSummary:
    _meter(key, UsageMetric.match_request, scope="match:write")
    summary = summarize_prices(request.records)
    _record_usage(
        store,
        key,
        UsageMetric.match_request,
        route="/v1/intelligence/price-summary",
        metadata={"records": len(request.records), "priced": summary.priced_count},
    )
    return summary
