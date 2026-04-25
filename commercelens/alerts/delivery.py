from __future__ import annotations

import json
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field

from commercelens.alerts.rules import AlertDestination, AlertDestinationType, AlertEvent


class DeliveryResult(BaseModel):
    destination_type: AlertDestinationType
    ok: bool
    dry_run: bool = False
    status_code: int | None = None
    message: str | None = None
    payload: dict[str, Any] | None = None


class AlertDeliveryReport(BaseModel):
    event: AlertEvent
    results: list[DeliveryResult] = Field(default_factory=list)


def build_alert_payload(event: AlertEvent) -> dict[str, Any]:
    title = f"CommerceLens alert: {event.name or event.product_key}"
    pieces = [f"Rule: {event.rule_name}", f"Condition: {event.condition.value}"]
    if event.current_amount is not None:
        price = f"{event.current_amount} {event.currency or ''}".strip()
        pieces.append(f"Current price: {price}")
    if event.previous_amount is not None:
        previous = f"{event.previous_amount} {event.currency or ''}".strip()
        pieces.append(f"Previous price: {previous}")
    if event.delta_percent is not None:
        pieces.append(f"Delta: {event.delta_percent:.2f}%")
    if event.current_availability:
        pieces.append(f"Availability: {event.current_availability}")
    if event.url:
        pieces.append(f"URL: {event.url}")

    text = "\n".join(pieces)
    return {
        "title": title,
        "text": text,
        "event": event.model_dump(mode="json", exclude_none=True),
    }


def deliver_alert(
    event: AlertEvent,
    destinations: list[AlertDestination],
    dry_run: bool = False,
) -> AlertDeliveryReport:
    report = AlertDeliveryReport(event=event)
    payload = build_alert_payload(event)
    for destination in destinations:
        if not destination.enabled:
            continue
        report.results.append(_deliver_one(destination, payload, dry_run=dry_run))
    return report


def _deliver_one(
    destination: AlertDestination,
    payload: dict[str, Any],
    dry_run: bool = False,
) -> DeliveryResult:
    if dry_run:
        return DeliveryResult(
            destination_type=destination.type,
            ok=True,
            dry_run=True,
            message="Dry run: alert was not delivered.",
            payload=payload,
        )

    if destination.type == AlertDestinationType.STDOUT:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return DeliveryResult(destination_type=destination.type, ok=True, message="Printed to stdout.")

    if destination.type == AlertDestinationType.FILE:
        if not destination.file_path:
            return DeliveryResult(destination_type=destination.type, ok=False, message="Missing file_path.")
        path = Path(destination.file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return DeliveryResult(destination_type=destination.type, ok=True, message=f"Wrote alert to {path}.")

    if destination.type in {AlertDestinationType.WEBHOOK, AlertDestinationType.SLACK}:
        if not destination.url:
            return DeliveryResult(destination_type=destination.type, ok=False, message="Missing url.")
        outbound = payload
        if destination.type == AlertDestinationType.SLACK:
            outbound = {"text": payload["text"], "blocks": _slack_blocks(payload)}
        response = httpx.post(str(destination.url), json=outbound, timeout=15.0)
        return DeliveryResult(
            destination_type=destination.type,
            ok=200 <= response.status_code < 300,
            status_code=response.status_code,
            message=response.text[:500],
        )

    if destination.type == AlertDestinationType.EMAIL:
        return _send_email(destination, payload)

    return DeliveryResult(destination_type=destination.type, ok=False, message="Unsupported destination.")


def _slack_blocks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"type": "header", "text": {"type": "plain_text", "text": payload["title"][:150]}},
        {"type": "section", "text": {"type": "mrkdwn", "text": payload["text"][:3000]}},
    ]


def _send_email(destination: AlertDestination, payload: dict[str, Any]) -> DeliveryResult:
    if not destination.email_to:
        return DeliveryResult(destination_type=destination.type, ok=False, message="Missing email_to.")

    import os

    host = os.getenv("COMMERCELENS_SMTP_HOST")
    port = int(os.getenv("COMMERCELENS_SMTP_PORT", "587"))
    username = os.getenv("COMMERCELENS_SMTP_USERNAME")
    password = os.getenv("COMMERCELENS_SMTP_PASSWORD")
    sender = os.getenv("COMMERCELENS_SMTP_FROM", username or "commercelens@example.com")
    use_tls = os.getenv("COMMERCELENS_SMTP_TLS", "true").lower() != "false"

    if not host:
        return DeliveryResult(
            destination_type=destination.type,
            ok=False,
            message="Missing COMMERCELENS_SMTP_HOST.",
        )

    message = EmailMessage()
    message["Subject"] = payload["title"]
    message["From"] = sender
    message["To"] = destination.email_to
    message.set_content(payload["text"])

    with smtplib.SMTP(host, port, timeout=20) as smtp:
        if use_tls:
            smtp.starttls()
        if username and password:
            smtp.login(username, password)
        smtp.send_message(message)

    return DeliveryResult(destination_type=destination.type, ok=True, message="Email sent.")
