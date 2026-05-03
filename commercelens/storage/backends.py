from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from commercelens.storage.price_store import PriceChange, PriceSnapshotStore, ProductSnapshot

StorageBackendName = Literal["sqlite", "postgres"]


class StorageConfig(BaseModel):
    backend: StorageBackendName = "sqlite"
    sqlite_path: str = "commercelens.db"
    postgres_dsn: str | None = None


class ProductSnapshotBackend(ABC):
    @abstractmethod
    def add_snapshot(self, snapshot: ProductSnapshot) -> None:
        raise NotImplementedError

    @abstractmethod
    def history(self, product_key: str, limit: int = 100) -> list[ProductSnapshot]:
        raise NotImplementedError

    @abstractmethod
    def history_for_url(self, url: str, limit: int = 100) -> list[ProductSnapshot]:
        raise NotImplementedError

    @abstractmethod
    def latest(self, product_key: str) -> ProductSnapshot | None:
        raise NotImplementedError

    @abstractmethod
    def list_latest(self, limit: int = 100) -> list[ProductSnapshot]:
        raise NotImplementedError

    @abstractmethod
    def detect_change(self, product_key: str) -> PriceChange | None:
        raise NotImplementedError

    @abstractmethod
    def detect_changes(self, limit: int = 100) -> list[PriceChange]:
        raise NotImplementedError


class SQLiteSnapshotBackend(ProductSnapshotBackend):
    def __init__(self, path: str | Path = "commercelens.db") -> None:
        self.store = PriceSnapshotStore(path)

    def add_snapshot(self, snapshot: ProductSnapshot) -> None:
        self.store.add_snapshot(snapshot)

    def history(self, product_key: str, limit: int = 100) -> list[ProductSnapshot]:
        return self.store.history(product_key, limit=limit)

    def history_for_url(self, url: str, limit: int = 100) -> list[ProductSnapshot]:
        return self.store.history_for_url(url, limit=limit)

    def latest(self, product_key: str) -> ProductSnapshot | None:
        return self.store.latest(product_key)

    def list_latest(self, limit: int = 100) -> list[ProductSnapshot]:
        return self.store.list_latest(limit=limit)

    def detect_change(self, product_key: str) -> PriceChange | None:
        return self.store.detect_change(product_key)

    def detect_changes(self, limit: int = 100) -> list[PriceChange]:
        return self.store.detect_changes(limit=limit)


class PostgresSnapshotBackend(ProductSnapshotBackend):
    """PostgreSQL-compatible backend for hosted deployments.

    This backend uses psycopg and mirrors the SQLite snapshot schema. It is optional so the
    default CommerceLens install stays lightweight. Install with `pip install -e .[postgres]`.
    """

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn or os.getenv("COMMERCELENS_POSTGRES_DSN")
        if not self.dsn:
            raise ValueError("Postgres backend requires postgres_dsn or COMMERCELENS_POSTGRES_DSN.")
        try:
            import psycopg  # type: ignore
            from psycopg.rows import dict_row  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency path
            raise RuntimeError("Postgres backend requires psycopg. Install with `pip install -e .[postgres]`.") from exc
        self._psycopg = psycopg
        self._dict_row = dict_row
        self._ensure_schema()

    def _connect(self):
        return self._psycopg.connect(self.dsn, row_factory=self._dict_row)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS product_snapshots (
                        id BIGSERIAL PRIMARY KEY,
                        product_key TEXT NOT NULL,
                        source_url TEXT,
                        canonical_url TEXT,
                        name TEXT,
                        brand TEXT,
                        amount DOUBLE PRECISION,
                        currency TEXT,
                        availability TEXT,
                        image_url TEXT,
                        captured_at TEXT NOT NULL,
                        raw_payload JSONB
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_product_snapshots_product_key ON product_snapshots(product_key)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_product_snapshots_source_url ON product_snapshots(source_url)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_product_snapshots_captured_at ON product_snapshots(captured_at)"
                )

    def add_snapshot(self, snapshot: ProductSnapshot) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO product_snapshots (
                        product_key, source_url, canonical_url, name, brand, amount, currency,
                        availability, image_url, captured_at, raw_payload
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                        snapshot.raw,
                    ),
                )

    def history(self, product_key: str, limit: int = 100) -> list[ProductSnapshot]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM product_snapshots
                    WHERE product_key = %s
                    ORDER BY captured_at DESC, id DESC
                    LIMIT %s
                    """,
                    (product_key, limit),
                )
                return [_snapshot_from_row(row) for row in cur.fetchall()]

    def history_for_url(self, url: str, limit: int = 100) -> list[ProductSnapshot]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM product_snapshots
                    WHERE source_url = %s OR canonical_url = %s
                    ORDER BY captured_at DESC, id DESC
                    LIMIT %s
                    """,
                    (url, url, limit),
                )
                return [_snapshot_from_row(row) for row in cur.fetchall()]

    def latest(self, product_key: str) -> ProductSnapshot | None:
        history = self.history(product_key, limit=1)
        return history[0] if history else None

    def list_latest(self, limit: int = 100) -> list[ProductSnapshot]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT ON (product_key) *
                    FROM product_snapshots
                    ORDER BY product_key, captured_at DESC, id DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                return [_snapshot_from_row(row) for row in cur.fetchall()]

    def detect_change(self, product_key: str) -> PriceChange | None:
        from commercelens.storage.price_store import compare_snapshots

        history = self.history(product_key, limit=2)
        if len(history) < 2:
            return None
        return compare_snapshots(previous=history[1], current=history[0])

    def detect_changes(self, limit: int = 100) -> list[PriceChange]:
        changes: list[PriceChange] = []
        for snapshot in self.list_latest(limit=limit):
            change = self.detect_change(snapshot.product_key)
            if change:
                changes.append(change)
        return changes


def _snapshot_from_row(row: dict) -> ProductSnapshot:
    payload = row.get("raw_payload") or {}
    return ProductSnapshot(
        product_key=row["product_key"],
        source_url=row.get("source_url"),
        canonical_url=row.get("canonical_url"),
        name=row.get("name"),
        brand=row.get("brand"),
        amount=row.get("amount"),
        currency=row.get("currency"),
        availability=row.get("availability"),
        image_url=row.get("image_url"),
        captured_at=row["captured_at"],
        raw=payload,
    )


def make_snapshot_backend(config: StorageConfig | None = None) -> ProductSnapshotBackend:
    config = config or StorageConfig()
    if config.backend == "sqlite":
        return SQLiteSnapshotBackend(config.sqlite_path)
    if config.backend == "postgres":
        return PostgresSnapshotBackend(config.postgres_dsn)
    raise ValueError(f"Unsupported storage backend: {config.backend}")
