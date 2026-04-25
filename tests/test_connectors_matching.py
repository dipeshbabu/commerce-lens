from __future__ import annotations

from pathlib import Path

from commercelens.connectors.datasets import ProductRecord, load_product_records, write_product_records
from commercelens.matching.products import match_products, product_similarity


def test_load_csv_product_records(tmp_path: Path) -> None:
    path = tmp_path / "products.csv"
    path.write_text(
        "url,name,brand,amount,currency\n"
        "https://example.com/a,Nike Air Max 90,Nike,120,USD\n",
        encoding="utf-8",
    )

    result = load_product_records(path)

    assert not result.warnings
    assert len(result.records) == 1
    assert result.records[0].name == "Nike Air Max 90"
    assert result.records[0].amount == 120


def test_write_jsonl_product_records(tmp_path: Path) -> None:
    path = tmp_path / "products.jsonl"
    result = write_product_records(
        [ProductRecord(url="https://example.com/a", name="Sample", amount=10, currency="USD")],
        path,
    )

    assert result.count == 1
    assert result.format == "jsonl"
    assert "Sample" in path.read_text(encoding="utf-8")


def test_product_similarity_strong_match() -> None:
    left = ProductRecord(name="Nike Air Max 90", brand="Nike", amount=120, currency="USD")
    right = ProductRecord(name="Nike Air Max 90 Shoes", brand="Nike", amount=125, currency="USD")

    score, reasons = product_similarity(left, right)

    assert score >= 0.72
    assert "brand_match" in reasons


def test_match_products_returns_top_match() -> None:
    left = [ProductRecord(name="Sony WH-1000XM5 Wireless Headphones", brand="Sony", amount=399, currency="USD")]
    right = [
        ProductRecord(name="Unrelated Backpack", brand="Other", amount=40, currency="USD"),
        ProductRecord(name="Sony WH1000XM5 Noise Canceling Headphones", brand="Sony", amount=389, currency="USD"),
    ]

    result = match_products(left, right, threshold=0.6)

    assert len(result.matches) == 1
    assert result.matches[0].right.brand == "Sony"
