from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from commercelens.alerts.rules import AlertRule


class MonitorTarget(BaseModel):
    url: str
    render: bool = False
    tags: list[str] = Field(default_factory=list)


class MonitorConfig(BaseModel):
    db_path: str = "commercelens.db"
    render: bool = False
    targets: list[MonitorTarget] = Field(default_factory=list)
    rules: list[AlertRule] = Field(default_factory=list)


def load_monitor_config(path: str | Path) -> MonitorConfig:
    config_path = Path(path)
    text = config_path.read_text(encoding="utf-8")
    data = _parse_config_text(text, suffix=config_path.suffix.lower())
    return MonitorConfig.model_validate(data)


def _parse_config_text(text: str, suffix: str) -> dict[str, Any]:
    if suffix == ".json":
        return json.loads(text)
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise RuntimeError("YAML config requires pyyaml. Install with `pip install pyyaml`.") from exc
        parsed = yaml.safe_load(text)
        if not isinstance(parsed, dict):
            raise ValueError("Config file must contain an object at the top level.")
        return parsed
    raise ValueError("Config must be .json, .yaml, or .yml")


def save_example_config(path: str | Path) -> None:
    example = {
        "db_path": "prices.db",
        "render": False,
        "targets": [
            {"url": "https://example.com/products/sample", "tags": ["demo"]},
            {"url": "https://example.com/products/another-sample", "tags": ["demo"]},
        ],
        "rules": [
            {
                "name": "any-price-change",
                "condition": "any_change",
                "destinations": [{"type": "stdout"}],
            },
            {
                "name": "major-price-drop",
                "condition": "percent_drop_at_least",
                "threshold": 10,
                "destinations": [
                    {"type": "file", "file_path": "alerts.jsonl"},
                    {"type": "webhook", "url": "https://example.com/webhook"},
                ],
            },
            {
                "name": "back-in-stock",
                "condition": "back_in_stock",
                "destinations": [{"type": "slack", "url": "https://hooks.slack.com/services/..."}],
            },
        ],
    }
    Path(path).write_text(json.dumps(example, indent=2), encoding="utf-8")
