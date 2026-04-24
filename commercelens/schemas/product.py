from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator


class Availability(str, Enum):
    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    PREORDER = "preorder"
    BACKORDER = "backorder"
    UNKNOWN = "unknown"


class Price(BaseModel):
    amount: float | None = None
    currency: str | None = None
    raw: str | None = None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else value


class ExtractedField(BaseModel):
    value: Any = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source: str | None = None
    selector: str | None = None


class Product(BaseModel):
    name: str | None = None
    brand: str | None = None
    description: str | None = None
    price: Price | None = None
    original_price: Price | None = None
    availability: Availability = Availability.UNKNOWN
    sku: str | None = None
    rating: float | None = None
    review_count: int | None = None
    image_urls: list[str] = Field(default_factory=list)
    canonical_url: str | None = None
    source_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProductExtractionResult(BaseModel):
    url: str | None = None
    page_type: Literal["product"] = "product"
    product: Product
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    fields: dict[str, ExtractedField] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class ProductExtractionRequest(BaseModel):
    url: HttpUrl | None = None
    html: str | None = None
    render: bool = False
    screenshot_path: str | None = None
    html_snapshot_path: str | None = None
    llm_fallback: bool = False
