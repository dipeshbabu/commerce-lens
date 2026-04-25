from __future__ import annotations

from pydantic import BaseModel, Field

from commercelens.alerts.config import MonitorConfig, load_monitor_config
from commercelens.alerts.delivery import AlertDeliveryReport, deliver_alert
from commercelens.alerts.rules import AlertEvent, event_from_change, rule_matches_change, snapshot_triggered_threshold
from commercelens.core.monitor import monitor_product


class MonitorRunResult(BaseModel):
    checked: int = 0
    succeeded: int = 0
    failed: int = 0
    events: list[AlertEvent] = Field(default_factory=list)
    delivery_reports: list[AlertDeliveryReport] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def run_monitor_config(
    config: MonitorConfig,
    dry_run: bool = False,
    deliver: bool = True,
) -> MonitorRunResult:
    result = MonitorRunResult(checked=len(config.targets))

    for target in config.targets:
        try:
            monitor_result = monitor_product(
                target.url,
                db_path=config.db_path,
                render=target.render or config.render,
            )
            result.succeeded += 1
        except Exception as exc:  # pragma: no cover - defensive CLI/API path
            result.failed += 1
            result.warnings.append(f"{target.url}: {exc}")
            continue

        target_events: list[tuple[AlertEvent, object]] = []
        if monitor_result.change:
            for rule in config.rules:
                if rule_matches_change(rule, monitor_result.change):
                    target_events.append((event_from_change(rule, monitor_result.change), rule))

        for rule in config.rules:
            threshold_event = snapshot_triggered_threshold(rule, monitor_result.snapshot)
            if threshold_event:
                target_events.append((threshold_event, rule))

        for event, rule in target_events:
            result.events.append(event)
            if deliver:
                report = deliver_alert(event, rule.destinations, dry_run=dry_run)
                result.delivery_reports.append(report)

    return result


def run_monitor_config_file(
    path: str,
    dry_run: bool = False,
    deliver: bool = True,
) -> MonitorRunResult:
    return run_monitor_config(load_monitor_config(path), dry_run=dry_run, deliver=deliver)
