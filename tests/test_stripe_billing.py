from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from commercelens.api.main import app
from commercelens.connectors.stripe import verify_stripe_signature
from commercelens.jobs.models import AccountCreate, BillingPlan
from commercelens.jobs.store import JobStore


def signed_header(payload: bytes, secret: str, timestamp: int | None = None) -> str:
    timestamp = timestamp or int(time.time())
    digest = hmac.new(secret.encode("utf-8"), f"{timestamp}.{payload.decode('utf-8')}".encode("utf-8"), hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def test_verify_stripe_signature_rejects_bad_digest() -> None:
    payload = b'{"type":"customer.subscription.updated"}'

    with pytest.raises(ValueError, match="Invalid Stripe"):
        verify_stripe_signature(payload, "t=1800000000,v1=bad", "secret", now=1_800_000_000)


def test_stripe_webhook_updates_account_plan(monkeypatch, tmp_path) -> None:
    secret = "whsec_test"
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", secret)
    monkeypatch.setenv("COMMERCELENS_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("COMMERCELENS_JOBS_DB", str(tmp_path / "jobs.db"))
    store = JobStore(tmp_path / "jobs.db")
    account = store.create_account(AccountCreate(name="Acme", billing_plan=BillingPlan.free))
    payload = json.dumps(
        {
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_123",
                    "customer": "cus_123",
                    "status": "active",
                    "metadata": {"account_id": account.id, "billing_plan": "team"},
                }
            },
        },
        separators=(",", ":"),
    ).encode("utf-8")
    client = TestClient(app)

    response = client.post(
        "/v1/billing/stripe/webhook",
        content=payload,
        headers={"Stripe-Signature": signed_header(payload, secret)},
    )

    assert response.status_code == 200
    assert response.json()["applied"] is True
    updated = JobStore(tmp_path / "jobs.db").get_account(account.id)
    assert updated is not None
    assert updated.billing_plan == BillingPlan.team
    assert updated.metadata["stripe_subscription_id"] == "sub_123"
