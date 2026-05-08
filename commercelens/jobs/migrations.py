from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PostgresMigration:
    id: str
    description: str
    statements: tuple[str, ...]


POSTGRES_MIGRATIONS: tuple[PostgresMigration, ...] = (
    PostgresMigration(
        id="0001_hosted_core",
        description="Create hosted accounts, jobs, runs, API keys, usage, and extraction records.",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                id TEXT PRIMARY KEY,
                payload JSONB NOT NULL,
                name TEXT NOT NULL,
                owner TEXT,
                billing_plan TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_accounts_status ON accounts(status)",
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                payload JSONB NOT NULL,
                name TEXT NOT NULL,
                slug TEXT,
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_projects_account_id ON projects(account_id)",
            """
            CREATE TABLE IF NOT EXISTS account_members (
                id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                payload JSONB NOT NULL,
                email TEXT NOT NULL,
                role TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_members_account_id ON account_members(account_id)",
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_members_account_email
            ON account_members(account_id, email)
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_jobs (
                id TEXT PRIMARY KEY,
                payload JSONB NOT NULL,
                status TEXT NOT NULL,
                next_run_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ NOT NULL,
                account_id TEXT,
                project_id TEXT,
                owner TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_jobs_status_next_run ON monitoring_jobs(status, next_run_at)",
            "CREATE INDEX IF NOT EXISTS idx_jobs_account_project ON monitoring_jobs(account_id, project_id)",
            """
            CREATE TABLE IF NOT EXISTS job_runs (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL REFERENCES monitoring_jobs(id) ON DELETE CASCADE,
                payload JSONB NOT NULL,
                status TEXT NOT NULL,
                started_at TIMESTAMPTZ,
                finished_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL,
                account_id TEXT,
                project_id TEXT,
                owner TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_runs_job_id ON job_runs(job_id)",
            "CREATE INDEX IF NOT EXISTS idx_runs_status ON job_runs(status)",
            "CREATE INDEX IF NOT EXISTS idx_runs_account_project ON job_runs(account_id, project_id)",
            """
            CREATE TABLE IF NOT EXISTS api_keys (
                id TEXT PRIMARY KEY,
                payload JSONB NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                token_prefix TEXT NOT NULL,
                disabled BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL,
                account_id TEXT,
                project_id TEXT,
                owner TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_api_keys_account_project ON api_keys(account_id, project_id)",
            """
            CREATE TABLE IF NOT EXISTS usage_events (
                id TEXT PRIMARY KEY,
                metric TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                payload JSONB NOT NULL,
                account_id TEXT,
                project_id TEXT,
                owner TEXT,
                api_key_id TEXT,
                job_id TEXT,
                run_id TEXT,
                route TEXT,
                status_code INTEGER,
                created_at TIMESTAMPTZ NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_usage_created_at ON usage_events(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_usage_metric ON usage_events(metric)",
            "CREATE INDEX IF NOT EXISTS idx_usage_account_project ON usage_events(account_id, project_id)",
            """
            CREATE TABLE IF NOT EXISTS extraction_records (
                id TEXT PRIMARY KEY,
                payload JSONB NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                url TEXT,
                account_id TEXT,
                project_id TEXT,
                owner TEXT,
                api_key_id TEXT,
                confidence DOUBLE PRECISION,
                product_count INTEGER,
                created_at TIMESTAMPTZ NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_extractions_created_at ON extraction_records(created_at)",
            """
            CREATE INDEX IF NOT EXISTS idx_extractions_account_project
            ON extraction_records(account_id, project_id)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_extractions_kind_status
            ON extraction_records(kind, status)
            """,
        ),
    ),
)


def ensure_migration_table(conn: Any) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS commercelens_schema_migrations (
            id TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def applied_postgres_migration_ids(conn: Any) -> set[str]:
    ensure_migration_table(conn)
    rows = conn.execute("SELECT id FROM commercelens_schema_migrations").fetchall()
    return {row["id"] for row in rows}


def run_postgres_migrations(conn: Any) -> list[str]:
    ensure_migration_table(conn)
    applied = applied_postgres_migration_ids(conn)
    applied_now: list[str] = []

    for migration in POSTGRES_MIGRATIONS:
        if migration.id in applied:
            continue
        for statement in migration.statements:
            conn.execute(statement)
        conn.execute(
            """
            INSERT INTO commercelens_schema_migrations (id, description)
            VALUES (%s, %s)
            """,
            (migration.id, migration.description),
        )
        applied_now.append(migration.id)

    return applied_now


def migrate_postgres_dsn(dsn: str) -> list[str]:
    try:
        import psycopg  # type: ignore[import-not-found]
        from psycopg.rows import dict_row  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - optional dependency path
        raise RuntimeError("Postgres migrations require `pip install commercelens[postgres]`.") from exc

    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        return run_postgres_migrations(conn)
