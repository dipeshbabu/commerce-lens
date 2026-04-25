from __future__ import annotations

import os

from fastapi import Header, HTTPException, status

from commercelens.jobs.store import JobStore


def get_job_store() -> JobStore:
    return JobStore(os.getenv("COMMERCELENS_JOBS_DB", "commercelens_jobs.db"))


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Optional hosted API key guard.

    Authentication is disabled unless `COMMERCELENS_REQUIRE_API_KEY=true` is set.
    This keeps the local developer workflow frictionless while giving hosted deployments
    a clean security boundary.
    """
    if os.getenv("COMMERCELENS_REQUIRE_API_KEY", "false").lower() not in {"1", "true", "yes"}:
        return
    if not x_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing X-API-Key header.")
    key = get_job_store().verify_api_key(x_api_key)
    if not key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key.")
