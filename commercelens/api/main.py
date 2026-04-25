from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException

from commercelens.alerts.runner import MonitorRunResult, run_monitor_config, run_monitor_config_file
from commercelens.api.auth import get_job_store, require_api_key
from commercelens.connectors.datasets import DatasetLoadResult
from commercelens.core.crawler import CatalogCrawlResult, crawl_catalog
from commercelens.core.fetcher import FetchError, fetch_html
from commercelens.core.monitor import BatchMonitorResult, MonitorResult, monitor_product, monitor_products
from commercelens.core.renderer import RenderError
from commercelens.extractors.listing import extract_listing, extract_listing_from_html
from commercelens.extractors.product import extract_product, extract_product_from_html
from commercelens.jobs.models import ApiKeyCreate, ApiKeyCreateResult, JobRun, JobStatus, MonitoringJob, MonitoringJobCreate, MonitoringJobUpdate, WorkerTickResult
from commercelens.jobs.store import JobStore
from commercelens.jobs.worker import MonitoringWorker, run_job_now
from commercelens.matching.products import ProductMatchResult, match_products
from commercelens.schemas.alerts import RunMonitorConfigFileRequest, RunMonitorConfigRequest
from commercelens.schemas.connectors import MatchProductsRequest, NormalizeRecordsRequest
from commercelens.schemas.listing import CatalogCrawlRequest, ListingExtractionRequest, ListingExtractionResult
from commercelens.schemas.monitor import MonitorBatchRequest, MonitorProductRequest, PriceHistoryRequest
from commercelens.schemas.product import ProductExtractionRequest, ProductExtractionResult
from commercelens.storage.price_store import PriceSnapshotStore, ProductSnapshot

API_VERSION = "0.7.0"

app = FastAPI(
    title="CommerceLens API",
    description="Product, catalog, monitoring, alerting, matching, and price intelligence extraction for developers.",
    version=API_VERSION,
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "commercelens", "version": API_VERSION}


@app.post("/v1/extract/product", response_model=ProductExtractionResult)
def extract_product_endpoint(request: ProductExtractionRequest) -> ProductExtractionResult:
    if not request.url and not request.html:
        raise HTTPException(status_code=400, detail="Provide either 'url' or 'html'.")
    if request.llm_fallback:
        raise HTTPException(status_code=501, detail="LLM fallback is planned for a later phase. Use llm_fallback=false for now.")
    url = str(request.url) if request.url else None
    try:
        if request.render:
            if not url:
                raise HTTPException(status_code=400, detail="render=true requires a URL.")
            return extract_product(url, render=True, screenshot_path=request.screenshot_path, html_snapshot_path=request.html_snapshot_path)
        html = request.html
        if not html and url:
            html = fetch_html(url)
        assert html is not None
        return extract_product_from_html(html, url=url)
    except FetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RenderError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@app.post("/v1/extract/listing", response_model=ListingExtractionResult)
def extract_listing_endpoint(request: ListingExtractionRequest) -> ListingExtractionResult:
    if not request.url and not request.html:
        raise HTTPException(status_code=400, detail="Provide either 'url' or 'html'.")
    url = str(request.url) if request.url else None
    try:
        if request.render:
            if not url:
                raise HTTPException(status_code=400, detail="render=true requires a URL.")
            return extract_listing(url, render=True, screenshot_path=request.screenshot_path, html_snapshot_path=request.html_snapshot_path)
        html = request.html
        if not html and url:
            html = fetch_html(url)
        assert html is not None
        return extract_listing_from_html(html, url=url)
    except FetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RenderError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@app.post("/v1/crawl/catalog", response_model=CatalogCrawlResult)
def crawl_catalog_endpoint(request: CatalogCrawlRequest) -> CatalogCrawlResult:
    try:
        return crawl_catalog(start_url=str(request.url), max_pages=request.max_pages, follow_next_pages=request.follow_next_pages, render=request.render, debug_dir=request.debug_dir)
    except FetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RenderError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@app.post("/v1/monitor/product", response_model=MonitorResult)
def monitor_product_endpoint(request: MonitorProductRequest) -> MonitorResult:
    try:
        return monitor_product(str(request.url), db_path=request.db_path, render=request.render)
    except FetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RenderError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@app.post("/v1/monitor/batch", response_model=BatchMonitorResult)
def monitor_batch_endpoint(request: MonitorBatchRequest) -> BatchMonitorResult:
    return monitor_products([str(url) for url in request.urls], db_path=request.db_path, render=request.render)


