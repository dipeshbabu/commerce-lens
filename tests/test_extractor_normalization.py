from __future__ import annotations

import pytest

from commercelens.extractors.availability import normalize_availability
from commercelens.extractors.price import parse_price


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://schema.org/InStock", "in_stock"),
        ("https://schema.org/OutOfStock", "out_of_stock"),
        ("https://schema.org/PreOrder", "preorder"),
        ("https://schema.org/BackOrder", "backorder"),
    ],
)
def test_normalize_availability_handles_schema_camel_case(raw: str, expected: str) -> None:
    assert normalize_availability(raw).value == expected


@pytest.mark.parametrize(
    ("raw", "currency", "expected_amount"),
    [
        ("12000", "JPY", 12000.0),
        ("1,200", "USD", 1200.0),
        ("1200.50", "USD", 1200.5),
    ],
)
def test_parse_price_preserves_full_integer_amount(
    raw: str, currency: str, expected_amount: float
) -> None:
    price = parse_price(raw, default_currency=currency)
    assert price is not None
    assert price.amount == expected_amount
    assert price.currency == currency
