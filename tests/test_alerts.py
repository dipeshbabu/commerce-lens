from __future__ import annotations

from commercelens.alerts.delivery import build_alert_payload, deliver_alert
from commercelens.alerts.rules import (
    AlertCondition,
    AlertDestination,
    AlertDestinationType,
    AlertEvent,
    AlertRule,
    event_from_change,
    rule_matches_change,
)
from commercelens.storage.price_store import PriceChange


def make_change(change_type: str = "price_drop", delta_percent: float = -15.0) -> PriceChange:
    return PriceChange(
        product_key="brand::sample-product",
        source_url="https://example.com/products/sample",
        name="Sample Product",
        previous_amount=100.0,
        current_amount=85.0,
        currency="USD",
        delta=-15.0,
        delta_percent=delta_percent,
        previous_availability="in_stock",
        current_availability="in_stock",
        change_type=change_type,
        changed_at="2026-01-01T00:00:00Z",
    )


def test_percent_drop_rule_matches_change() -> None:
    rule = AlertRule(name="drop", condition=AlertCondition.PERCENT_DROP_AT_LEAST, threshold=10)
    assert rule_matches_change(rule, make_change())


def test_percent_drop_rule_does_not_match_small_change() -> None:
    rule = AlertRule(name="drop", condition=AlertCondition.PERCENT_DROP_AT_LEAST, threshold=20)
    assert not rule_matches_change(rule, make_change(delta_percent=-5.0))


def test_back_in_stock_rule_matches() -> None:
    rule = AlertRule(name="stock", condition=AlertCondition.BACK_IN_STOCK)
    assert rule_matches_change(rule, make_change(change_type="back_in_stock"))


def test_event_payload_contains_key_fields() -> None:
    rule = AlertRule(name="drop", condition=AlertCondition.PRICE_DROP)
    event = event_from_change(rule, make_change())
    payload = build_alert_payload(event)
    assert "Sample Product" in payload["title"]
    assert "Current price" in payload["text"]
    assert payload["event"]["product_key"] == "brand::sample-product"


def test_dry_run_delivery_returns_payload() -> None:
    event = AlertEvent(
        rule_name="drop",
        condition=AlertCondition.PRICE_DROP,
        product_key="brand::sample-product",
        current_amount=85.0,
        currency="USD",
        changed_at="2026-01-01T00:00:00Z",
    )
    report = deliver_alert(
        event,
        [AlertDestination(type=AlertDestinationType.STDOUT)],
        dry_run=True,
    )
    assert report.results[0].ok
    assert report.results[0].dry_run
    assert report.results[0].payload is not None


def test_webhook_delivery_rejects_private_destinations() -> None:
    event = AlertEvent(
        rule_name="drop",
        condition=AlertCondition.PRICE_DROP,
        product_key="brand::sample-product",
        current_amount=85.0,
        currency="USD",
        changed_at="2026-01-01T00:00:00Z",
    )

    report = deliver_alert(
        event,
        [
            AlertDestination(
                type=AlertDestinationType.WEBHOOK,
                url="http://127.0.0.1/internal",
            )
        ],
    )

    assert not report.results[0].ok
    assert "non-public address space" in (report.results[0].message or "")