@app.post("/v1/monitor/history", response_model=list[ProductSnapshot])
def price_history_endpoint(request: PriceHistoryRequest) -> list[ProductSnapshot]:
    if not request.product_key and not request.url:
        raise HTTPException(status_code=400, detail="Provide either 'product_key' or 'url'.")
    store = PriceSnapshotStore(request.db_path)
    if request.product_key:
        return store.history(request.product_key, limit=request.limit)
    assert request.url is not None
    return store.history_for_url(str(request.url), limit=request.limit)


@app.post("/v1/alerts/run", response_model=MonitorRunResult)
def run_alert_config_endpoint(request: RunMonitorConfigRequest) -> MonitorRunResult:
    return run_monitor_config(request.config, dry_run=request.dry_run, deliver=request.deliver)


@app.post("/v1/alerts/run-file", response_model=MonitorRunResult)
def run_alert_config_file_endpoint(request: RunMonitorConfigFileRequest) -> MonitorRunResult:
    return run_monitor_config_file(request.path, dry_run=request.dry_run, deliver=request.deliver)


@app.post("/v1/jobs", response_model=MonitoringJob, dependencies=[Depends(require_api_key)])
def create_job_endpoint(request: MonitoringJobCreate, store: JobStore = Depends(get_job_store)) -> MonitoringJob:
    return store.create_job(request)


@app.get("/v1/jobs", response_model=list[MonitoringJob], dependencies=[Depends(require_api_key)])
def list_jobs_endpoint(status: JobStatus | None = None, limit: int = 100, store: JobStore = Depends(get_job_store)) -> list[MonitoringJob]:
    return store.list_jobs(status=status, limit=limit)


@app.get("/v1/jobs/{job_id}", response_model=MonitoringJob, dependencies=[Depends(require_api_key)])
def get_job_endpoint(job_id: str, store: JobStore = Depends(get_job_store)) -> MonitoringJob:
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


@app.patch("/v1/jobs/{job_id}", response_model=MonitoringJob, dependencies=[Depends(require_api_key)])
def update_job_endpoint(job_id: str, request: MonitoringJobUpdate, store: JobStore = Depends(get_job_store)) -> MonitoringJob:
    job = store.update_job(job_id, request)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


@app.delete("/v1/jobs/{job_id}", dependencies=[Depends(require_api_key)])
def delete_job_endpoint(job_id: str, store: JobStore = Depends(get_job_store)) -> dict[str, bool]:
    deleted = store.delete_job(job_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"deleted": True}


@app.post("/v1/jobs/{job_id}/run", response_model=JobRun, dependencies=[Depends(require_api_key)])
def run_job_endpoint(job_id: str, dry_run: bool = False, deliver: bool = True, store: JobStore = Depends(get_job_store)) -> JobRun:
    try:
        return run_job_now(store, job_id, dry_run=dry_run, deliver=deliver)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/v1/runs", response_model=list[JobRun], dependencies=[Depends(require_api_key)])
def list_runs_endpoint(job_id: str | None = None, limit: int = 100, store: JobStore = Depends(get_job_store)) -> list[JobRun]:
    return store.list_runs(job_id=job_id, limit=limit)


@app.get("/v1/runs/{run_id}", response_model=JobRun, dependencies=[Depends(require_api_key)])
def get_run_endpoint(run_id: str, store: JobStore = Depends(get_job_store)) -> JobRun:
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")
    return run


@app.post("/v1/worker/tick", response_model=WorkerTickResult, dependencies=[Depends(require_api_key)])
def worker_tick_endpoint(limit: int = 25, dry_run: bool = False, deliver: bool = True, store: JobStore = Depends(get_job_store)) -> WorkerTickResult:
    return MonitoringWorker(store=store).tick(limit=limit, dry_run=dry_run, deliver=deliver)


@app.post("/v1/api-keys", response_model=ApiKeyCreateResult)
def create_api_key_endpoint(request: ApiKeyCreate, store: JobStore = Depends(get_job_store)) -> ApiKeyCreateResult:
    return store.create_api_key(request)


@app.post("/v1/records/normalize", response_model=DatasetLoadResult)
def normalize_records_endpoint(request: NormalizeRecordsRequest) -> DatasetLoadResult:
    return DatasetLoadResult(records=request.records)


@app.post("/v1/match/products", response_model=ProductMatchResult)
def match_products_endpoint(request: MatchProductsRequest) -> ProductMatchResult:
    return match_products(request.left, request.right, threshold=request.threshold, top_k=request.top_k)
