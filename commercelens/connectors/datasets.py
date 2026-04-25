from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel, Field

from commercelens.storage.price_store import ProductSnapshot


class ProductRecord(BaseModel):
    url: str | None = None
    product_key: str | None = None
    name: str | None = None
    brand: str | None = None
    amount: float | None = None
    currency: str | None = None
    availability: str | None = None
    image_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DatasetLoadResult(BaseModel):
    records: list[ProductRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DatasetWriteResult(BaseModel):
    path: str
    count: int
    format: str


def load_product_records(path: str | Path) -> DatasetLoadResult:
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    if suffix == ".jsonl":
        return _load_jsonl(file_path)
    if suffix == ".json":
        return _load_json(file_path)
    if suffix == ".csv":
        return _load_csv(file_path)
    if suffix == ".txt":
        records = [ProductRecord(url=line.strip()) for line in file_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return DatasetLoadResult(records=records)
    raise ValueError("Supported formats: .txt, .csv, .json, .jsonl")


def write_product_records(records: Iterable[ProductRecord], path: str | Path) -> DatasetWriteResult:
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    rows = list(records)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    if suffix == ".jsonl":
        with file_path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row.model_dump(mode="json", exclude_none=True), ensure_ascii=False) + "\n")
        return DatasetWriteResult(path=str(file_path), count=len(rows), format="jsonl")
    if suffix == ".json":
        file_path.write_text(json.dumps([row.model_dump(mode="json", exclude_none=True) for row in rows], indent=2), encoding="utf-8")
        return DatasetWriteResult(path=str(file_path), count=len(rows), format="json")
    if suffix == ".csv":
        fieldnames = ["url", "product_key", "name", "brand", "amount", "currency", "availability", "image_url"]
        with file_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({field: getattr(row, field) for field in fieldnames})
        return DatasetWriteResult(path=str(file_path), count=len(rows), format="csv")
    raise ValueError("Supported output formats: .csv, .json, .jsonl")


def records_from_snapshots(snapshots: Iterable[ProductSnapshot]) -> list[ProductRecord]:
    return [
        ProductRecord(
            url=snapshot.source_url or snapshot.canonical_url,
            product_key=snapshot.product_key,
            name=snapshot.name,
            brand=snapshot.brand,
            amount=snapshot.amount,
            currency=snapshot.currency,
            availability=snapshot.availability,
            image_url=snapshot.image_url,
            metadata={"captured_at": snapshot.captured_at},
        )
        for snapshot in snapshots
    ]


def _load_jsonl(path: Path) -> DatasetLoadResult:
    records: list[ProductRecord] = []
    warnings: list[str] = []
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(ProductRecord.model_validate(json.loads(line)))
        except Exception as exc:
            warnings.append(f"line {index}: {exc}")
    return DatasetLoadResult(records=records, warnings=warnings)


def _load_json(path: Path) -> DatasetLoadResult:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("records", data.get("products", []))
    if not isinstance(data, list):
        raise ValueError("JSON input must be a list or an object with records/products.")
    records: list[ProductRecord] = []
    warnings: list[str] = []
    for index, item in enumerate(data, start=1):
        try:
            records.append(ProductRecord.model_validate(item))
        except Exception as exc:
            warnings.append(f"item {index}: {exc}")
    return DatasetLoadResult(records=records, warnings=warnings)


def _load_csv(path: Path) -> DatasetLoadResult:
    records: list[ProductRecord] = []
    warnings: list[str] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader, start=1):
            try:
                amount = row.get("amount") or row.get("price")
                records.append(
                    ProductRecord(
                        url=row.get("url") or row.get("source_url") or row.get("canonical_url"),
                        product_key=row.get("product_key") or None,
                        name=row.get("name") or row.get("title") or None,
                        brand=row.get("brand") or None,
                        amount=float(amount) if amount not in {None, ""} else None,
                        currency=row.get("currency") or None,
                        availability=row.get("availability") or None,
                        image_url=row.get("image_url") or row.get("image") or None,
                    )
                )
            except Exception as exc:
                warnings.append(f"row {index}: {exc}")
    return DatasetLoadResult(records=records, warnings=warnings)
