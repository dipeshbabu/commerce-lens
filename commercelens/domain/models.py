from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from commercelens.alerts.config import MonitorConfig


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


class ProductMatchStatus(str, Enum):
    proposed = "proposed"
    confirmed = "confirmed"
    rejected = "rejected"


class SourceCreate(BaseModel):
    name: str
    domain: str
    base_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceRecord(SourceCreate):
    id: str = Field(default_factory=lambda: _id("src"))
    account_id: str
    project_id: str
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class ProductCreate(BaseModel):
    name: str | None = None
    brand: str | None = None
    sku: str | None = None
    identity_key: str | None = None
    legacy_product_key: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProductRecord(ProductCreate):
    id: str = Field(default_factory=lambda: _id("prod"))
    account_id: str
    project_id: str
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class OfferCreate(BaseModel):
    product_id: str
    source_id: str
    url: str
    canonical_url: str | None = None
    seller_sku: str | None = None
    current_amount: float | None = None
    current_currency: str | None = None
    current_availability: str | None = None
    last_observed_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class OfferRecord(OfferCreate):
    id: str = Field(default_factory=lambda: _id("offer"))
    account_id: str
    project_id: str
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class MonitorCreate(BaseModel):
    name: str
    config: MonitorConfig
    schedule_kind: str = "interval"
    interval_minutes: int = Field(default=360, ge=1)
    status: str = "active"
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MonitorRecord(MonitorCreate):
    id: str = Field(default_factory=lambda: _id("mon"))
    account_id: str
    project_id: str
    job_id: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class ObservationRecord(BaseModel):
    id: str = Field(default_factory=lambda: _id("obs"))
    account_id: str
    project_id: str
    source_id: str
    product_id: str
    offer_id: str
    monitor_id: str | None = None
    job_id: str | None = None
    run_id: str | None = None
    extraction_id: str | None = None
    captured_at: str = Field(default_factory=utc_now_iso)
    amount: float | None = None
    currency: str | None = None
    availability: str | None = None
    name: str | None = None
    brand: str | None = None
    source_url: str | None = None
    canonical_url: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    provenance: dict[str, Any] = Field(default_factory=dict)
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso)


class ChangeEventRecord(BaseModel):
    id: str = Field(default_factory=lambda: _id("chg"))
    account_id: str
    project_id: str
    source_id: str
    product_id: str
    offer_id: str
    observation_id: str
    previous_observation_id: str
    monitor_id: str | None = None
    job_id: str | None = None
    run_id: str | None = None
    event_type: str
    severity: str = "info"
    previous_amount: float | None = None
    current_amount: float | None = None
    currency: str | None = None
    delta: float | None = None
    delta_percent: float | None = None
    previous_availability: str | None = None
    current_availability: str | None = None
    changed_at: str
    dedupe_key: str
    provenance: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso)


class ProductMatchCreate(BaseModel):
    left_product_id: str
    right_product_id: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    status: ProductMatchStatus = ProductMatchStatus.proposed
    method: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProductMatchRecord(ProductMatchCreate):
    id: str = Field(default_factory=lambda: _id("match"))
    account_id: str
    project_id: str
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class DomainIngestResult(BaseModel):
    source: SourceRecord
    product: ProductRecord
    offer: OfferRecord
    observation: ObservationRecord
    change: ChangeEventRecord | None = None
