from commercelens.schemas.product import Availability, Price, Product, ProductExtractionResult
from commercelens.storage.price_store import PriceSnapshotStore, compare_snapshots, snapshot_from_result


def _result(amount: float, availability: Availability = Availability.IN_STOCK) -> ProductExtractionResult:
    return ProductExtractionResult(
        url="https://example.com/products/widget",
        product=Product(
            name="Widget",
            brand="Example",
            price=Price(amount=amount, currency="USD", raw=f"${amount}"),
            availability=availability,
            canonical_url="https://example.com/products/widget",
            source_url="https://example.com/products/widget",
        ),
        confidence=0.9,
    )


def test_snapshot_store_tracks_history_and_price_drop(tmp_path) -> None:
    db_path = tmp_path / "prices.db"
    store = PriceSnapshotStore(db_path)

    first = snapshot_from_result(_result(100.0), captured_at="2026-01-01T00:00:00+00:00")
    second = snapshot_from_result(_result(80.0), captured_at="2026-01-02T00:00:00+00:00")

    store.add_snapshot(first)
    store.add_snapshot(second)

    history = store.history(first.product_key)
    assert len(history) == 2
    assert history[0].amount == 80.0

    change = store.detect_change(first.product_key)
    assert change is not None
    assert change.change_type == "price_drop"
    assert change.delta == -20.0
    assert change.delta_percent == -20.0


def test_compare_snapshots_detects_back_in_stock() -> None:
    previous = snapshot_from_result(
        _result(50.0, availability=Availability.OUT_OF_STOCK),
        captured_at="2026-01-01T00:00:00+00:00",
    )
    current = snapshot_from_result(
        _result(50.0, availability=Availability.IN_STOCK),
        captured_at="2026-01-02T00:00:00+00:00",
    )

    change = compare_snapshots(previous, current)
    assert change is not None
    assert change.change_type == "back_in_stock"
    assert change.previous_availability == "out_of_stock"
    assert change.current_availability == "in_stock"


def test_history_for_url(tmp_path) -> None:
    db_path = tmp_path / "prices.db"
    store = PriceSnapshotStore(db_path)
    snapshot = snapshot_from_result(_result(25.0), captured_at="2026-01-01T00:00:00+00:00")
    store.add_snapshot(snapshot)

    history = store.history_for_url("https://example.com/products/widget")
    assert len(history) == 1
    assert history[0].name == "Widget"
