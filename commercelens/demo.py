from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from commercelens.alerts.config import MonitorConfig, MonitorTarget
from commercelens.alerts.rules import AlertCondition, AlertRule
from commercelens.jobs.models import (
    AccountRecord,
    AccountStatus,
    ApiKeyCreate,
    ApiKeyCreateResult,
    BillingPlan,
    ExtractionCreate,
    ExtractionKind,
    ExtractionStatus,
    JobRun,
    MemberRecord,
    MemberRole,
    MonitoringJobCreate,
    ProjectRecord,
    RunStatus,
    UsageEvent,
    UsageMetric,
)
from commercelens.jobs.store import JobStore


DEMO_ACCOUNT_ID = "acct_demo"
DEMO_PROJECT_ID = "proj_competitor_watch"


class DemoProduct(TypedDict):
    url: str
    name: str
    brand: str
    amount: float
    currency: str
    availability: str
    confidence: float


def seed_demo_workspace(store: JobStore) -> dict:
    """Seed a realistic customer workspace for demos and local portal testing."""
    account = store.save_account(
        AccountRecord(
            id=DEMO_ACCOUNT_ID,
            name="Northstar Outfitters",
            owner="ops@northstar.example",
            billing_plan=BillingPlan.team,
            status=AccountStatus.trialing,
            metadata={"segment": "dtc apparel", "demo": True},
        )
    )
    project = store.save_project(
        ProjectRecord(
            id=DEMO_PROJECT_ID,
            account_id=DEMO_ACCOUNT_ID,
            name="Competitor Price Watch",
            slug="competitor-price-watch",
            metadata={"demo": True},
        )
    )
    store.save_member(
        MemberRecord(
            account_id=DEMO_ACCOUNT_ID,
            email="pricing@northstar.example",
            role=MemberRole.owner,
            name="Pricing Lead",
        )
    )
    key_result = store.create_api_key(
        ApiKeyCreate(
            name="demo portal key",
            owner=account.owner,
            account_id=DEMO_ACCOUNT_ID,
            project_id=DEMO_PROJECT_ID,
            billing_plan=BillingPlan.team,
            scopes=["*"],
            monthly_domain_quotas={"example.com": 5000, "competitor.example": 2500, "*": 500},
        )
    )
    config = MonitorConfig(
        db_path="demo_prices.db",
        targets=[
            MonitorTarget(url="https://competitor.example/products/alpine-shell", tags=["jackets"]),
            MonitorTarget(url="https://competitor.example/products/trail-pant", tags=["pants"]),
            MonitorTarget(url="https://example.com/products/base-layer", tags=["baselayers"]),
        ],
        rules=[
            AlertRule(
                name="major-price-drop",
                condition=AlertCondition.PERCENT_DROP_AT_LEAST,
                threshold=10,
            ),
            AlertRule(name="back-in-stock", condition=AlertCondition.BACK_IN_STOCK),
            AlertRule(name="availability-change", condition=AlertCondition.AVAILABILITY_CHANGE),
        ],
    )
    job = store.create_job(
        MonitoringJobCreate(
            name="Daily competitor watch",
            config=config,
            interval_minutes=1440,
            owner=account.owner,
            account_id=DEMO_ACCOUNT_ID,
            project_id=DEMO_PROJECT_ID,
            tags=["demo", "competitors"],
        )
    )
    succeeded_run = store.save_run(
        JobRun(
            job_id=job.id,
            status=RunStatus.succeeded,
            account_id=DEMO_ACCOUNT_ID,
            project_id=DEMO_PROJECT_ID,
            owner=account.owner,
            event_count=2,
            delivery_count=2,
            warning_count=0,
            duration_ms=1842,
            result={
                "events": [
                    {
                        "product": "Alpine Shell",
                        "change_type": "price_drop",
                        "delta_percent": -12.5,
                    },
                    {"product": "Trail Pant", "change_type": "back_in_stock"},
                ]
            },
        )
    )
    failed_run = store.save_run(
        JobRun(
            job_id=job.id,
            status=RunStatus.failed,
            account_id=DEMO_ACCOUNT_ID,
            project_id=DEMO_PROJECT_ID,
            owner=account.owner,
            warning_count=1,
            duration_ms=902,
            error="competitor.example timed out after 20 seconds",
        )
    )
    for metric, quantity in {
        UsageMetric.product_extract: 148,
        UsageMetric.monitor_run: 12,
        UsageMetric.job_run: 2,
        UsageMetric.alert_event: 2,
        UsageMetric.alert_delivery: 2,
    }.items():
        store.record_usage(
            UsageEvent(
                metric=metric,
                quantity=quantity,
                account_id=DEMO_ACCOUNT_ID,
                project_id=DEMO_PROJECT_ID,
                owner=account.owner,
                api_key_id=key_result.key.id,
                job_id=job.id if metric in {UsageMetric.monitor_run, UsageMetric.job_run} else None,
                run_id=succeeded_run.id if metric != UsageMetric.product_extract else None,
                metadata={"demo": True},
            )
        )
    _record_demo_extractions(store, key_result)
    return {
        "account": account.model_dump(mode="json", exclude_none=True),
        "project": project.model_dump(mode="json", exclude_none=True),
        "api_key": key_result.key.model_dump(mode="json", exclude_none=True),
        "token": key_result.token,
        "portal_path": f"/portal?api_key={key_result.token}",
        "job_id": job.id,
        "run_ids": [succeeded_run.id, failed_run.id],
    }


def seed_demo_workspace_path(path: str | Path) -> dict:
    return seed_demo_workspace(JobStore(path))


def _record_demo_extractions(store: JobStore, key_result: ApiKeyCreateResult) -> None:
    products: list[DemoProduct] = [
        {
            "url": "https://competitor.example/products/alpine-shell",
            "name": "Alpine Shell",
            "brand": "SummitWorks",
            "amount": 139.0,
            "currency": "USD",
            "availability": "in_stock",
            "confidence": 0.93,
        },
        {
            "url": "https://competitor.example/products/trail-pant",
            "name": "Trail Pant",
            "brand": "SummitWorks",
            "amount": 89.0,
            "currency": "USD",
            "availability": "in_stock",
            "confidence": 0.9,
        },
        {
            "url": "https://example.com/products/base-layer",
            "name": "Merino Base Layer",
            "brand": "Northstar",
            "amount": 74.0,
            "currency": "USD",
            "availability": "out_of_stock",
            "confidence": 0.87,
        },
    ]
    for product in products:
        store.record_extraction(
            ExtractionCreate(
                kind=ExtractionKind.product,
                status=ExtractionStatus.succeeded,
                url=product["url"],
                account_id=DEMO_ACCOUNT_ID,
                project_id=DEMO_PROJECT_ID,
                owner="ops@northstar.example",
                api_key_id=key_result.key.id,
                confidence=product["confidence"],
                product_count=1,
                payload={
                    "product": {
                        "name": product["name"],
                        "brand": product["brand"],
                        "price": {"amount": product["amount"], "currency": product["currency"]},
                        "availability": product["availability"],
                    }
                },
                metadata={"demo": True},
            )
        )
    store.record_extraction(
        ExtractionCreate(
            kind=ExtractionKind.listing,
            status=ExtractionStatus.failed,
            url="https://competitor.example/collections/jackets",
            account_id=DEMO_ACCOUNT_ID,
            project_id=DEMO_PROJECT_ID,
            owner="ops@northstar.example",
            api_key_id=key_result.key.id,
            error="Blocked by upstream 403 response",
            metadata={"demo": True, "failure_class": "blocked"},
        )
    )
