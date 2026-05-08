from __future__ import annotations

import json
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from commercelens.extractors.availability import normalize_availability
from commercelens.schemas.product import ExtractedField, Price, Product


def _balanced_object(text: str, start: int) -> str | None:
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _shopify_meta_product(soup: BeautifulSoup) -> dict[str, Any] | None:
    for script in soup.find_all("script"):
        text = script.string or script.get_text()
        marker = "ShopifyAnalytics.meta.product"
        marker_index = text.find(marker)
        if marker_index < 0:
            continue
        object_start = text.find("{", marker_index)
        if object_start < 0:
            continue
        raw_object = _balanced_object(text, object_start)
        if not raw_object:
            continue
        try:
            data = json.loads(raw_object)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


def apply_shopify_product_adapter(
    soup: BeautifulSoup,
    product: Product,
    fields: dict[str, ExtractedField],
    url: str | None = None,
) -> bool:
    data = _shopify_meta_product(soup)
    if not data:
        return False

    variants = data.get("variants")
    first_variant = variants[0] if isinstance(variants, list) and variants else {}
    if not isinstance(first_variant, dict):
        first_variant = {}

    if not product.name and data.get("title"):
        product.name = str(data["title"]).strip()
        fields["name"] = ExtractedField(value=product.name, confidence=0.88, source="shopify_adapter")

    if not product.brand and data.get("vendor"):
        product.brand = str(data["vendor"]).strip()
        fields["brand"] = ExtractedField(value=product.brand, confidence=0.86, source="shopify_adapter")

    if not product.sku and first_variant.get("sku"):
        product.sku = str(first_variant["sku"]).strip()
        fields["sku"] = ExtractedField(value=product.sku, confidence=0.84, source="shopify_adapter")

    if not product.price and first_variant.get("price") is not None:
        raw_price = first_variant["price"]
        try:
            amount = float(raw_price) / 100 if isinstance(raw_price, int) else float(raw_price)
            product.price = Price(amount=amount, currency=data.get("currency"))
            fields["price"] = ExtractedField(
                value=product.price.model_dump(), confidence=0.86, source="shopify_adapter"
            )
        except (TypeError, ValueError):
            pass

    if product.availability.value == "unknown" and "available" in first_variant:
        product.availability = normalize_availability(
            "in stock" if first_variant.get("available") else "out of stock"
        )
        fields["availability"] = ExtractedField(
            value=product.availability.value, confidence=0.84, source="shopify_adapter"
        )

    featured_image = data.get("featured_image")
    if not product.image_urls and featured_image:
        product.image_urls = [urljoin(url or "", str(featured_image))]
        fields["image_urls"] = ExtractedField(
            value=product.image_urls, confidence=0.82, source="shopify_adapter"
        )

    product.metadata["adapter"] = "shopify"
    return True
