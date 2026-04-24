from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel


def _to_dict(item: BaseModel | dict) -> dict:
    if isinstance(item, BaseModel):
        return item.model_dump(mode="json", exclude_none=True)
    return item


def write_jsonl(items: Iterable[BaseModel | dict], path: str | Path) -> None:
    output_path = Path(path)
    with output_path.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(_to_dict(item), ensure_ascii=False) + "\n")


def write_csv(items: Iterable[BaseModel | dict], path: str | Path) -> None:
    rows = [_flatten(_to_dict(item)) for item in items]
    output_path = Path(path)
    if not rows:
        output_path.write_text("", encoding="utf-8")
        return

    fieldnames = sorted({key for row in rows for key in row.keys()})
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _flatten(data: dict, prefix: str = "") -> dict[str, str | int | float | bool | None]:
    flattened: dict[str, str | int | float | bool | None] = {}
    for key, value in data.items():
        full_key = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            flattened.update(_flatten(value, full_key))
        elif isinstance(value, list):
            flattened[full_key] = json.dumps(value, ensure_ascii=False)
        else:
            flattened[full_key] = value
    return flattened
