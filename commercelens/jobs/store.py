from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from commercelens.jobs.models import (
    ApiKeyCreate,
    ApiKeyCreateResult,
    ApiKeyRecord,
    JobRun,
    JobStatus,
    MonitoringJob,
    MonitoringJobCreate,
    MonitoringJobUpdate,
    RunStatus,
    ScheduleKind,
    UsageEvent,
    UsageMetric,
    UsageSummary,
    UsageSummaryItem,
    utc_now_iso,
)


class JobStore:
    def __init__(self, path: str | Path = "commercelens_jobs.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS monitoring_jobs (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL,
                    next_run_at TEXT,
                    updated_at TEXT NOT NULL,
                    account_id TEXT,
                    project_id TEXT,
                    owner TEXT
                )
                """
            )
            self._ensure_column(conn, "monitoring_jobs", "account_id", "TEXT")
            self._ensure_column(conn, "monitoring_jobs", "project_id", "TEXT")
            self._ensure_column(conn, "monitoring_jobs", "owner", "TEXT")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status_next_run ON monitoring_jobs(status, next_run_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_account_project ON monitoring_jobs(account_id, project_id)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS job_runs (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    created_at TEXT NOT NULL,
                    account_id TEXT,
                    project_id TEXT,
                    owner TEXT,
                    FOREIGN KEY(job_id) REFERENCES monitoring_jobs(id)
                )
                """
            )
            self._ensure_column(conn, "job_runs", "account_id", "TEXT")
            self._ensure_column(conn, "job_runs", "project_id", "TEXT")
            self._ensure_column(conn, "job_runs", "owner", "TEXT")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_job_id ON job_runs(job_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_status ON job_runs(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_account_project ON job_runs(account_id, project_id)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS api_keys (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    token_prefix TEXT NOT NULL,
                    disabled INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    account_id TEXT,
                    project_id TEXT,
                    owner TEXT
                )
                """
            )
            self._ensure_column(conn, "api_keys", "account_id", "TEXT")
            self._ensure_column(conn, "api_keys", "project_id", "TEXT")
            self._ensure_column(conn, "api_keys", "owner", "TEXT")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_account_project ON api_keys(account_id, project_id)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS usage_events (
                    id TEXT PRIMARY KEY,
                    metric TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    account_id TEXT,
                    project_id TEXT,
                    owner TEXT,
                    api_key_id TEXT,
                    job_id TEXT,
                    run_id TEXT,
                    route TEXT,
                    status_code INTEGER,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_created_at ON usage_events(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_metric ON usage_events(metric)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_account_project ON usage_events(account_id, project_id)")

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, column_type: str) -> None:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

    def create_job(self, request: MonitoringJobCreate) -> MonitoringJob:
        job = MonitoringJob(**request.model_dump())
        job.next_run_at = self.compute_next_run(job)
        self.save_job(job)
        self.record_usage(
            UsageEvent(
                metric=UsageMetric.api_request,
                account_id=job.account_id,
                project_id=job.project_id,
                owner=job.owner,
                job_id=job.id,
                metadata={"operation": "create_job"},
            )
        )
        return job

    def save_job(self, job: MonitoringJob) -> MonitoringJob:
        job.updated_at = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO monitoring_jobs (id, payload, status, next_run_at, updated_at, account_id, project_id, owner)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    payload=excluded.payload,
                    status=excluded.status,
                    next_run_at=excluded.next_run_at,
                    updated_at=excluded.updated_at,
                    account_id=excluded.account_id,
                    project_id=excluded.project_id,
                    owner=excluded.owner
                """,
                (
                    job.id,
                    job.model_dump_json(exclude_none=True),
                    job.status.value if isinstance(job.status, JobStatus) else job.status,
                    job.next_run_at,
                    job.updated_at,
                    job.account_id,
                    job.project_id,
                    job.owner,
                ),
            )
        return job

    def get_job(self, job_id: str, account_id: str | None = None, project_id: str | None = None) -> MonitoringJob | None:
        query = "SELECT payload FROM monitoring_jobs WHERE id = ?"
        params: list[object] = [job_id]
        query, params = self._add_tenant_filters(query, params, account_id, project_id)
        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
        if not row:
            return None
        return MonitoringJob.model_validate_json(row["payload"])

    def list_jobs(
        self,
        status: JobStatus | None = None,
        limit: int = 100,
        account_id: str | None = None,
        project_id: str | None = None,
    ) -> list[MonitoringJob]:
        query = "SELECT payload FROM monitoring_jobs WHERE 1=1"
        params: list[object] = []
        if status:
            query += " AND status = ?"
            params.append(status.value)
        query, params = self._add_tenant_filters(query, params, account_id, project_id)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [MonitoringJob.model_validate_json(row["payload"]) for row in rows]

    def update_job(
        self,
        job_id: str,
        request: MonitoringJobUpdate,
        account_id: str | None = None,
        project_id: str | None = None,
    ) -> MonitoringJob | None:
        job = self.get_job(job_id, account_id=account_id, project_id=project_id)
        if not job:
            return None
        updates = request.model_dump(exclude_unset=True)
        for key, value in updates.items():
            setattr(job, key, value)
        if job.status == JobStatus.active and ("interval_minutes" in updates or "schedule_kind" in updates or not job.next_run_at):
            job.next_run_at = self.compute_next_run(job)
        if job.status != JobStatus.active:
            job.next_run_at = None
        return self.save_job(job)

    def delete_job(self, job_id: str, account_id: str | None = None, project_id: str | None = None) -> bool:
        query = "DELETE FROM monitoring_jobs WHERE id = ?"
        params: list[object] = [job_id]
        query, params = self._add_tenant_filters(query, params, account_id, project_id)
        with self._connect() as conn:
            cursor = conn.execute(query, params)
        return cursor.rowcount > 0

    def due_jobs(self, now_iso: str | None = None, limit: int = 50) -> list[MonitoringJob]:
        now_iso = now_iso or utc_now_iso()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT payload FROM monitoring_jobs
                WHERE status = ? AND next_run_at IS NOT NULL AND next_run_at <= ?
                ORDER BY next_run_at ASC
                LIMIT ?
                """,
                (JobStatus.active.value, now_iso, limit),
            ).fetchall()
        return [MonitoringJob.model_validate_json(row["payload"]) for row in rows]

    def mark_job_run_started(self, job: MonitoringJob) -> JobRun:
        run = JobRun(
            job_id=job.id,
            status=RunStatus.running,
            started_at=utc_now_iso(),
            account_id=job.account_id,
            project_id=job.project_id,
            owner=job.owner,
        )
        self.save_run(run)
        job.last_run_at = run.started_at
        job.next_run_at = None
        self.save_job(job)
        return run

    def complete_run(self, run: JobRun, result: dict, event_count: int, delivery_count: int, warning_count: int) -> JobRun:
        run.status = RunStatus.succeeded
        run.finished_at = utc_now_iso()
        run.duration_ms = duration_ms(run.started_at, run.finished_at)
        run.result = result
        run.event_count = event_count
        run.delivery_count = delivery_count
        run.warning_count = warning_count
        self.save_run(run)
        self.record_usage(
            UsageEvent(
                metric=UsageMetric.job_run,
                account_id=run.account_id,
                project_id=run.project_id,
                owner=run.owner,
                job_id=run.job_id,
                run_id=run.id,
                metadata={"status": "succeeded", "duration_ms": run.duration_ms},
            )
        )
        if event_count:
            self.record_usage(
                UsageEvent(
                    metric=UsageMetric.alert_event,
                    quantity=event_count,
                    account_id=run.account_id,
                    project_id=run.project_id,
                    owner=run.owner,
                    job_id=run.job_id,
                    run_id=run.id,
                )
            )
        if delivery_count:
            self.record_usage(
                UsageEvent(
                    metric=UsageMetric.alert_delivery,
                    quantity=delivery_count,
                    account_id=run.account_id,
                    project_id=run.project_id,
                    owner=run.owner,
                    job_id=run.job_id,
                    run_id=run.id,
                )
            )
        job = self.get_job(run.job_id)
        if job:
            job.last_error = None
            job.next_run_at = self.compute_next_run(job) if job.status == JobStatus.active else None
            self.save_job(job)
        return run

    def fail_run(self, run: JobRun, error: str) -> JobRun:
        run.status = RunStatus.failed
        run.finished_at = utc_now_iso()
        run.duration_ms = duration_ms(run.started_at, run.finished_at)
        run.error = error
        self.save_run(run)
        self.record_usage(
            UsageEvent(
                metric=UsageMetric.job_run,
                account_id=run.account_id,
                project_id=run.project_id,
                owner=run.owner,
                job_id=run.job_id,
                run_id=run.id,
                metadata={"status": "failed", "error": error, "duration_ms": run.duration_ms},
            )
        )
        job = self.get_job(run.job_id)
        if job:
            job.last_error = error
            job.next_run_at = self.compute_retry_run(job, run.attempt) if job.status == JobStatus.active else None
            self.save_job(job)
        return run

    def save_run(self, run: JobRun) -> JobRun:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO job_runs (id, job_id, payload, status, started_at, finished_at, created_at, account_id, project_id, owner)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    payload=excluded.payload,
                    status=excluded.status,
                    started_at=excluded.started_at,
                    finished_at=excluded.finished_at,
                    account_id=excluded.account_id,
                    project_id=excluded.project_id,
                    owner=excluded.owner
                """,
                (
                    run.id,
                    run.job_id,
                    run.model_dump_json(exclude_none=True),
                    run.status.value if isinstance(run.status, RunStatus) else run.status,
                    run.started_at,
                    run.finished_at,
                    run.created_at,
                    run.account_id,
                    run.project_id,
                    run.owner,
                ),
            )
        return run

    def get_run(self, run_id: str, account_id: str | None = None, project_id: str | None = None) -> JobRun | None:
        query = "SELECT payload FROM job_runs WHERE id = ?"
        params: list[object] = [run_id]
        query, params = self._add_tenant_filters(query, params, account_id, project_id)
        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
        if not row:
            return None
        return JobRun.model_validate_json(row["payload"])

    def list_runs(
        self,
        job_id: str | None = None,
        limit: int = 100,
        account_id: str | None = None,
        project_id: str | None = None,
    ) -> list[JobRun]:
        query = "SELECT payload FROM job_runs WHERE 1=1"
        params: list[object] = []
        if job_id:
            query += " AND job_id = ?"
            params.append(job_id)
        query, params = self._add_tenant_filters(query, params, account_id, project_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [JobRun.model_validate_json(row["payload"]) for row in rows]

    def create_api_key(self, request: ApiKeyCreate) -> ApiKeyCreateResult:
        token = f"cl_{secrets.token_urlsafe(32)}"
        token_hash = hash_token(token)
        key = ApiKeyRecord(
            name=request.name,
            owner=request.owner,
            account_id=request.account_id,
            project_id=request.project_id,
            scopes=request.scopes,
            token_hash=token_hash,
            token_prefix=token[:10],
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO api_keys (id, payload, token_hash, token_prefix, disabled, created_at, account_id, project_id, owner)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    key.id,
                    key.model_dump_json(exclude_none=True),
                    key.token_hash,
                    key.token_prefix,
                    0,
                    key.created_at,
                    key.account_id,
                    key.project_id,
                    key.owner,
                ),
            )
        return ApiKeyCreateResult(key=key, token=token)

    def verify_api_key(self, token: str) -> ApiKeyRecord | None:
        token_hash = hash_token(token)
        with self._connect() as conn:
            row = conn.execute("SELECT payload FROM api_keys WHERE token_hash = ? AND disabled = 0", (token_hash,)).fetchone()
        if not row:
            return None
        key = ApiKeyRecord.model_validate_json(row["payload"])
        key.last_used_at = utc_now_iso()
        self.save_api_key(key)
        return key

    def save_api_key(self, key: ApiKeyRecord) -> ApiKeyRecord:
        with self._connect() as conn:
            conn.execute(
                "UPDATE api_keys SET payload = ?, disabled = ?, account_id = ?, project_id = ?, owner = ? WHERE id = ?",
                (key.model_dump_json(exclude_none=True), 1 if key.disabled else 0, key.account_id, key.project_id, key.owner, key.id),
            )
        return key

    def record_usage(self, event: UsageEvent) -> UsageEvent:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO usage_events (
                    id, metric, quantity, payload, account_id, project_id, owner, api_key_id,
                    job_id, run_id, route, status_code, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.metric.value if isinstance(event.metric, UsageMetric) else event.metric,
                    event.quantity,
                    event.model_dump_json(exclude_none=True),
                    event.account_id,
                    event.project_id,
                    event.owner,
                    event.api_key_id,
                    event.job_id,
                    event.run_id,
                    event.route,
                    event.status_code,
                    event.created_at,
                ),
            )
        return event

    def list_usage_events(
        self,
        account_id: str | None = None,
        project_id: str | None = None,
        metric: UsageMetric | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 100,
    ) -> list[UsageEvent]:
        query = "SELECT payload FROM usage_events WHERE 1=1"
        params: list[object] = []
        query, params = self._add_tenant_filters(query, params, account_id, project_id)
        if metric:
            query += " AND metric = ?"
            params.append(metric.value)
        if since:
            query += " AND created_at >= ?"
            params.append(since)
        if until:
            query += " AND created_at <= ?"
            params.append(until)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [UsageEvent.model_validate_json(row["payload"]) for row in rows]

    def usage_summary(
        self,
        account_id: str | None = None,
        project_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> UsageSummary:
        query = "SELECT metric, SUM(quantity) AS quantity FROM usage_events WHERE 1=1"
        params: list[object] = []
        query, params = self._add_tenant_filters(query, params, account_id, project_id)
        if since:
            query += " AND created_at >= ?"
            params.append(since)
        if until:
            query += " AND created_at <= ?"
            params.append(until)
        query += " GROUP BY metric ORDER BY metric ASC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        items = [UsageSummaryItem(metric=UsageMetric(row["metric"]), quantity=int(row["quantity"] or 0)) for row in rows]
        return UsageSummary(
            account_id=account_id,
            project_id=project_id,
            since=since,
            until=until,
            total_quantity=sum(item.quantity for item in items),
            items=items,
        )

    def compute_next_run(self, job: MonitoringJob) -> str | None:
        if job.schedule_kind == ScheduleKind.manual or job.status != JobStatus.active:
            return None
        base = datetime.now(timezone.utc)
        return (base + timedelta(minutes=job.interval_minutes)).replace(microsecond=0).isoformat()

    def compute_retry_run(self, job: MonitoringJob, attempt: int) -> str | None:
        if attempt > job.max_retries:
            return self.compute_next_run(job)
        delay = job.retry_backoff_seconds * max(1, attempt)
        return (datetime.now(timezone.utc) + timedelta(seconds=delay)).replace(microsecond=0).isoformat()

    def _add_tenant_filters(
        self,
        query: str,
        params: list[object],
        account_id: str | None = None,
        project_id: str | None = None,
    ) -> tuple[str, list[object]]:
        if account_id:
            query += " AND account_id = ?"
            params.append(account_id)
        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)
        return query, params


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def duration_ms(started_at: str | None, finished_at: str | None) -> int | None:
    if not started_at or not finished_at:
        return None
    start = datetime.fromisoformat(started_at)
    finish = datetime.fromisoformat(finished_at)
    return int((finish - start).total_seconds() * 1000)


def dumps_pretty(payload: object) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, default=str)
