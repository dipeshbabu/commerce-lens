from __future__ import annotations

import json
from typing import Any

from bs4 import BeautifulSoup


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _walk_jsonld(node: Any) -> list[dict[str, Any]]:
    products: list[dict[str, Any]] = []

    if isinstance(node, list):
        for item in node:
            products.extend(_walk_jsonld(item))
        return products

    if not isinstance(node, dict):
        return products

    node_type = node.get("@type") or node.get("type")
    node_types = [str(t).lower() for t in _as_list(node_type)]
    if "product" in node_types:
        products.append(node)

    for key in ("@graph", "graph", "itemListElement", "mainEntity", "mainEntityOfPage"):
        if key in node:
            products.extend(_walk_jsonld(node[key]))

    return products


def extract_jsonld_products(soup: BeautifulSoup) -> list[dict[str, Any]]:
    products: list[dict[str, Any]] = []
    scripts = soup.find_all("script", attrs={"type": "application/ld+json"})

    for script in scripts:
        raw = script.string or script.get_text(strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        products.extend(_walk_jsonld(data))

    return products


def first_jsonld_product(soup: BeautifulSoup) -> dict[str, Any] | None:
    products = extract_jsonld_products(soup)
    return products[0] if products else None
