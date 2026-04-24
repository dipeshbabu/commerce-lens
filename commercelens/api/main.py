from __future__ import annotations

from fastapi import FastAPI, HTTPException

from commercelens.core.crawler import CatalogCrawlResult, crawl_catalog
from commercelens.core.fetcher import FetchError, fetch_html
from commercelens.extractors.listing import extract_listing_from_html
from commercelens.extractors.product import extract_product_from_html
from commercelens.schemas.listing import (
    CatalogCrawlRequest,
    ListingExtractionRequest,
    ListingExtractionResult,
)
from commercelens.schemas.product import ProductExtractionRequest, ProductExtractionResult

app = FastAPI(
    title="CommerceLens API",
    description="Product, catalog, and price intelligence extraction for developers.",
    version="0.2.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "commercelens", "version": "0.2.0"}


@app.post("/v1/extract/product", response_model=ProductExtractionResult)
def extract_product_endpoint(request: ProductExtractionRequest) -> ProductExtractionResult:
    if not request.url and not request.html:
        raise HTTPException(status_code=400, detail="Provide either 'url' or 'html'.")

    if request.render:
        raise HTTPException(
            status_code=501,
            detail="Browser rendering is planned for v0.3. Use render=false for now.",
        )

    if request.llm_fallback:
        raise HTTPException(
            status_code=501,
            detail="LLM fallback is planned for v0.5. Use llm_fallback=false for now.",
        )

    url = str(request.url) if request.url else None
    html = request.html

    if not html and url:
        try:
            html = fetch_html(url)
        except FetchError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    assert html is not None
    return extract_product_from_html(html, url=url)


@app.post("/v1/extract/listing", response_model=ListingExtractionResult)
def extract_listing_endpoint(request: ListingExtractionRequest) -> ListingExtractionResult:
    if not request.url and not request.html:
        raise HTTPException(status_code=400, detail="Provide either 'url' or 'html'.")

    if request.render:
        raise HTTPException(
            status_code=501,
            detail="Browser rendering is planned for v0.3. Use render=false for now.",
        )

    url = str(request.url) if request.url else None
    html = request.html

    if not html and url:
        try:
            html = fetch_html(url)
        except FetchError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    assert html is not None
    return extract_listing_from_html(html, url=url)


@app.post("/v1/crawl/catalog", response_model=CatalogCrawlResult)
def crawl_catalog_endpoint(request: CatalogCrawlRequest) -> CatalogCrawlResult:
    try:
        return crawl_catalog(
            start_url=str(request.url),
            max_pages=request.max_pages,
            follow_next_pages=request.follow_next_pages,
        )
    except FetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
