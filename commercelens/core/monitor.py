from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from commercelens.extractors.product import extract_product
from commercelens.storage.price_store import (
    PriceChange,
    PriceSnapshotStore,
    ProductSnapshot,
    snapshot_from_result,
)


class MonitorResult(BaseModel):
    product_key: str
    snapshot_id: int
    snapshot: ProductSnapshot
    change: PriceChange | None = None
    has_change: bool = False

    class Config:
        arbitrary_types_allowed = True


class BatchMonitorResult(BaseModel):
    results: list[MonitorResult] = Field(default_factory=list)
    changes: list[PriceChange] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    class Config:
        arbitrary_types_allowed = True


def monitor_product(
    url: str,
    db_path: str | Path = "commercelens.db",
    render: bool = False,
) -> MonitorResult:
    store = PriceSnapshotStore(db_path)
    extraction = extract_product(url, render=render)
    snapshot = snapshot_from_result(extraction)
    previous = store.latest_snapshot(snapshot.product_key)
    snapshot_id = store.add_snapshot(snapshot)
    change = None
    if previous:
        from commercelens.storage.price_store import compare_snapshots

        change = compare_snapshots(previous, snapshot)
    return MonitorResult(
        product_key=snapshot.product_key,
        snapshot_id=snapshot_id,
        snapshot=snapshot,
        change=change,
        has_change=change is not None,
    )


def monitor_products(
    urls: list[str],
    db_path: str | Path = "commercelens.db",
    render: bool = False,
) -> BatchMonitorResult:
    results: list[MonitorResult] = []
    changes: list[PriceChange] = []
    warnings: list[str] = []

    for url in urls:
        try:
            result = monitor_product(url, db_path=db_path, render=render)
            results.append(result)
            if result.change:
                changes.append(result.change)
        except Exception as exc:
            warnings.append(f"{url}: {exc}")

    return BatchMonitorResult(results=results, changes=changes, warnings=warnings)
