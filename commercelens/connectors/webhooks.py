from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, HttpUrl

from commercelens.alerts.delivery import build_alert_payload
from commercelens.alerts.rules import AlertEvent


class WebhookEnvelope(BaseModel):
    event_type: str
    api_version: str = "0.6"
    payload: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)


class WebhookSubscription(BaseModel):
    name: str
    url: HttpUrl
    secret: str | None = None
    enabled: bool = True
    event_types: list[str] = Field(default_factory=lambda: ["price.change", "availability.change"])


def alert_event_to_webhook(event: AlertEvent) -> WebhookEnvelope:
    event_type = "price.change"
    if event.change_type in {
        "availability_change",
        "back_in_stock",
        "price_and_availability_change",
    }:
        event_type = "availability.change"
    return WebhookEnvelope(
        event_type=event_type,
        payload=build_alert_payload(event),
        metadata={"source": "commercelens"},
    )
