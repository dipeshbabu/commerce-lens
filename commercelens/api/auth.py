from __future__ import annotations

import os

from fastapi import Header, HTTPException, status

from commercelens.jobs.models import ApiKeyRecord
from commercelens.jobs.store import JobStore


def get_job_store():
    backend = os.getenv("COMMERCELENS_STORE_BACKEND", "sqlite").lower()
    if backend == "postgres":
        from commercelens.jobs.postgres_store import PostgresJobStore

        dsn = os.getenv("COMMERCELENS_DATABASE_URL") or os.getenv("DATABASE_URL")
        if not dsn:
            raise RuntimeError("COMMERCELENS_STORE_BACKEND=postgres requires COMMERCELENS_DATABASE_URL or DATABASE_URL.")
        return PostgresJobStore(dsn)
    return JobStore(os.getenv("COMMERCELENS_JOBS_DB", "commercelens_jobs.db"))


def require_api_key(x_api_key: str | None = Header(default=None)) -> ApiKeyRecord | None:
    """Optional hosted API key guard.

    Authentication is disabled unless `COMMERCELENS_REQUIRE_API_KEY=true` is set.
    This keeps the local developer workflow frictionless while giving hosted deployments
    a clean security boundary.

    When authentication is enabled, the returned API key record carries account/project
    context that API handlers can use for tenant-scoped reads, writes, and usage metering.
    """
    if os.getenv("COMMERCELENS_REQUIRE_API_KEY", "false").lower() not in {"1", "true", "yes"}:
        return None
    if not x_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing X-API-Key header.")
    key = get_job_store().verify_api_key(x_api_key)
    if not key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key.")
    return key
