from __future__ import annotations

import os
from typing import Mapping

from pydantic import BaseModel, Field


class ProductionCheckItem(BaseModel):
    name: str
    passed: bool
    severity: str = "blocker"
    detail: str


class ProductionPreflightResult(BaseModel):
    passed: bool
    blockers: int = 0
    warnings: int = 0
    checks: list[ProductionCheckItem] = Field(default_factory=list)


def run_production_preflight(env: Mapping[str, str] | None = None) -> ProductionPreflightResult:
    values = env or os.environ
    checks = [
        _check_equal(
            values,
            "COMMERCELENS_ENV",
            "production",
            "Set COMMERCELENS_ENV=production for hosted deployments.",
        ),
        _check_equal(
            values,
            "COMMERCELENS_STORE_BACKEND",
            "postgres",
            "Use Postgres for hosted jobs, usage, keys, and extraction records.",
        ),
        _check_present(
            values,
            "COMMERCELENS_DATABASE_URL",
            "Set COMMERCELENS_DATABASE_URL to the hosted Postgres DSN.",
        ),
        _check_truthy(
            values,
            "COMMERCELENS_REQUIRE_API_KEY",
            "Require API keys before accepting hosted customer traffic.",
        ),
        _check_secret(
            values,
            "COMMERCELENS_ADMIN_TOKEN",
            "Set a long random admin token for operator-only routes.",
            min_length=24,
        ),
        _check_present(
            values,
            "COMMERCELENS_USER_AGENT",
            "Set a clear User-Agent with a contact address for outbound fetches.",
            severity="warning",
        ),
        _check_present(
            values,
            "STRIPE_WEBHOOK_SECRET",
            "Set STRIPE_WEBHOOK_SECRET before enabling paid subscription sync.",
            severity="warning",
        ),
    ]
    blockers = sum(1 for check in checks if not check.passed and check.severity == "blocker")
    warnings = sum(1 for check in checks if not check.passed and check.severity == "warning")
    return ProductionPreflightResult(
        passed=blockers == 0,
        blockers=blockers,
        warnings=warnings,
        checks=checks,
    )


def _check_present(
    env: Mapping[str, str],
    name: str,
    detail: str,
    severity: str = "blocker",
) -> ProductionCheckItem:
    return ProductionCheckItem(
        name=name,
        passed=bool(env.get(name)),
        severity=severity,
        detail=detail,
    )


def _check_equal(
    env: Mapping[str, str],
    name: str,
    expected: str,
    detail: str,
    severity: str = "blocker",
) -> ProductionCheckItem:
    return ProductionCheckItem(
        name=name,
        passed=env.get(name, "").lower() == expected,
        severity=severity,
        detail=detail,
    )


def _check_truthy(
    env: Mapping[str, str],
    name: str,
    detail: str,
    severity: str = "blocker",
) -> ProductionCheckItem:
    return ProductionCheckItem(
        name=name,
        passed=env.get(name, "").lower() in {"1", "true", "yes"},
        severity=severity,
        detail=detail,
    )


def _check_secret(
    env: Mapping[str, str],
    name: str,
    detail: str,
    min_length: int,
    severity: str = "blocker",
) -> ProductionCheckItem:
    value = env.get(name, "")
    return ProductionCheckItem(
        name=name,
        passed=len(value) >= min_length and value.lower() not in {"secret", "changeme", "password"},
        severity=severity,
        detail=detail,
    )
