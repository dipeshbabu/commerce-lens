from __future__ import annotations

import hashlib
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from commercelens.api.auth import get_job_store, require_api_key
from commercelens.api.quota import require_scope
from commercelens.domain.models import (
    ChangeEventRecord,
    MonitorCreate,
    MonitorRecord,
    ObservationRecord,
    OfferCreate,
    OfferRecord,
    ProductCreate,
    ProductMatchCreate,
    ProductMatchRecord,
    ProductRecord,
    SourceCreate,
    SourceRecord,
)
from commercelens.domain.repository import domain_repository_for_store
from commercelens.jobs.models import ApiKeyRecord

router = APIRouter()


class SourceUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    metadata: dict[str, Any] | None = None


class ProductUpdate(BaseModel):
    name: str | None = None
    brand: str | None = None
    sku: str | None = None
    identity_key: str | None = None
    metadata: dict[str, Any] | None = None


class OfferUpdate(BaseModel):
    product_id: str | None = None
    canonical_url: str | None = None
    seller_sku: str | None = None
    metadata: dict[str, Any] | None = None


class MonitorUpdate(BaseModel):
    name: str | None = None
    config: Any | None = None
    schedule_kind: str | None = None
    interval_minutes: int | None = Field(default=None, ge=1)
    status: str | None = None
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None


class ProductMatchUpdate(BaseModel):
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    status: str | None = None
    method: str | None = None
    metadata: dict[str, Any] | None = None


def _tenant(key: ApiKeyRecord | None) -> tuple[str, str]:
    if key is None or not key.account_id or not key.project_id:
        raise HTTPException(
            status_code=400,
            detail="Commerce domain resources require an account and project scoped API key.",
        )
    return key.account_id, key.project_id


def _repo(store: Any = Depends(get_job_store)):
    return domain_repository_for_store(store)


def _apply_update(record: Any, request: BaseModel) -> Any:
    for field, value in request.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(record, field, value)
    return record


def _match_id(account_id: str, project_id: str, left: str, right: str) -> str:
    key = "|".join((account_id, project_id, left, right)).encode("utf-8")
    return f"match_{hashlib.sha256(key).hexdigest()[:20]}"


