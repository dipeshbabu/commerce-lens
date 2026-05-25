from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from commercelens.api.main import app
from commercelens.connectors.stripe import create_checkout_session, verify_stripe_signature
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


def test_create_checkout_session_encodes_subscription_metadata() -> None:
    captured: dict[str, bytes] = {}

    def fake_post(encoded: bytes) -> dict:
        captured["encoded"] = encoded
        return {"id": "cs_test", "url": "https://checkout.stripe.test/session"}

    session = create_checkout_session(
        secret_key="sk_test",
        price_id="price_123",
        success_url="https://app.test/success",
        cancel_url="https://app.test/cancel",
        account_id="acct_123",
        billing_plan=BillingPlan.team,
        customer_email="owner@app.test",
        trial_days=14,
        http_post=fake_post,
    )

    encoded = captured["encoded"].decode("utf-8")
    assert session["id"] == "cs_test"
    assert "subscription_data%5Bmetadata%5D%5Baccount_id%5D=acct_123" in encoded
    assert "subscription_data%5Bmetadata%5D%5Bbilling_plan%5D=team" in encoded
    assert "subscription_data%5Btrial_period_days%5D=14" in encoded


def test_stripe_checkout_endpoint_creates_session(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("COMMERCELENS_ADMIN_TOKEN", "secret")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setenv("COMMERCELENS_JOBS_DB", str(tmp_path / "jobs.db"))
    store = JobStore(tmp_path / "jobs.db")
    account = store.create_account(AccountCreate(name="Acme", owner="owner@acme.test"))

    def fake_create_checkout_session(**kwargs) -> dict:
        assert kwargs["account_id"] == account.id
        assert kwargs["billing_plan"] == BillingPlan.team
        return {"id": "cs_test", "url": "https://checkout.stripe.test/session"}

    monkeypatch.setattr("commercelens.api.main.create_checkout_session", fake_create_checkout_session)
    client = TestClient(app)

    response = client.post(
        "/v1/billing/stripe/checkout-session",
        headers={"X-Admin-Token": "secret"},
        json={
            "account_id": account.id,
            "price_id": "price_123",
            "success_url": "https://app.test/success",
            "cancel_url": "https://app.test/cancel",
            "billing_plan": "team",
        },
    )

    assert response.status_code == 200
    assert response.json()["url"] == "https://checkout.stripe.test/session"
    updated = JobStore(tmp_path / "jobs.db").get_account(account.id)
    assert updated is not None
    assert updated.metadata["stripe_checkout_session_id"] == "cs_test"
