from __future__ import annotations

from collections import deque

from pydantic import BaseModel, Field

from commercelens.core.fetcher import FetchError, fetch_html
from commercelens.core.urls import normalize_url, same_domain
from commercelens.extractors.listing import extract_listing_from_html
from commercelens.schemas.listing import ListingExtractionResult, ListingProduct


class CatalogCrawlResult(BaseModel):
    start_url: str
    pages_crawled: int = 0
    products: list[ListingProduct] = Field(default_factory=list)
    listings: list[ListingExtractionResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def product_count(self) -> int:
        return len(self.products)


def crawl_catalog(
    start_url: str,
    max_pages: int = 5,
    follow_next_pages: bool = True,
    same_domain_only: bool = True,
) -> CatalogCrawlResult:
    normalized_start = normalize_url(start_url)
    queue: deque[str] = deque([normalized_start])
    visited: set[str] = set()
    seen_product_urls: set[str] = set()
    products: list[ListingProduct] = []
    listings: list[ListingExtractionResult] = []
    warnings: list[str] = []

    while queue and len(visited) < max_pages:
        current_url = queue.popleft()
        if current_url in visited:
            continue
        if same_domain_only and not same_domain(normalized_start, current_url):
            continue

        visited.add(current_url)

        try:
            html = fetch_html(current_url)
        except FetchError as exc:
            warnings.append(str(exc))
            continue

        listing = extract_listing_from_html(html, url=current_url)
        listings.append(listing)

        for item in listing.products:
            key = item.url or f"{item.name}:{item.position}:{current_url}"
            if key in seen_product_urls:
                continue
            seen_product_urls.add(key)
            products.append(item)

        if follow_next_pages and listing.next_page_url:
            next_url = normalize_url(listing.next_page_url, base_url=current_url)
            if next_url not in visited and next_url not in queue:
                queue.append(next_url)

    return CatalogCrawlResult(
        start_url=normalized_start,
        pages_crawled=len(visited),
        products=products,
        listings=listings,
        warnings=warnings,
    )
