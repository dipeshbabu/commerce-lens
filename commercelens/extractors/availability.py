from __future__ import annotations

from commercelens.schemas.product import Availability

IN_STOCK_TERMS = ["in stock", "available", "ships", "add to cart", "buy now"]
OUT_OF_STOCK_TERMS = ["out of stock", "sold out", "unavailable", "currently unavailable"]
PREORDER_TERMS = ["preorder", "pre-order", "pre order"]
BACKORDER_TERMS = ["backorder", "back order", "back-order"]


def normalize_availability(raw: str | None) -> Availability:
    if not raw:
        return Availability.UNKNOWN

    text = " ".join(raw.lower().split())

    if any(term in text for term in OUT_OF_STOCK_TERMS):
        return Availability.OUT_OF_STOCK
    if any(term in text for term in PREORDER_TERMS):
        return Availability.PREORDER
    if any(term in text for term in BACKORDER_TERMS):
        return Availability.BACKORDER
    if any(term in text for term in IN_STOCK_TERMS):
        return Availability.IN_STOCK

    return Availability.UNKNOWN
