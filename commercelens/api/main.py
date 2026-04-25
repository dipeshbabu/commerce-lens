from __future__ import annotations

from fastapi import FastAPI, HTTPException

from commercelens.core.crawler import CatalogCrawlResult, crawl_catalog
from commercelens.core.fetcher import FetchError, fetch_html
from commercelens.core.monitor import BatchMonitorResult, MonitorResult, monitor_product, monitor_products
from commercelens.core.renderer import RenderError
from commercelens.extractors.listing import extract_listing, extract_listing_from_html
from commercelens.extractors.product import extract_product, extract_product_from_html
from commercelens.schemas.listing import (
    CatalogCrawlRequest,
    ListingExtractionRequest,
    ListingExtractionResult,
)
from commercelens.schemas.monitor import MonitorBatchRequest, MonitorProductRequest, PriceHistoryRequest
from commercelens.schemas.product import ProductExtractionRequest, ProductExtractionResult
from commercelens.storage.price_store import PriceSnapshotStore, ProductSnapshot

app = FastAPI(
    title="CommerceLens API",
    description="Product, catalog, and price intelligence extraction for developers.",
    version="0.4.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "commercelens", "version": "0.4.0"}


@app.post("/v1/extract/product", response_model=ProductExtractionResult)
def extract_product_endpoint(request: ProductExtractionRequest) -> ProductExtractionResult:
    if not request.url and not request.html:
        raise HTTPException(status_code=400, detail="Provide either 'url' or 'html'.")

    if request.llm_fallback:
        raise HTTPException(
            status_code=501,
            detail="LLM fallback is planned for v0.5. Use llm_fallback=false for now.",
        )

    url = str(request.url) if request.url else None

    try:
        if request.render:
            if not url:
                raise HTTPException(status_code=400, detail="render=true requires a URL.")
            return extract_product(
                url,
                render=True,
                screenshot_path=request.screenshot_path,
                html_snapshot_path=request.html_snapshot_path,
            )

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
            return extract_listing(
                url,
                render=True,
                screenshot_path=request.screenshot_path,
                html_snapshot_path=request.html_snapshot_path,
            )

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
        return crawl_catalog(
            start_url=str(request.url),
            max_pages=request.max_pages,
            follow_next_pages=request.follow_next_pages,
            render=request.render,
            debug_dir=request.debug_dir,
        )
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
    return monitor_products(
        [str(url) for url in request.urls],
        db_path=request.db_path,
        render=request.render,
    )


@app.post("/v1/monitor/history", response_model=list[ProductSnapshot])
def price_history_endpoint(request: PriceHistoryRequest) -> list[ProductSnapshot]:
    if not request.product_key and not request.url:
        raise HTTPException(status_code=400, detail="Provide either 'product_key' or 'url'.")

    store = PriceSnapshotStore(request.db_path)
    if request.product_key:
        return store.history(request.product_key, limit=request.limit)
    assert request.url is not None
    return store.history_for_url(str(request.url), limit=request.limit)
