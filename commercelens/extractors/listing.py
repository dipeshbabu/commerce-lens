from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from commercelens.core.fetcher import fetch_html
from commercelens.core.urls import normalize_url
from commercelens.extractors.availability import normalize_availability
from commercelens.extractors.price import parse_price
from commercelens.schemas.listing import ListingExtractionResult, ListingProduct

CARD_SELECTORS = [
    "article.product_pod",
    "[data-testid*='product']",
    "[class*='product-card']",
    "[class*='product_card']",
    "[class*='product-item']",
    "[class*='product_item']",
    "[class*='product-tile']",
    "[class*='product_tile']",
    "[class*='grid-item']",
    "li[class*='product']",
    "article[class*='product']",
]

NAME_SELECTORS = [
    "[itemprop='name']",
    "h1",
    "h2",
    "h3",
    "h4",
    ".product-title",
    ".product__title",
    ".product-name",
    "[class*='title']",
    "[class*='name']",
]

PRICE_SELECTORS = [
    "[itemprop='price']",
    ".price_color",
    ".price",
    ".product-price",
    ".product__price",
    "[class*='price']",
]

AVAILABILITY_SELECTORS = [
    ".availability",
    ".stock",
    "[class*='availability']",
    "[class*='stock']",
]

NEXT_SELECTORS = [
    "a[rel='next']",
    ".next a",
    "a.next",
    "a[aria-label*='Next']",
    "a[aria-label*='next']",
    "a:contains('Next')",
]


def _clean_text(value: str | None) -> str | None:
    if not value:
        return None
    text = " ".join(value.split())
    return text or None


def _node_text(node: Tag | None) -> str | None:
    if not node:
        return None
    value = node.get("content") or node.get("title") or node.get("alt") or node.get_text(" ", strip=True)
    return _clean_text(str(value)) if value else None


def _first_text(card: Tag, selectors: list[str]) -> tuple[str | None, str | None]:
    for selector in selectors:
        node = card.select_one(selector)
        value = _node_text(node)
        if value:
            return value, selector
    return None, None


def _product_url(card: Tag, base_url: str | None) -> str | None:
    preferred = card.select_one("a[href][itemprop='url']") or card.select_one("h1 a[href], h2 a[href], h3 a[href]")
    link = preferred or card.select_one("a[href]")
    if not link or not link.get("href"):
        return None
    return normalize_url(str(link["href"]), base_url=base_url)


def _image_url(card: Tag, base_url: str | None) -> str | None:
    img = card.select_one("img")
    if not img:
        return None
    raw = img.get("src") or img.get("data-src") or img.get("data-original") or img.get("srcset")
    if not raw:
        return None
    raw = str(raw).split(",")[0].strip().split(" ")[0]
    return urljoin(base_url or "", raw)


def _next_page_url(soup: BeautifulSoup, base_url: str | None) -> str | None:
    for selector in NEXT_SELECTORS:
        try:
            node = soup.select_one(selector)
        except Exception:
            continue
        if node and node.get("href"):
            return normalize_url(str(node["href"]), base_url=base_url)

    for link in soup.find_all("a", href=True):
        text = _clean_text(link.get_text(" ", strip=True)) or ""
        if text.lower() in {"next", "next page", ">", "›", "→"}:
            return normalize_url(str(link["href"]), base_url=base_url)
    return None


def _score_listing_product(item: ListingProduct) -> float:
    score = 0.0
    if item.name:
        score += 0.35
    if item.url:
        score += 0.25
    if item.price and item.price.amount is not None:
        score += 0.25
    if item.image_url:
        score += 0.10
    if item.availability:
        score += 0.05
    return round(min(score, 1.0), 3)


def _candidate_cards(soup: BeautifulSoup) -> list[tuple[Tag, str]]:
    seen: set[int] = set()
    cards: list[tuple[Tag, str]] = []
    for selector in CARD_SELECTORS:
        for card in soup.select(selector):
            if not isinstance(card, Tag):
                continue
            identity = id(card)
            if identity in seen:
                continue
            seen.add(identity)
            cards.append((card, selector))
    return cards


def extract_listing_from_html(html: str, url: str | None = None) -> ListingExtractionResult:
    soup = BeautifulSoup(html, "lxml")
    warnings: list[str] = []
    products: list[ListingProduct] = []
    seen_urls: set[str] = set()
    seen_names: set[str] = set()

    for position, (card, selector) in enumerate(_candidate_cards(soup), start=1):
        name, _name_selector = _first_text(card, NAME_SELECTORS)
        raw_price, _price_selector = _first_text(card, PRICE_SELECTORS)
        raw_availability, _availability_selector = _first_text(card, AVAILABILITY_SELECTORS)
        product_url = _product_url(card, url)
        image_url = _image_url(card, url)
        price = parse_price(raw_price)
        availability = normalize_availability(raw_availability)
        availability_value = None if availability.value == "unknown" else availability.value

        if not name and product_url:
            name = product_url.rstrip("/").split("/")[-1].replace("-", " ").replace("_", " ").title()

        if not name and not product_url:
            continue
        if product_url and product_url in seen_urls:
            continue
        if not product_url and name in seen_names:
            continue

        item = ListingProduct(
            name=name,
            url=product_url,
            price=price if price and price.amount is not None else None,
            image_url=image_url,
            availability=availability_value,
            position=len(products) + 1,
            source_selector=selector,
        )
        item.confidence = _score_listing_product(item)

        if item.confidence < 0.4:
            continue

        products.append(item)
        if product_url:
            seen_urls.add(product_url)
        if name:
            seen_names.add(name)

    if not products:
        warnings.append("Could not identify product cards on this listing page.")

    confidence = 0.0
    if products:
        confidence = round(sum(product.confidence for product in products) / len(products), 3)

    return ListingExtractionResult(
        url=url,
        products=products,
        product_count=len(products),
        next_page_url=_next_page_url(soup, url),
        confidence=confidence,
        warnings=warnings,
    )


def extract_listing(url: str) -> ListingExtractionResult:
    html = fetch_html(url)
    return extract_listing_from_html(html, url=url)
