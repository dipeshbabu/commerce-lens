from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from commercelens.domain.models import (
    ChangeEventRecord,
    MonitorRecord,
    ObservationRecord,
    OfferRecord,
    ProductMatchRecord,
    ProductRecord,
    SourceRecord,
    utc_now_iso,
)
from commercelens.jobs.migrations import run_postgres_migrations

T = TypeVar("T", bound=BaseModel)


class CommerceRepository(Protocol):
    def save_source(self, record: SourceRecord) -> SourceRecord: ...
    def get_source(
        self, source_id: str, *, account_id: str, project_id: str
    ) -> SourceRecord | None: ...
    def list_sources(
        self, *, account_id: str, project_id: str, limit: int = 100
    ) -> list[SourceRecord]: ...
    def save_product(self, record: ProductRecord) -> ProductRecord: ...
    def get_product(
        self, product_id: str, *, account_id: str, project_id: str
    ) -> ProductRecord | None: ...
    def list_products(
        self, *, account_id: str, project_id: str, limit: int = 100
    ) -> list[ProductRecord]: ...
    def save_offer(self, record: OfferRecord) -> OfferRecord: ...
    def get_offer(
        self, offer_id: str, *, account_id: str, project_id: str
    ) -> OfferRecord | None: ...
    def list_offers(
        self,
        *,
        account_id: str,
        project_id: str,
        product_id: str | None = None,
        source_id: str | None = None,
        limit: int = 100,
    ) -> list[OfferRecord]: ...
    def save_monitor(self, record: MonitorRecord) -> MonitorRecord: ...
    def get_monitor(
        self, monitor_id: str, *, account_id: str, project_id: str
    ) -> MonitorRecord | None: ...
    def list_monitors(
        self, *, account_id: str, project_id: str, limit: int = 100
    ) -> list[MonitorRecord]: ...
    def save_observation(self, record: ObservationRecord) -> ObservationRecord: ...
    def get_observation(
        self, observation_id: str, *, account_id: str, project_id: str
    ) -> ObservationRecord | None: ...
    def list_observations(
        self,
        *,
        account_id: str,
        project_id: str,
        product_id: str | None = None,
        offer_id: str | None = None,
        monitor_id: str | None = None,
        limit: int = 100,
    ) -> list[ObservationRecord]: ...
    def latest_observation(
        self, offer_id: str, *, account_id: str, project_id: str
    ) -> ObservationRecord | None: ...
    def save_change_event(self, record: ChangeEventRecord) -> ChangeEventRecord: ...
    def get_change_event(
        self, event_id: str, *, account_id: str, project_id: str
    ) -> ChangeEventRecord | None: ...
    def list_change_events(
        self,
        *,
        account_id: str,
        project_id: str,
        product_id: str | None = None,
        offer_id: str | None = None,
        monitor_id: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[ChangeEventRecord]: ...
    def save_product_match(self, record: ProductMatchRecord) -> ProductMatchRecord: ...
    def get_product_match(
        self, match_id: str, *, account_id: str, project_id: str
    ) -> ProductMatchRecord | None: ...
    def list_product_matches(
        self, *, account_id: str, project_id: str, limit: int = 100
    ) -> list[ProductMatchRecord]: ...
    def delete_record(
        self, resource: str, record_id: str, *, account_id: str, project_id: str
    ) -> bool: ...


_SQLITE_TABLES = {
    "source": "commerce_sources",
    "product": "commerce_products",
    "offer": "commerce_offers",
    "monitor": "commerce_monitors",
    "observation": "commerce_observations",
    "change_event": "commerce_change_events",
    "product_match": "commerce_product_matches",
}


class SQLiteDomainRepository:
    def __init__(self, path: str | Path = "commercelens_jobs.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS commerce_sources (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_commerce_sources_tenant_domain
                    ON commerce_sources(account_id, project_id, domain);

                CREATE TABLE IF NOT EXISTS commerce_products (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    identity_key TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_commerce_products_identity
                    ON commerce_products(account_id, project_id, identity_key)
                    WHERE identity_key IS NOT NULL;
                CREATE INDEX IF NOT EXISTS idx_commerce_products_tenant
                    ON commerce_products(account_id, project_id, updated_at);

                CREATE TABLE IF NOT EXISTS commerce_offers (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    product_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_commerce_offers_source_url
                    ON commerce_offers(account_id, project_id, source_id, url);
                CREATE INDEX IF NOT EXISTS idx_commerce_offers_product
                    ON commerce_offers(account_id, project_id, product_id);

                CREATE TABLE IF NOT EXISTS commerce_monitors (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    job_id TEXT,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_commerce_monitors_tenant
                    ON commerce_monitors(account_id, project_id, updated_at);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_commerce_monitors_job
                    ON commerce_monitors(account_id, project_id, job_id)
                    WHERE job_id IS NOT NULL;

                CREATE TABLE IF NOT EXISTS commerce_observations (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    product_id TEXT NOT NULL,
                    offer_id TEXT NOT NULL,
                    monitor_id TEXT,
                    job_id TEXT,
                    run_id TEXT,
                    captured_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_commerce_observations_offer_time
                    ON commerce_observations(account_id, project_id, offer_id, captured_at DESC);
                CREATE INDEX IF NOT EXISTS idx_commerce_observations_product_time
                    ON commerce_observations(account_id, project_id, product_id, captured_at DESC);
                CREATE INDEX IF NOT EXISTS idx_commerce_observations_monitor_time
                    ON commerce_observations(account_id, project_id, monitor_id, captured_at DESC);

                CREATE TABLE IF NOT EXISTS commerce_change_events (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    product_id TEXT NOT NULL,
                    offer_id TEXT NOT NULL,
                    monitor_id TEXT,
                    event_type TEXT NOT NULL,
                    changed_at TEXT NOT NULL,
                    dedupe_key TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_commerce_change_dedupe
                    ON commerce_change_events(account_id, project_id, dedupe_key);
                CREATE INDEX IF NOT EXISTS idx_commerce_change_feed
                    ON commerce_change_events(account_id, project_id, changed_at DESC);

                CREATE TABLE IF NOT EXISTS commerce_product_matches (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    left_product_id TEXT NOT NULL,
                    right_product_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_commerce_product_match_pair
                    ON commerce_product_matches(
                        account_id, project_id, left_product_id, right_product_id
                    );
                """
            )

    def _save(self, table: str, record: BaseModel, indexes: dict[str, object]) -> None:
        columns = ["id", "payload", *indexes]
        values: list[object] = [
            getattr(record, "id"),
            record.model_dump_json(exclude_none=True),
            *indexes.values(),
        ]
        placeholders = ", ".join("?" for _ in columns)
        updates = ", ".join(f"{column}=excluded.{column}" for column in columns[1:])
        with self._connect() as conn:
            conn.execute(
                f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
                f"ON CONFLICT(id) DO UPDATE SET {updates}",
                values,
            )

    def _get(
        self,
        table: str,
        record_id: str,
        model: type[T],
        *,
        account_id: str,
        project_id: str,
    ) -> T | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT payload FROM {table} WHERE id = ? AND account_id = ? AND project_id = ?",
                (record_id, account_id, project_id),
            ).fetchone()
        return model.model_validate_json(row["payload"]) if row else None

    def _list(
        self,
        table: str,
        model: type[T],
        *,
        account_id: str,
        project_id: str,
        filters: dict[str, object] | None = None,
        order_by: str = "updated_at DESC",
        limit: int = 100,
    ) -> list[T]:
        query = f"SELECT payload FROM {table} WHERE account_id = ? AND project_id = ?"
        params: list[object] = [account_id, project_id]
        for column, value in (filters or {}).items():
            if value is None:
                continue
            query += f" AND {column} = ?"
            params.append(value)
        query += f" ORDER BY {order_by} LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [model.model_validate_json(row["payload"]) for row in rows]

    def save_source(self, record: SourceRecord) -> SourceRecord:
        record.updated_at = utc_now_iso()
        self._save(
            "commerce_sources",
            record,
            {
                "account_id": record.account_id,
                "project_id": record.project_id,
                "domain": record.domain.lower(),
                "updated_at": record.updated_at,
            },
        )
        return record

    def get_source(
        self, source_id: str, *, account_id: str, project_id: str
    ) -> SourceRecord | None:
        return self._get(
            "commerce_sources",
            source_id,
            SourceRecord,
            account_id=account_id,
            project_id=project_id,
        )

    def find_source_by_domain(
        self, domain: str, *, account_id: str, project_id: str
    ) -> SourceRecord | None:
        rows = self._list(
            "commerce_sources",
            SourceRecord,
            account_id=account_id,
            project_id=project_id,
            filters={"domain": domain.lower()},
            limit=1,
        )
        return rows[0] if rows else None

    def list_sources(
        self, *, account_id: str, project_id: str, limit: int = 100
    ) -> list[SourceRecord]:
        return self._list(
            "commerce_sources",
            SourceRecord,
            account_id=account_id,
            project_id=project_id,
            limit=limit,
        )

    def save_product(self, record: ProductRecord) -> ProductRecord:
        record.updated_at = utc_now_iso()
        self._save(
            "commerce_products",
            record,
            {
                "account_id": record.account_id,
                "project_id": record.project_id,
                "identity_key": record.identity_key,
                "updated_at": record.updated_at,
            },
        )
        return record

    def get_product(
        self, product_id: str, *, account_id: str, project_id: str
    ) -> ProductRecord | None:
        return self._get(
            "commerce_products",
            product_id,
            ProductRecord,
            account_id=account_id,
            project_id=project_id,
        )

    def find_product_by_identity(
        self, identity_key: str, *, account_id: str, project_id: str
    ) -> ProductRecord | None:
        rows = self._list(
            "commerce_products",
            ProductRecord,
            account_id=account_id,
            project_id=project_id,
            filters={"identity_key": identity_key},
            limit=1,
        )
        return rows[0] if rows else None

    def list_products(
        self, *, account_id: str, project_id: str, limit: int = 100
    ) -> list[ProductRecord]:
        return self._list(
            "commerce_products",
            ProductRecord,
            account_id=account_id,
            project_id=project_id,
            limit=limit,
        )

    def save_offer(self, record: OfferRecord) -> OfferRecord:
        record.updated_at = utc_now_iso()
        self._save(
            "commerce_offers",
            record,
            {
                "account_id": record.account_id,
                "project_id": record.project_id,
                "product_id": record.product_id,
                "source_id": record.source_id,
                "url": record.url,
                "updated_at": record.updated_at,
            },
        )
        return record

    def get_offer(self, offer_id: str, *, account_id: str, project_id: str) -> OfferRecord | None:
        return self._get(
            "commerce_offers", offer_id, OfferRecord, account_id=account_id, project_id=project_id
        )

    def find_offer_by_url(
        self, url: str, *, source_id: str, account_id: str, project_id: str
    ) -> OfferRecord | None:
        rows = self._list(
            "commerce_offers",
            OfferRecord,
            account_id=account_id,
            project_id=project_id,
            filters={"source_id": source_id, "url": url},
            limit=1,
        )
        return rows[0] if rows else None

    def list_offers(
        self,
        *,
        account_id: str,
        project_id: str,
        product_id: str | None = None,
        source_id: str | None = None,
        limit: int = 100,
    ) -> list[OfferRecord]:
        return self._list(
            "commerce_offers",
            OfferRecord,
            account_id=account_id,
            project_id=project_id,
            filters={"product_id": product_id, "source_id": source_id},
            limit=limit,
        )

    def save_monitor(self, record: MonitorRecord) -> MonitorRecord:
        record.updated_at = utc_now_iso()
        self._save(
            "commerce_monitors",
            record,
            {
                "account_id": record.account_id,
                "project_id": record.project_id,
                "job_id": record.job_id,
                "status": record.status,
                "updated_at": record.updated_at,
            },
        )
        return record

    def get_monitor(
        self, monitor_id: str, *, account_id: str, project_id: str
    ) -> MonitorRecord | None:
        return self._get(
            "commerce_monitors",
            monitor_id,
            MonitorRecord,
            account_id=account_id,
            project_id=project_id,
        )

    def find_monitor_by_job(
        self, job_id: str, *, account_id: str, project_id: str
    ) -> MonitorRecord | None:
        rows = self._list(
            "commerce_monitors",
            MonitorRecord,
            account_id=account_id,
            project_id=project_id,
            filters={"job_id": job_id},
            limit=1,
        )
        return rows[0] if rows else None

    def list_monitors(
        self, *, account_id: str, project_id: str, limit: int = 100
    ) -> list[MonitorRecord]:
        return self._list(
            "commerce_monitors",
            MonitorRecord,
            account_id=account_id,
            project_id=project_id,
            limit=limit,
        )

    def save_observation(self, record: ObservationRecord) -> ObservationRecord:
        self._save(
            "commerce_observations",
            record,
            {
                "account_id": record.account_id,
                "project_id": record.project_id,
                "source_id": record.source_id,
                "product_id": record.product_id,
                "offer_id": record.offer_id,
                "monitor_id": record.monitor_id,
                "job_id": record.job_id,
                "run_id": record.run_id,
                "captured_at": record.captured_at,
            },
        )
        return record

    def get_observation(
        self, observation_id: str, *, account_id: str, project_id: str
    ) -> ObservationRecord | None:
        return self._get(
            "commerce_observations",
            observation_id,
            ObservationRecord,
            account_id=account_id,
            project_id=project_id,
        )

    def list_observations(
        self,
        *,
        account_id: str,
        project_id: str,
        product_id: str | None = None,
        offer_id: str | None = None,
        monitor_id: str | None = None,
        limit: int = 100,
    ) -> list[ObservationRecord]:
        return self._list(
            "commerce_observations",
            ObservationRecord,
            account_id=account_id,
            project_id=project_id,
            filters={
                "product_id": product_id,
                "offer_id": offer_id,
                "monitor_id": monitor_id,
            },
            order_by="captured_at DESC",
            limit=limit,
        )

    def latest_observation(
        self, offer_id: str, *, account_id: str, project_id: str
    ) -> ObservationRecord | None:
        rows = self.list_observations(
            account_id=account_id, project_id=project_id, offer_id=offer_id, limit=1
        )
        return rows[0] if rows else None

    def save_change_event(self, record: ChangeEventRecord) -> ChangeEventRecord:
        existing = self._list(
            "commerce_change_events",
            ChangeEventRecord,
            account_id=record.account_id,
            project_id=record.project_id,
            filters={"dedupe_key": record.dedupe_key},
            order_by="changed_at DESC",
            limit=1,
        )
        if existing:
            return existing[0]
        self._save(
            "commerce_change_events",
            record,
            {
                "account_id": record.account_id,
                "project_id": record.project_id,
                "product_id": record.product_id,
                "offer_id": record.offer_id,
                "monitor_id": record.monitor_id,
                "event_type": record.event_type,
                "changed_at": record.changed_at,
                "dedupe_key": record.dedupe_key,
            },
        )
        return record

    def get_change_event(
        self, event_id: str, *, account_id: str, project_id: str
    ) -> ChangeEventRecord | None:
        return self._get(
            "commerce_change_events",
            event_id,
            ChangeEventRecord,
            account_id=account_id,
            project_id=project_id,
        )

    def list_change_events(
        self,
        *,
        account_id: str,
        project_id: str,
        product_id: str | None = None,
        offer_id: str | None = None,
        monitor_id: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[ChangeEventRecord]:
        return self._list(
            "commerce_change_events",
            ChangeEventRecord,
            account_id=account_id,
            project_id=project_id,
            filters={
                "product_id": product_id,
                "offer_id": offer_id,
                "monitor_id": monitor_id,
                "event_type": event_type,
            },
            order_by="changed_at DESC",
            limit=limit,
        )

    def save_product_match(self, record: ProductMatchRecord) -> ProductMatchRecord:
        record.updated_at = utc_now_iso()
        self._save(
            "commerce_product_matches",
            record,
            {
                "account_id": record.account_id,
                "project_id": record.project_id,
                "left_product_id": record.left_product_id,
                "right_product_id": record.right_product_id,
                "status": record.status.value,
                "updated_at": record.updated_at,
            },
        )
        return record

    def get_product_match(
        self, match_id: str, *, account_id: str, project_id: str
    ) -> ProductMatchRecord | None:
        return self._get(
            "commerce_product_matches",
            match_id,
            ProductMatchRecord,
            account_id=account_id,
            project_id=project_id,
        )

    def list_product_matches(
        self, *, account_id: str, project_id: str, limit: int = 100
    ) -> list[ProductMatchRecord]:
        return self._list(
            "commerce_product_matches",
            ProductMatchRecord,
            account_id=account_id,
            project_id=project_id,
            limit=limit,
        )

    def delete_record(
        self, resource: str, record_id: str, *, account_id: str, project_id: str
    ) -> bool:
        table = _SQLITE_TABLES.get(resource)
        if not table:
            raise ValueError(f"Unsupported commerce resource: {resource}")
        with self._connect() as conn:
            cursor = conn.execute(
                f"DELETE FROM {table} WHERE id = ? AND account_id = ? AND project_id = ?",
                (record_id, account_id, project_id),
            )
        return cursor.rowcount > 0


class PostgresDomainRepository:
    def __init__(self, dsn: str) -> None:
        try:
            import psycopg  # type: ignore[import-not-found]
            from psycopg.rows import dict_row  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - optional dependency path
            raise RuntimeError("Postgres domain storage requires commercelens[postgres].") from exc
        self.dsn = dsn
        self._psycopg = psycopg
        self._dict_row = dict_row
        with self._connect() as conn:
            run_postgres_migrations(conn)

    def _connect(self):
        return self._psycopg.connect(self.dsn, row_factory=self._dict_row)

    def _save(self, table: str, record: BaseModel, indexes: dict[str, object]) -> None:
        columns = ["id", "payload", *indexes]
        values: list[object] = [
            getattr(record, "id"),
            record.model_dump_json(exclude_none=True),
            *indexes.values(),
        ]
        placeholders = ["%s", "%s::jsonb", *["%s" for _ in indexes]]
        updates = ", ".join(f"{column}=excluded.{column}" for column in columns[1:])
        with self._connect() as conn:
            conn.execute(
                f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(placeholders)}) "
                f"ON CONFLICT(id) DO UPDATE SET {updates}",
                values,
            )

    def _get(
        self,
        table: str,
        record_id: str,
        model: type[T],
        *,
        account_id: str,
        project_id: str,
    ) -> T | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT payload FROM {table} WHERE id = %s AND account_id = %s AND project_id = %s",
                (record_id, account_id, project_id),
            ).fetchone()
        return model.model_validate(row["payload"]) if row else None

    def _list(
        self,
        table: str,
        model: type[T],
        *,
        account_id: str,
        project_id: str,
        filters: dict[str, object] | None = None,
        order_by: str = "updated_at DESC",
        limit: int = 100,
    ) -> list[T]:
        query = f"SELECT payload FROM {table} WHERE account_id = %s AND project_id = %s"
        params: list[object] = [account_id, project_id]
        for column, value in (filters or {}).items():
            if value is None:
                continue
            query += f" AND {column} = %s"
            params.append(value)
        query += f" ORDER BY {order_by} LIMIT %s"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [model.model_validate(row["payload"]) for row in rows]

    def save_source(self, record: SourceRecord) -> SourceRecord:
        record.updated_at = utc_now_iso()
        self._save(
            "commerce_sources",
            record,
            {
                "account_id": record.account_id,
                "project_id": record.project_id,
                "domain": record.domain.lower(),
                "updated_at": record.updated_at,
            },
        )
        return record

    def get_source(
        self, source_id: str, *, account_id: str, project_id: str
    ) -> SourceRecord | None:
        return self._get(
            "commerce_sources",
            source_id,
            SourceRecord,
            account_id=account_id,
            project_id=project_id,
        )

    def find_source_by_domain(
        self, domain: str, *, account_id: str, project_id: str
    ) -> SourceRecord | None:
        rows = self._list(
            "commerce_sources",
            SourceRecord,
            account_id=account_id,
            project_id=project_id,
            filters={"domain": domain.lower()},
            limit=1,
        )
        return rows[0] if rows else None

    def list_sources(
        self, *, account_id: str, project_id: str, limit: int = 100
    ) -> list[SourceRecord]:
        return self._list(
            "commerce_sources",
            SourceRecord,
            account_id=account_id,
            project_id=project_id,
            limit=limit,
        )

    def save_product(self, record: ProductRecord) -> ProductRecord:
        record.updated_at = utc_now_iso()
        self._save(
            "commerce_products",
            record,
            {
                "account_id": record.account_id,
                "project_id": record.project_id,
                "identity_key": record.identity_key,
                "updated_at": record.updated_at,
            },
        )
        return record

    def get_product(
        self, product_id: str, *, account_id: str, project_id: str
    ) -> ProductRecord | None:
        return self._get(
            "commerce_products",
            product_id,
            ProductRecord,
            account_id=account_id,
            project_id=project_id,
        )

    def find_product_by_identity(
        self, identity_key: str, *, account_id: str, project_id: str
    ) -> ProductRecord | None:
        rows = self._list(
            "commerce_products",
            ProductRecord,
            account_id=account_id,
            project_id=project_id,
            filters={"identity_key": identity_key},
            limit=1,
        )
        return rows[0] if rows else None

    def list_products(
        self, *, account_id: str, project_id: str, limit: int = 100
    ) -> list[ProductRecord]:
        return self._list(
            "commerce_products",
            ProductRecord,
            account_id=account_id,
            project_id=project_id,
            limit=limit,
        )

    def save_offer(self, record: OfferRecord) -> OfferRecord:
        record.updated_at = utc_now_iso()
        self._save(
            "commerce_offers",
            record,
            {
                "account_id": record.account_id,
                "project_id": record.project_id,
                "product_id": record.product_id,
                "source_id": record.source_id,
                "url": record.url,
                "updated_at": record.updated_at,
            },
        )
        return record

    def get_offer(self, offer_id: str, *, account_id: str, project_id: str) -> OfferRecord | None:
        return self._get(
            "commerce_offers", offer_id, OfferRecord, account_id=account_id, project_id=project_id
        )

    def find_offer_by_url(
        self, url: str, *, source_id: str, account_id: str, project_id: str
    ) -> OfferRecord | None:
        rows = self._list(
            "commerce_offers",
            OfferRecord,
            account_id=account_id,
            project_id=project_id,
            filters={"source_id": source_id, "url": url},
            limit=1,
        )
        return rows[0] if rows else None

    def list_offers(
        self,
        *,
        account_id: str,
        project_id: str,
        product_id: str | None = None,
        source_id: str | None = None,
        limit: int = 100,
    ) -> list[OfferRecord]:
        return self._list(
            "commerce_offers",
            OfferRecord,
            account_id=account_id,
            project_id=project_id,
            filters={"product_id": product_id, "source_id": source_id},
            limit=limit,
        )

    def save_monitor(self, record: MonitorRecord) -> MonitorRecord:
        record.updated_at = utc_now_iso()
        self._save(
            "commerce_monitors",
            record,
            {
                "account_id": record.account_id,
                "project_id": record.project_id,
                "job_id": record.job_id,
                "status": record.status,
                "updated_at": record.updated_at,
            },
        )
        return record

    def get_monitor(
        self, monitor_id: str, *, account_id: str, project_id: str
    ) -> MonitorRecord | None:
        return self._get(
            "commerce_monitors",
            monitor_id,
            MonitorRecord,
            account_id=account_id,
            project_id=project_id,
        )

    def find_monitor_by_job(
        self, job_id: str, *, account_id: str, project_id: str
    ) -> MonitorRecord | None:
        rows = self._list(
            "commerce_monitors",
            MonitorRecord,
            account_id=account_id,
            project_id=project_id,
            filters={"job_id": job_id},
            limit=1,
        )
        return rows[0] if rows else None

    def list_monitors(
        self, *, account_id: str, project_id: str, limit: int = 100
    ) -> list[MonitorRecord]:
        return self._list(
            "commerce_monitors",
            MonitorRecord,
            account_id=account_id,
            project_id=project_id,
            limit=limit,
        )

    def save_observation(self, record: ObservationRecord) -> ObservationRecord:
        self._save(
            "commerce_observations",
            record,
            {
                "account_id": record.account_id,
                "project_id": record.project_id,
                "source_id": record.source_id,
                "product_id": record.product_id,
                "offer_id": record.offer_id,
                "monitor_id": record.monitor_id,
                "job_id": record.job_id,
                "run_id": record.run_id,
                "captured_at": record.captured_at,
            },
        )
        return record

    def get_observation(
        self, observation_id: str, *, account_id: str, project_id: str
    ) -> ObservationRecord | None:
        return self._get(
            "commerce_observations",
            observation_id,
            ObservationRecord,
            account_id=account_id,
            project_id=project_id,
        )

    def list_observations(
        self,
        *,
        account_id: str,
        project_id: str,
        product_id: str | None = None,
        offer_id: str | None = None,
        monitor_id: str | None = None,
        limit: int = 100,
    ) -> list[ObservationRecord]:
        return self._list(
            "commerce_observations",
            ObservationRecord,
            account_id=account_id,
            project_id=project_id,
            filters={
                "product_id": product_id,
                "offer_id": offer_id,
                "monitor_id": monitor_id,
            },
            order_by="captured_at DESC",
            limit=limit,
        )

    def latest_observation(
        self, offer_id: str, *, account_id: str, project_id: str
    ) -> ObservationRecord | None:
        rows = self.list_observations(
            account_id=account_id, project_id=project_id, offer_id=offer_id, limit=1
        )
        return rows[0] if rows else None

    def save_change_event(self, record: ChangeEventRecord) -> ChangeEventRecord:
        rows = self._list(
            "commerce_change_events",
            ChangeEventRecord,
            account_id=record.account_id,
            project_id=record.project_id,
            filters={"dedupe_key": record.dedupe_key},
            order_by="changed_at DESC",
            limit=1,
        )
        if rows:
            return rows[0]
        self._save(
            "commerce_change_events",
            record,
            {
                "account_id": record.account_id,
                "project_id": record.project_id,
                "product_id": record.product_id,
                "offer_id": record.offer_id,
                "monitor_id": record.monitor_id,
                "event_type": record.event_type,
                "changed_at": record.changed_at,
                "dedupe_key": record.dedupe_key,
            },
        )
        return record

    def get_change_event(
        self, event_id: str, *, account_id: str, project_id: str
    ) -> ChangeEventRecord | None:
        return self._get(
            "commerce_change_events",
            event_id,
            ChangeEventRecord,
            account_id=account_id,
            project_id=project_id,
        )

    def list_change_events(
        self,
        *,
        account_id: str,
        project_id: str,
        product_id: str | None = None,
        offer_id: str | None = None,
        monitor_id: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[ChangeEventRecord]:
        return self._list(
            "commerce_change_events",
            ChangeEventRecord,
            account_id=account_id,
            project_id=project_id,
            filters={
                "product_id": product_id,
                "offer_id": offer_id,
                "monitor_id": monitor_id,
                "event_type": event_type,
            },
            order_by="changed_at DESC",
            limit=limit,
        )

    def save_product_match(self, record: ProductMatchRecord) -> ProductMatchRecord:
        record.updated_at = utc_now_iso()
        self._save(
            "commerce_product_matches",
            record,
            {
                "account_id": record.account_id,
                "project_id": record.project_id,
                "left_product_id": record.left_product_id,
                "right_product_id": record.right_product_id,
                "status": record.status.value,
                "updated_at": record.updated_at,
            },
        )
        return record

    def get_product_match(
        self, match_id: str, *, account_id: str, project_id: str
    ) -> ProductMatchRecord | None:
        return self._get(
            "commerce_product_matches",
            match_id,
            ProductMatchRecord,
            account_id=account_id,
            project_id=project_id,
        )

    def list_product_matches(
        self, *, account_id: str, project_id: str, limit: int = 100
    ) -> list[ProductMatchRecord]:
        return self._list(
            "commerce_product_matches",
            ProductMatchRecord,
            account_id=account_id,
            project_id=project_id,
            limit=limit,
        )

    def delete_record(
        self, resource: str, record_id: str, *, account_id: str, project_id: str
    ) -> bool:
        table = _SQLITE_TABLES.get(resource)
        if not table:
            raise ValueError(f"Unsupported commerce resource: {resource}")
        with self._connect() as conn:
            cursor = conn.execute(
                f"DELETE FROM {table} WHERE id = %s AND account_id = %s AND project_id = %s",
                (record_id, account_id, project_id),
            )
            return cursor.rowcount > 0


def domain_repository_for_store(store: Any) -> CommerceRepository:
    dsn = getattr(store, "dsn", None)
    if dsn:
        return PostgresDomainRepository(str(dsn))
    path = getattr(store, "path", None)
    return SQLiteDomainRepository(path or os.getenv("COMMERCELENS_JOBS_DB", "commercelens_jobs.db"))


def domain_repository_from_env() -> CommerceRepository:
    backend = os.getenv("COMMERCELENS_STORE_BACKEND", "sqlite").lower()
    if backend == "postgres":
        dsn = os.getenv("COMMERCELENS_DATABASE_URL") or os.getenv("DATABASE_URL")
        if not dsn:
            raise RuntimeError(
                "COMMERCELENS_STORE_BACKEND=postgres requires COMMERCELENS_DATABASE_URL or DATABASE_URL."
            )
        return PostgresDomainRepository(dsn)
    return SQLiteDomainRepository(os.getenv("COMMERCELENS_JOBS_DB", "commercelens_jobs.db"))
