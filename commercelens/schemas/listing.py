from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl

from commercelens.schemas.product import Price


class ListingProduct(BaseModel):
    name: str | None = None
    url: str | None = None
    price: Price | None = None
    image_url: str | None = None
    availability: str | None = None
    position: int | None = None
    source_selector: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ListingExtractionResult(BaseModel):
    url: str | None = None
    page_type: Literal["listing"] = "listing"
    products: list[ListingProduct] = Field(default_factory=list)
    product_count: int = 0
    next_page_url: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)


class ListingExtractionRequest(BaseModel):
    url: HttpUrl | None = None
    html: str | None = None
    render: bool = False


class CatalogCrawlRequest(BaseModel):
    url: HttpUrl
    max_pages: int = Field(default=5, ge=1, le=100)
    follow_next_pages: bool = True
