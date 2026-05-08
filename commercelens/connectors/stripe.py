from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

from commercelens.jobs.models import AccountStatus, BillingPlan


def verify_stripe_signature(
    payload: bytes,
    signature_header: str,
    webhook_secret: str,
    tolerance_seconds: int = 300,
    now: int | None = None,
) -> None:
    parts = {
        key: value
        for item in signature_header.split(",")
        if "=" in item
        for key, value in [item.split("=", 1)]
    }
    timestamp = int(parts.get("t", "0"))
    received = parts.get("v1")
    if not timestamp or not received:
        raise ValueError("Missing Stripe signature timestamp or v1 digest.")

    now = now or int(time.time())
    if abs(now - timestamp) > tolerance_seconds:
        raise ValueError("Stripe webhook signature timestamp is outside tolerance.")

    signed_payload = f"{timestamp}.{payload.decode('utf-8')}".encode("utf-8")
    expected = hmac.new(webhook_secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise ValueError("Invalid Stripe webhook signature.")


def parse_stripe_event(payload: bytes) -> dict[str, Any]:
    event = json.loads(payload.decode("utf-8"))
    if not isinstance(event, dict) or not event.get("type"):
        raise ValueError("Invalid Stripe event payload.")
    return event


def _status_from_subscription(stripe_status: str | None) -> AccountStatus:
    if stripe_status == "active":
        return AccountStatus.active
    if stripe_status == "trialing":
        return AccountStatus.trialing
    return AccountStatus.suspended


def _plan_from_metadata(metadata: dict[str, Any]) -> BillingPlan | None:
    raw_plan = metadata.get("billing_plan") or metadata.get("plan")
    if not raw_plan:
        return None
    return BillingPlan(str(raw_plan))


def apply_subscription_event(store: Any, event: dict[str, Any]) -> dict[str, Any]:
    event_type = str(event.get("type"))
    subscription = (event.get("data") or {}).get("object") or {}
    metadata = subscription.get("metadata") or {}
    account_id = metadata.get("account_id")
    if not account_id:
        return {"applied": False, "reason": "missing_account_id"}

    account = store.get_account(account_id)
    if not account:
        return {"applied": False, "reason": "account_not_found", "account_id": account_id}

    if event_type == "customer.subscription.deleted":
        account.status = AccountStatus.suspended
    else:
        plan = _plan_from_metadata(metadata)
        if plan is not None:
            account.billing_plan = plan
        account.status = _status_from_subscription(subscription.get("status"))

    account.metadata["stripe_customer_id"] = subscription.get("customer")
    account.metadata["stripe_subscription_id"] = subscription.get("id")
    account.metadata["stripe_subscription_status"] = subscription.get("status")
    store.save_account(account)
    return {
        "applied": True,
        "account_id": account.id,
        "billing_plan": account.billing_plan.value,
        "status": account.status.value,
    }
