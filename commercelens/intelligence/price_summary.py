from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, Field

from commercelens.connectors.datasets import ProductRecord


class PriceIntelligenceSummary(BaseModel):
    record_count: int = 0
    priced_count: int = 0
    currency: str | None = None
    min_amount: float | None = None
    max_amount: float | None = None
    average_amount: float | None = None
    cheapest: ProductRecord | None = None
    highest: ProductRecord | None = None
    availability_counts: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


def summarize_prices(records: list[ProductRecord]) -> PriceIntelligenceSummary:
    priced = [record for record in records if record.amount is not None]
    availability_counts = Counter(record.availability or "unknown" for record in records)
    warnings: list[str] = []
    currencies = sorted({record.currency.upper() for record in priced if record.currency})
    currency = currencies[0] if len(currencies) == 1 else None
    if len(currencies) > 1:
        warnings.append("Multiple currencies found; aggregate price fields are not currency-normalized.")

    amounts = [float(record.amount) for record in priced if record.amount is not None]
    cheapest = min(priced, key=lambda record: float(record.amount)) if priced else None
    highest = max(priced, key=lambda record: float(record.amount)) if priced else None
    return PriceIntelligenceSummary(
        record_count=len(records),
        priced_count=len(priced),
        currency=currency,
        min_amount=min(amounts) if amounts else None,
        max_amount=max(amounts) if amounts else None,
        average_amount=round(sum(amounts) / len(amounts), 2) if amounts else None,
        cheapest=cheapest,
        highest=highest,
        availability_counts=dict(sorted(availability_counts.items())),
        warnings=warnings,
    )
