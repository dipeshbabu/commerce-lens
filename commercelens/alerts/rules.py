from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, HttpUrl

from commercelens.storage.price_store import PriceChange, ProductSnapshot


class AlertCondition(str, Enum):
    ANY_CHANGE = "any_change"
    PRICE_DROP = "price_drop"
    PRICE_INCREASE = "price_increase"
    BACK_IN_STOCK = "back_in_stock"
    AVAILABILITY_CHANGE = "availability_change"
    PRICE_BELOW = "price_below"
    PRICE_ABOVE = "price_above"
    PERCENT_DROP_AT_LEAST = "percent_drop_at_least"
    PERCENT_INCREASE_AT_LEAST = "percent_increase_at_least"


class AlertDestinationType(str, Enum):
    WEBHOOK = "webhook"
    SLACK = "slack"
    EMAIL = "email"
    FILE = "file"
    STDOUT = "stdout"


class AlertDestination(BaseModel):
    type: AlertDestinationType = AlertDestinationType.STDOUT
    url: HttpUrl | None = None
    email_to: str | None = None
    file_path: str | None = None
    enabled: bool = True


class AlertRule(BaseModel):
    name: str
    condition: AlertCondition = AlertCondition.ANY_CHANGE
    threshold: float | None = None
    currency: str | None = None
    product_keys: list[str] | None = None
    urls: list[str] | None = None
    destinations: list[AlertDestination] = Field(default_factory=lambda: [AlertDestination()])
    enabled: bool = True


class AlertEvent(BaseModel):
    rule_name: str
    condition: AlertCondition
    product_key: str
    url: str | None = None
    name: str | None = None
    previous_amount: float | None = None
    current_amount: float | None = None
    currency: str | None = None
    delta: float | None = None
    delta_percent: float | None = None
    previous_availability: str | None = None
    current_availability: str | None = None
    change_type: str | None = None
    changed_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


def rule_matches_change(rule: AlertRule, change: PriceChange) -> bool:
    if not rule.enabled:
        return False
    if rule.product_keys and change.product_key not in rule.product_keys:
        return False
    if rule.urls and change.source_url not in rule.urls:
        return False
    if rule.currency and change.currency and rule.currency.upper() != change.currency.upper():
        return False

    condition = rule.condition
    if condition == AlertCondition.ANY_CHANGE:
        return True
    if condition == AlertCondition.PRICE_DROP:
        return change.change_type == "price_drop"
    if condition == AlertCondition.PRICE_INCREASE:
        return change.change_type == "price_increase"
    if condition == AlertCondition.BACK_IN_STOCK:
        return change.change_type == "back_in_stock"
    if condition == AlertCondition.AVAILABILITY_CHANGE:
        return change.change_type in {"availability_change", "back_in_stock", "price_and_availability_change"}
    if condition == AlertCondition.PRICE_BELOW:
        return rule.threshold is not None and change.current_amount is not None and change.current_amount <= rule.threshold
    if condition == AlertCondition.PRICE_ABOVE:
        return rule.threshold is not None and change.current_amount is not None and change.current_amount >= rule.threshold
    if condition == AlertCondition.PERCENT_DROP_AT_LEAST:
        return (
            rule.threshold is not None
            and change.delta_percent is not None
            and change.delta_percent <= -abs(rule.threshold)
        )
    if condition == AlertCondition.PERCENT_INCREASE_AT_LEAST:
        return (
            rule.threshold is not None
            and change.delta_percent is not None
            and change.delta_percent >= abs(rule.threshold)
        )
    return False


def event_from_change(rule: AlertRule, change: PriceChange) -> AlertEvent:
    return AlertEvent(
        rule_name=rule.name,
        condition=rule.condition,
        product_key=change.product_key,
        url=change.source_url,
        name=change.name,
        previous_amount=change.previous_amount,
        current_amount=change.current_amount,
        currency=change.currency,
        delta=change.delta,
        delta_percent=change.delta_percent,
        previous_availability=change.previous_availability,
        current_availability=change.current_availability,
        change_type=change.change_type,
        changed_at=change.changed_at,
    )


def snapshot_triggered_threshold(rule: AlertRule, snapshot: ProductSnapshot) -> AlertEvent | None:
    if not rule.enabled:
        return None
    if rule.product_keys and snapshot.product_key not in rule.product_keys:
        return None
    if rule.urls and snapshot.source_url not in rule.urls and snapshot.canonical_url not in rule.urls:
        return None
    if rule.currency and snapshot.currency and rule.currency.upper() != snapshot.currency.upper():
        return None

    threshold = rule.threshold
    if threshold is None or snapshot.amount is None:
        return None

    matched = False
    if rule.condition == AlertCondition.PRICE_BELOW:
        matched = snapshot.amount <= threshold
    elif rule.condition == AlertCondition.PRICE_ABOVE:
        matched = snapshot.amount >= threshold

    if not matched:
        return None

    return AlertEvent(
        rule_name=rule.name,
        condition=rule.condition,
        product_key=snapshot.product_key,
        url=snapshot.source_url,
        name=snapshot.name,
        current_amount=snapshot.amount,
        currency=snapshot.currency,
        current_availability=snapshot.availability,
        changed_at=snapshot.captured_at,
        change_type="threshold_match",
    )
