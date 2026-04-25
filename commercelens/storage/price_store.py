from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from commercelens.schemas.product import ProductExtractionResult


@dataclass(slots=True)
class ProductSnapshot:
    product_key: str
    source_url: str | None
    canonical_url: str | None
    name: str | None
    brand: str | None
    amount: float | None
    currency: str | None
    availability: str | None
    image_url: str | None
    captured_at: str
    raw: dict[str, Any]


@dataclass(slots=True)
class PriceChange:
    product_key: str
    source_url: str | None
    name: str | None
    previous_amount: float | None
    current_amount: float | None
    currency: str | None
    delta: float | None
    delta_percent: float | None
    previous_availability: str | None
    current_availability: str | None
    changed_at: str
    change_type: str


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def product_key_for(url: str | None, name: str | None, brand: str | None = None) -> str:
    identity = "|".join(part.strip().lower() for part in [url or "", brand or "", name or ""])
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def snapshot_from_result(result: ProductExtractionResult, captured_at: str | None = None) -> ProductSnapshot:
    product = result.product
    price = product.price
    canonical_or_source = product.canonical_url or product.source_url or result.url
    key = product_key_for(canonical_or_source, product.name, product.brand)
    return ProductSnapshot(
        product_key=key,
        source_url=product.source_url or result.url,
        canonical_url=product.canonical_url,
        name=product.name,
        brand=product.brand,
        amount=price.amount if price else None,
        currency=price.currency if price else None,
        availability=product.availability.value if product.availability else None,
        image_url=product.image_urls[0] if product.image_urls else None,
        captured_at=captured_at or utc_now_iso(),
        raw=result.model_dump(mode="json", exclude_none=True),
    )


class PriceSnapshotStore:
    def __init__(self, path: str | Path = "commercelens.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True) if self.path.parent != Path(".") else None
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS price_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_key TEXT NOT NULL,
                    source_url TEXT,
                    canonical_url TEXT,
                    name TEXT,
                    brand TEXT,
                    amount REAL,
                    currency TEXT,
                    availability TEXT,
                    image_url TEXT,
                    captured_at TEXT NOT NULL,
                    raw_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_price_snapshots_key_time "
                "ON price_snapshots(product_key, captured_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_price_snapshots_url "
                "ON price_snapshots(source_url)"
            )

    def add_snapshot(self, snapshot: ProductSnapshot) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO price_snapshots (
                    product_key, source_url, canonical_url, name, brand, amount, currency,
                    availability, image_url, captured_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.product_key,
                    snapshot.source_url,
                    snapshot.canonical_url,
                    snapshot.name,
                    snapshot.brand,
                    snapshot.amount,
                    snapshot.currency,
                    snapshot.availability,
                    snapshot.image_url,
                    snapshot.captured_at,
                    json.dumps(snapshot.raw, ensure_ascii=False),
                ),
            )
            return int(cursor.lastrowid)

    def add_result(self, result: ProductExtractionResult) -> int:
        return self.add_snapshot(snapshot_from_result(result))

    def latest_snapshot(self, product_key: str) -> ProductSnapshot | None:
        rows = self.history(product_key, limit=1)
        return rows[0] if rows else None

    def history(self, product_key: str, limit: int = 100) -> list[ProductSnapshot]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM price_snapshots
                WHERE product_key = ?
                ORDER BY captured_at DESC, id DESC
                LIMIT ?
                """,
                (product_key, limit),
            ).fetchall()
        return [self._row_to_snapshot(row) for row in rows]

    def history_for_url(self, url: str, limit: int = 100) -> list[ProductSnapshot]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM price_snapshots
                WHERE source_url = ? OR canonical_url = ?
                ORDER BY captured_at DESC, id DESC
                LIMIT ?
                """,
                (url, url, limit),
            ).fetchall()
        return [self._row_to_snapshot(row) for row in rows]

    def all_latest(self) -> list[ProductSnapshot]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT ps.*
                FROM price_snapshots ps
                JOIN (
                    SELECT product_key, MAX(captured_at) AS max_captured_at
                    FROM price_snapshots
                    GROUP BY product_key
                ) latest
                ON ps.product_key = latest.product_key AND ps.captured_at = latest.max_captured_at
                ORDER BY ps.captured_at DESC
                """
            ).fetchall()
        return [self._row_to_snapshot(row) for row in rows]

    def detect_change(self, product_key: str) -> PriceChange | None:
        snapshots = self.history(product_key, limit=2)
        if len(snapshots) < 2:
            return None
        current, previous = snapshots[0], snapshots[1]
        return compare_snapshots(previous, current)

    def detect_changes(self, product_keys: Iterable[str] | None = None) -> list[PriceChange]:
        keys = list(product_keys) if product_keys is not None else [item.product_key for item in self.all_latest()]
        changes: list[PriceChange] = []
        for key in keys:
            change = self.detect_change(key)
            if change:
                changes.append(change)
        return changes

    @staticmethod
    def _row_to_snapshot(row: sqlite3.Row) -> ProductSnapshot:
        return ProductSnapshot(
            product_key=row["product_key"],
            source_url=row["source_url"],
            canonical_url=row["canonical_url"],
            name=row["name"],
            brand=row["brand"],
            amount=row["amount"],
            currency=row["currency"],
            availability=row["availability"],
            image_url=row["image_url"],
            captured_at=row["captured_at"],
            raw=json.loads(row["raw_json"]),
        )


def compare_snapshots(previous: ProductSnapshot, current: ProductSnapshot) -> PriceChange | None:
    price_changed = previous.amount != current.amount or previous.currency != current.currency
    availability_changed = previous.availability != current.availability
    if not price_changed and not availability_changed:
        return None

    delta = None
    delta_percent = None
    if previous.amount is not None and current.amount is not None:
        delta = round(current.amount - previous.amount, 4)
        if previous.amount != 0:
            delta_percent = round((delta / previous.amount) * 100, 4)

    change_type = "availability_change"
    if price_changed and availability_changed:
        change_type = "price_and_availability_change"
    elif price_changed:
        if delta is not None and delta < 0:
            change_type = "price_drop"
        elif delta is not None and delta > 0:
            change_type = "price_increase"
        else:
            change_type = "price_change"
    elif previous.availability == "out_of_stock" and current.availability == "in_stock":
        change_type = "back_in_stock"

    return PriceChange(
        product_key=current.product_key,
        source_url=current.source_url,
        name=current.name,
        previous_amount=previous.amount,
        current_amount=current.amount,
        currency=current.currency or previous.currency,
        delta=delta,
        delta_percent=delta_percent,
        previous_availability=previous.availability,
        current_availability=current.availability,
        changed_at=current.captured_at,
        change_type=change_type,
    )
