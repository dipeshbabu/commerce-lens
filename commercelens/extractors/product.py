from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from commercelens.core.fetcher import fetch_html
from commercelens.core.renderer import render_html
from commercelens.extractors.adapters import apply_shopify_product_adapter
from commercelens.extractors.availability import normalize_availability
from commercelens.extractors.jsonld import first_jsonld_product
from commercelens.extractors.opengraph import extract_opengraph
from commercelens.extractors.price import parse_price
from commercelens.schemas.product import ExtractedField, Price, Product, ProductExtractionResult

TITLE_SELECTORS = [
    "[itemprop='name']",
    "h1[itemprop='name']",
    "h1.product-title",
    "h1.product__title",
    ".product-title",
    ".product__title",
    ".product-name",
    "h1",
]

PRICE_SELECTORS = [
    "[itemprop='price']",
    ".price",
    ".product-price",
    ".product__price",
    ".price_color",
    "[class*='price']",
]

AVAILABILITY_SELECTORS = [
    "[itemprop='availability']",
    ".availability",
    ".stock",
    ".inventory",
    "[class*='availability']",
    "[class*='stock']",
]

BRAND_SELECTORS = [
    "[itemprop='brand']",
    ".brand",
    ".product-brand",
    "[class*='brand']",
]

DESCRIPTION_SELECTORS = [
    "[itemprop='description']",
    "meta[name='description']",
    ".description",
    ".product-description",
    ".product__description",
]


def _text(node: Any) -> str | None:
    if not node:
        return None
    if getattr(node, "name", None) == "meta":
        value = node.get("content")
        return str(value).strip() if value else None
    value = node.get("content") or node.get("alt") or node.get_text(" ", strip=True)
    return str(value).strip() if value else None


def _first_text(soup: BeautifulSoup, selectors: list[str]) -> tuple[str | None, str | None]:
    for selector in selectors:
        node = soup.select_one(selector)
        value = _text(node)
        if value:
            return value, selector
    return None, None


def _canonical_url(soup: BeautifulSoup, base_url: str | None) -> str | None:
    link = soup.find("link", rel="canonical")
    if link and link.get("href"):
        return urljoin(base_url or "", str(link["href"]))
    return base_url


def _image_urls(soup: BeautifulSoup, base_url: str | None) -> list[str]:
    urls: list[str] = []
    for selector in ["meta[property='og:image']", "[itemprop='image']", "img"]:
        for node in soup.select(selector):
            raw = node.get("content") or node.get("src") or node.get("data-src")
            if raw:
                absolute = urljoin(base_url or "", str(raw))
                if absolute not in urls:
                    urls.append(absolute)
        if urls:
            break
    return urls[:20]


def _jsonld_price(product_data: dict[str, Any]) -> Price | None:
    offers = product_data.get("offers")
    if isinstance(offers, list):
        offers = offers[0] if offers else None
    if not isinstance(offers, dict):
        return None
    raw_amount = offers.get("price") or offers.get("lowPrice") or offers.get("highPrice")
    currency = offers.get("priceCurrency")
    if raw_amount is None:
        return None
    return parse_price(str(raw_amount), default_currency=str(currency) if currency else None)


def _jsonld_availability(product_data: dict[str, Any]) -> str | None:
    offers = product_data.get("offers")
    if isinstance(offers, list):
        offers = offers[0] if offers else None
    if isinstance(offers, dict):
        availability = offers.get("availability")
        if availability:
            return str(availability).split("/")[-1].replace("InStock", "in stock")
    return None


def _jsonld_images(product_data: dict[str, Any], base_url: str | None) -> list[str]:
    images = product_data.get("image")
    if not images:
        return []
    if isinstance(images, str):
        images = [images]
    if not isinstance(images, list):
        return []
    return [urljoin(base_url or "", str(img)) for img in images if img]


