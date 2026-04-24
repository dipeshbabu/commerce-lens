from pathlib import Path

from commercelens.schemas.listing import ListingProduct
from commercelens.schemas.product import Price
from commercelens.storage.exporters import write_csv, write_jsonl


def test_write_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "products.jsonl"
    items = [ListingProduct(name="Sample", price=Price(amount=10.0, currency="USD"))]

    write_jsonl(items, path)

    text = path.read_text(encoding="utf-8")
    assert '"name": "Sample"' in text
    assert '"currency": "USD"' in text


def test_write_csv(tmp_path: Path) -> None:
    path = tmp_path / "products.csv"
    items = [ListingProduct(name="Sample", price=Price(amount=10.0, currency="USD"))]

    write_csv(items, path)

    text = path.read_text(encoding="utf-8")
    assert "name" in text
    assert "price.amount" in text
    assert "Sample" in text