@router.post("/v1/sources", response_model=SourceRecord)
def create_source_endpoint(
    request: SourceCreate,
    repo: Any = Depends(_repo),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> SourceRecord:
    require_scope(key, "extract:write")
    account_id, project_id = _tenant(key)
    existing = repo.find_source_by_domain(
        request.domain, account_id=account_id, project_id=project_id
    )
    if existing:
        raise HTTPException(status_code=409, detail="A source for this domain already exists.")
    return repo.save_source(
        SourceRecord(account_id=account_id, project_id=project_id, **request.model_dump())
    )


@router.get("/v1/sources", response_model=list[SourceRecord])
def list_sources_endpoint(
    limit: int = 100,
    repo: Any = Depends(_repo),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> list[SourceRecord]:
    require_scope(key, "extractions:read")
    account_id, project_id = _tenant(key)
    return repo.list_sources(account_id=account_id, project_id=project_id, limit=limit)


@router.get("/v1/sources/{source_id}", response_model=SourceRecord)
def get_source_endpoint(
    source_id: str,
    repo: Any = Depends(_repo),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> SourceRecord:
    require_scope(key, "extractions:read")
    account_id, project_id = _tenant(key)
    record = repo.get_source(source_id, account_id=account_id, project_id=project_id)
    if not record:
        raise HTTPException(status_code=404, detail="Source not found.")
    return record


@router.patch("/v1/sources/{source_id}", response_model=SourceRecord)
def update_source_endpoint(
    source_id: str,
    request: SourceUpdate,
    repo: Any = Depends(_repo),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> SourceRecord:
    require_scope(key, "extract:write")
    account_id, project_id = _tenant(key)
    record = repo.get_source(source_id, account_id=account_id, project_id=project_id)
    if not record:
        raise HTTPException(status_code=404, detail="Source not found.")
    return repo.save_source(_apply_update(record, request))


@router.delete("/v1/sources/{source_id}")
def delete_source_endpoint(
    source_id: str,
    repo: Any = Depends(_repo),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> dict[str, bool]:
    require_scope(key, "extract:write")
    account_id, project_id = _tenant(key)
    if repo.list_offers(account_id=account_id, project_id=project_id, source_id=source_id, limit=1):
        raise HTTPException(status_code=409, detail="Delete or move this source's offers first.")
    deleted = repo.delete_record("source", source_id, account_id=account_id, project_id=project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Source not found.")
    return {"deleted": True}


@router.post("/v1/products", response_model=ProductRecord)
def create_product_endpoint(
    request: ProductCreate,
    repo: Any = Depends(_repo),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> ProductRecord:
    require_scope(key, "extract:write")
    account_id, project_id = _tenant(key)
    if request.identity_key:
        existing = repo.find_product_by_identity(
            request.identity_key, account_id=account_id, project_id=project_id
        )
        if existing:
            raise HTTPException(status_code=409, detail="This product identity already exists.")
    return repo.save_product(
        ProductRecord(account_id=account_id, project_id=project_id, **request.model_dump())
    )


@router.get("/v1/products", response_model=list[ProductRecord])
def list_products_endpoint(
    limit: int = 100,
    repo: Any = Depends(_repo),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> list[ProductRecord]:
    require_scope(key, "extractions:read")
    account_id, project_id = _tenant(key)
    return repo.list_products(account_id=account_id, project_id=project_id, limit=limit)


@router.get("/v1/products/{product_id}", response_model=ProductRecord)
def get_product_endpoint(
    product_id: str,
    repo: Any = Depends(_repo),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> ProductRecord:
    require_scope(key, "extractions:read")
    account_id, project_id = _tenant(key)
    record = repo.get_product(product_id, account_id=account_id, project_id=project_id)
    if not record:
        raise HTTPException(status_code=404, detail="Product not found.")
    return record


@router.patch("/v1/products/{product_id}", response_model=ProductRecord)
def update_product_endpoint(
    product_id: str,
    request: ProductUpdate,
    repo: Any = Depends(_repo),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> ProductRecord:
    require_scope(key, "extract:write")
    account_id, project_id = _tenant(key)
    record = repo.get_product(product_id, account_id=account_id, project_id=project_id)
    if not record:
        raise HTTPException(status_code=404, detail="Product not found.")
    return repo.save_product(_apply_update(record, request))


@router.delete("/v1/products/{product_id}")
def delete_product_endpoint(
    product_id: str,
    repo: Any = Depends(_repo),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> dict[str, bool]:
    require_scope(key, "extract:write")
    account_id, project_id = _tenant(key)
    if repo.list_offers(
        account_id=account_id, project_id=project_id, product_id=product_id, limit=1
    ):
        raise HTTPException(status_code=409, detail="Delete or move this product's offers first.")
    deleted = repo.delete_record(
        "product", product_id, account_id=account_id, project_id=project_id
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Product not found.")
    return {"deleted": True}


@router.post("/v1/offers", response_model=OfferRecord)
def create_offer_endpoint(
    request: OfferCreate,
    repo: Any = Depends(_repo),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> OfferRecord:
    require_scope(key, "extract:write")
    account_id, project_id = _tenant(key)
    if not repo.get_product(request.product_id, account_id=account_id, project_id=project_id):
        raise HTTPException(status_code=404, detail="Product not found.")
    if not repo.get_source(request.source_id, account_id=account_id, project_id=project_id):
        raise HTTPException(status_code=404, detail="Source not found.")
    existing = repo.find_offer_by_url(
        request.url,
        source_id=request.source_id,
        account_id=account_id,
        project_id=project_id,
    )
    if existing:
        raise HTTPException(status_code=409, detail="This source offer already exists.")
    return repo.save_offer(
        OfferRecord(account_id=account_id, project_id=project_id, **request.model_dump())
    )


@router.get("/v1/offers", response_model=list[OfferRecord])
def list_offers_endpoint(
    product_id: str | None = None,
    source_id: str | None = None,
    limit: int = 100,
    repo: Any = Depends(_repo),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> list[OfferRecord]:
    require_scope(key, "extractions:read")
    account_id, project_id = _tenant(key)
    return repo.list_offers(
        account_id=account_id,
        project_id=project_id,
        product_id=product_id,
        source_id=source_id,
        limit=limit,
    )


@router.get("/v1/offers/{offer_id}", response_model=OfferRecord)
def get_offer_endpoint(
    offer_id: str,
    repo: Any = Depends(_repo),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> OfferRecord:
    require_scope(key, "extractions:read")
    account_id, project_id = _tenant(key)
    record = repo.get_offer(offer_id, account_id=account_id, project_id=project_id)
    if not record:
        raise HTTPException(status_code=404, detail="Offer not found.")
    return record


@router.patch("/v1/offers/{offer_id}", response_model=OfferRecord)
def update_offer_endpoint(
    offer_id: str,
    request: OfferUpdate,
    repo: Any = Depends(_repo),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> OfferRecord:
    require_scope(key, "extract:write")
    account_id, project_id = _tenant(key)
    record = repo.get_offer(offer_id, account_id=account_id, project_id=project_id)
    if not record:
        raise HTTPException(status_code=404, detail="Offer not found.")
    if request.product_id and not repo.get_product(
        request.product_id, account_id=account_id, project_id=project_id
    ):
        raise HTTPException(status_code=404, detail="Product not found.")
    return repo.save_offer(_apply_update(record, request))


@router.delete("/v1/offers/{offer_id}")
def delete_offer_endpoint(
    offer_id: str,
    repo: Any = Depends(_repo),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> dict[str, bool]:
    require_scope(key, "extract:write")
    account_id, project_id = _tenant(key)
    deleted = repo.delete_record("offer", offer_id, account_id=account_id, project_id=project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Offer not found.")
    return {"deleted": True}


@router.post("/v1/monitors", response_model=MonitorRecord)
def create_monitor_endpoint(
    request: MonitorCreate,
    repo: Any = Depends(_repo),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> MonitorRecord:
    require_scope(key, "jobs:write")
    account_id, project_id = _tenant(key)
    return repo.save_monitor(
        MonitorRecord(account_id=account_id, project_id=project_id, **request.model_dump())
    )


@router.get("/v1/monitors", response_model=list[MonitorRecord])
def list_monitors_endpoint(
    limit: int = 100,
    repo: Any = Depends(_repo),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> list[MonitorRecord]:
    require_scope(key, "jobs:read")
    account_id, project_id = _tenant(key)
    return repo.list_monitors(account_id=account_id, project_id=project_id, limit=limit)


@router.get("/v1/monitors/{monitor_id}", response_model=MonitorRecord)
def get_monitor_endpoint(
    monitor_id: str,
    repo: Any = Depends(_repo),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> MonitorRecord:
    require_scope(key, "jobs:read")
    account_id, project_id = _tenant(key)
    record = repo.get_monitor(monitor_id, account_id=account_id, project_id=project_id)
    if not record:
        raise HTTPException(status_code=404, detail="Monitor not found.")
    return record


@router.patch("/v1/monitors/{monitor_id}", response_model=MonitorRecord)
def update_monitor_endpoint(
    monitor_id: str,
    request: MonitorUpdate,
    repo: Any = Depends(_repo),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> MonitorRecord:
    require_scope(key, "jobs:write")
    account_id, project_id = _tenant(key)
    record = repo.get_monitor(monitor_id, account_id=account_id, project_id=project_id)
    if not record:
        raise HTTPException(status_code=404, detail="Monitor not found.")
    updates = request.model_dump(exclude_unset=True)
    if "config" in updates and updates["config"] is not None:
        from commercelens.alerts.config import MonitorConfig

        updates["config"] = MonitorConfig.model_validate(updates["config"])
    for field, value in updates.items():
        if value is not None:
            setattr(record, field, value)
    return repo.save_monitor(record)


@router.delete("/v1/monitors/{monitor_id}")
def delete_monitor_endpoint(
    monitor_id: str,
    repo: Any = Depends(_repo),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> dict[str, bool]:
    require_scope(key, "jobs:write")
    account_id, project_id = _tenant(key)
    deleted = repo.delete_record(
        "monitor", monitor_id, account_id=account_id, project_id=project_id
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Monitor not found.")
    return {"deleted": True}


@router.get("/v1/observations", response_model=list[ObservationRecord])
def list_observations_endpoint(
    product_id: str | None = None,
    offer_id: str | None = None,
    monitor_id: str | None = None,
    limit: int = 100,
    repo: Any = Depends(_repo),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> list[ObservationRecord]:
    require_scope(key, "extractions:read")
    account_id, project_id = _tenant(key)
    return repo.list_observations(
        account_id=account_id,
        project_id=project_id,
        product_id=product_id,
        offer_id=offer_id,
        monitor_id=monitor_id,
        limit=limit,
    )


@router.get("/v1/observations/{observation_id}", response_model=ObservationRecord)
def get_observation_endpoint(
    observation_id: str,
    repo: Any = Depends(_repo),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> ObservationRecord:
    require_scope(key, "extractions:read")
    account_id, project_id = _tenant(key)
    record = repo.get_observation(observation_id, account_id=account_id, project_id=project_id)
    if not record:
        raise HTTPException(status_code=404, detail="Observation not found.")
    return record


@router.get("/v1/change-events", response_model=list[ChangeEventRecord])
def list_change_events_endpoint(
    product_id: str | None = None,
    offer_id: str | None = None,
    monitor_id: str | None = None,
    event_type: str | None = None,
    limit: int = 100,
    repo: Any = Depends(_repo),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> list[ChangeEventRecord]:
    require_scope(key, "runs:read")
    account_id, project_id = _tenant(key)
    return repo.list_change_events(
        account_id=account_id,
        project_id=project_id,
        product_id=product_id,
        offer_id=offer_id,
        monitor_id=monitor_id,
        event_type=event_type,
        limit=limit,
    )


@router.get("/v1/change-events/{event_id}", response_model=ChangeEventRecord)
def get_change_event_endpoint(
    event_id: str,
    repo: Any = Depends(_repo),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> ChangeEventRecord:
    require_scope(key, "runs:read")
    account_id, project_id = _tenant(key)
    record = repo.get_change_event(event_id, account_id=account_id, project_id=project_id)
    if not record:
        raise HTTPException(status_code=404, detail="Change event not found.")
    return record


@router.post("/v1/product-matches", response_model=ProductMatchRecord)
def create_product_match_endpoint(
    request: ProductMatchCreate,
    repo: Any = Depends(_repo),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> ProductMatchRecord:
    require_scope(key, "jobs:write")
    account_id, project_id = _tenant(key)
    if request.left_product_id == request.right_product_id:
        raise HTTPException(status_code=422, detail="A product cannot be matched to itself.")
    left, right = sorted((request.left_product_id, request.right_product_id))
    if not repo.get_product(
        left, account_id=account_id, project_id=project_id
    ) or not repo.get_product(right, account_id=account_id, project_id=project_id):
        raise HTTPException(status_code=404, detail="One or both products were not found.")
    record = ProductMatchRecord(
        id=_match_id(account_id, project_id, left, right),
        account_id=account_id,
        project_id=project_id,
        left_product_id=left,
        right_product_id=right,
        confidence=request.confidence,
        status=request.status,
        method=request.method,
        metadata=request.metadata,
    )
    return repo.save_product_match(record)


@router.get("/v1/product-matches", response_model=list[ProductMatchRecord])
def list_product_matches_endpoint(
    limit: int = 100,
    repo: Any = Depends(_repo),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> list[ProductMatchRecord]:
    require_scope(key, "jobs:read")
    account_id, project_id = _tenant(key)
    return repo.list_product_matches(account_id=account_id, project_id=project_id, limit=limit)


@router.get("/v1/product-matches/{match_id}", response_model=ProductMatchRecord)
def get_product_match_endpoint(
    match_id: str,
    repo: Any = Depends(_repo),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> ProductMatchRecord:
    require_scope(key, "jobs:read")
    account_id, project_id = _tenant(key)
    record = repo.get_product_match(match_id, account_id=account_id, project_id=project_id)
    if not record:
        raise HTTPException(status_code=404, detail="Product match not found.")
    return record


@router.patch("/v1/product-matches/{match_id}", response_model=ProductMatchRecord)
def update_product_match_endpoint(
    match_id: str,
    request: ProductMatchUpdate,
    repo: Any = Depends(_repo),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> ProductMatchRecord:
    require_scope(key, "jobs:write")
    account_id, project_id = _tenant(key)
    record = repo.get_product_match(match_id, account_id=account_id, project_id=project_id)
    if not record:
        raise HTTPException(status_code=404, detail="Product match not found.")
    updates = request.model_dump(exclude_unset=True)
    if "status" in updates and updates["status"] is not None:
        from commercelens.domain.models import ProductMatchStatus

        updates["status"] = ProductMatchStatus(updates["status"])
    for field, value in updates.items():
        if value is not None:
            setattr(record, field, value)
    return repo.save_product_match(record)


@router.delete("/v1/product-matches/{match_id}")
def delete_product_match_endpoint(
    match_id: str,
    repo: Any = Depends(_repo),
    key: ApiKeyRecord | None = Depends(require_api_key),
) -> dict[str, bool]:
    require_scope(key, "jobs:write")
    account_id, project_id = _tenant(key)
    deleted = repo.delete_record(
        "product_match", match_id, account_id=account_id, project_id=project_id
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Product match not found.")
    return {"deleted": True}