def extract_product_from_html(html: str, url: str | None = None) -> ProductExtractionResult:
    soup = BeautifulSoup(html, "lxml")
    fields: dict[str, ExtractedField] = {}
    warnings: list[str] = []

    product = Product(source_url=url, canonical_url=_canonical_url(soup, url))

    jsonld_product = first_jsonld_product(soup)
    if jsonld_product:
        name = jsonld_product.get("name")
        if name:
            product.name = str(name).strip()
            fields["name"] = ExtractedField(value=product.name, confidence=0.98, source="json_ld")

        brand = jsonld_product.get("brand")
        if isinstance(brand, dict):
            brand = brand.get("name")
        if brand:
            product.brand = str(brand).strip()
            fields["brand"] = ExtractedField(value=product.brand, confidence=0.95, source="json_ld")

        description = jsonld_product.get("description")
        if description:
            product.description = str(description).strip()
            fields["description"] = ExtractedField(
                value=product.description, confidence=0.9, source="json_ld"
            )

        price = _jsonld_price(jsonld_product)
        if price:
            product.price = price
            fields["price"] = ExtractedField(
                value=price.model_dump(), confidence=0.96, source="json_ld"
            )

        availability = _jsonld_availability(jsonld_product)
        if availability:
            product.availability = normalize_availability(availability)
            fields["availability"] = ExtractedField(
                value=product.availability.value, confidence=0.92, source="json_ld"
            )

        sku = jsonld_product.get("sku") or jsonld_product.get("mpn")
        if sku:
            product.sku = str(sku).strip()
            fields["sku"] = ExtractedField(value=product.sku, confidence=0.9, source="json_ld")

        product.image_urls = _jsonld_images(jsonld_product, url)
        if product.image_urls:
            fields["image_urls"] = ExtractedField(
                value=product.image_urls, confidence=0.9, source="json_ld"
            )

        aggregate_rating = jsonld_product.get("aggregateRating")
        if isinstance(aggregate_rating, dict):
            rating = aggregate_rating.get("ratingValue")
            review_count = aggregate_rating.get("reviewCount") or aggregate_rating.get("ratingCount")
            try:
                product.rating = float(rating) if rating is not None else None
            except (TypeError, ValueError):
                product.rating = None
            try:
                product.review_count = int(review_count) if review_count is not None else None
            except (TypeError, ValueError):
                product.review_count = None

    og = extract_opengraph(soup)
    if not product.name and og.get("title"):
        product.name = og["title"]
        fields["name"] = ExtractedField(value=product.name, confidence=0.78, source="opengraph")
    if not product.description and og.get("description"):
        product.description = og["description"]
        fields["description"] = ExtractedField(
            value=product.description, confidence=0.72, source="opengraph"
        )
    if not product.brand and og.get("brand"):
        product.brand = og["brand"]
        fields["brand"] = ExtractedField(value=product.brand, confidence=0.75, source="opengraph")
    if not product.price and og.get("price_amount"):
        product.price = parse_price(og["price_amount"], default_currency=og.get("price_currency"))
        fields["price"] = ExtractedField(
            value=product.price.model_dump() if product.price else None,
            confidence=0.8,
            source="opengraph",
        )
    if product.availability.value == "unknown" and og.get("availability"):
        product.availability = normalize_availability(og["availability"])
        fields["availability"] = ExtractedField(
            value=product.availability.value, confidence=0.75, source="opengraph"
        )
    if not product.image_urls and og.get("image"):
        product.image_urls = [urljoin(url or "", og["image"])]
        fields["image_urls"] = ExtractedField(
            value=product.image_urls, confidence=0.75, source="opengraph"
        )

    apply_shopify_product_adapter(soup, product, fields, url=url)

    if not product.name:
        name, selector = _first_text(soup, TITLE_SELECTORS)
        if name:
            product.name = name
            fields["name"] = ExtractedField(
                value=name, confidence=0.72, source="dom_heuristic", selector=selector
            )

    if not product.price:
        raw_price, selector = _first_text(soup, PRICE_SELECTORS)
        price = parse_price(raw_price)
        if price and price.amount is not None:
            product.price = price
            fields["price"] = ExtractedField(
                value=price.model_dump(), confidence=0.72, source="dom_heuristic", selector=selector
            )

    if product.availability.value == "unknown":
        raw_availability, selector = _first_text(soup, AVAILABILITY_SELECTORS)
        availability = normalize_availability(raw_availability)
        if availability.value != "unknown":
            product.availability = availability
            fields["availability"] = ExtractedField(
                value=availability.value,
                confidence=0.7,
                source="dom_heuristic",
                selector=selector,
            )

    if not product.brand:
        brand, selector = _first_text(soup, BRAND_SELECTORS)
        if brand:
            product.brand = brand
            fields["brand"] = ExtractedField(
                value=brand, confidence=0.65, source="dom_heuristic", selector=selector
            )

    if not product.description:
        description, selector = _first_text(soup, DESCRIPTION_SELECTORS)
        if description:
            product.description = description
            fields["description"] = ExtractedField(
                value=description, confidence=0.65, source="dom_heuristic", selector=selector
            )

    if not product.image_urls:
        product.image_urls = _image_urls(soup, url)
        if product.image_urls:
            fields["image_urls"] = ExtractedField(
                value=product.image_urls, confidence=0.65, source="dom_heuristic"
            )

    if not product.name:
        warnings.append("Could not extract product name.")
    if not product.price or product.price.amount is None:
        warnings.append("Could not extract a normalized product price.")

    confidence = 0.0
    if fields:
        confidence = round(sum(field.confidence for field in fields.values()) / len(fields), 3)

    return ProductExtractionResult(
        url=url,
        product=product,
        confidence=confidence,
        fields=fields,
        warnings=warnings,
    )


def extract_product(
    url: str,
    render: bool = False,
    screenshot_path: str | Path | None = None,
    html_snapshot_path: str | Path | None = None,
) -> ProductExtractionResult:
    if render:
        rendered = render_html(
            url,
            screenshot_path=screenshot_path,
            html_snapshot_path=html_snapshot_path,
        )
        result = extract_product_from_html(rendered.html, url=rendered.final_url or url)
        result.product.metadata["rendered"] = True
        if rendered.screenshot_path:
            result.product.metadata["screenshot_path"] = rendered.screenshot_path
        if rendered.html_snapshot_path:
            result.product.metadata["html_snapshot_path"] = rendered.html_snapshot_path
        return result

    html = fetch_html(url)
    return extract_product_from_html(html, url=url)
