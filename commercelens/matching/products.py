from __future__ import annotations

import re
from difflib import SequenceMatcher
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from commercelens.connectors.datasets import ProductRecord

_TOKEN_RE = re.compile(r"[a-z0-9]+")
DEFAULT_MATCH_THRESHOLD = 0.65
_VARIANT_KEYS = ("model", "storage", "memory", "capacity", "size", "color", "gender", "variant")
_BUNDLE_KEYS = ("bundle_quantity", "bundle")


class ProductMatch(BaseModel):
    left: ProductRecord
    right: ProductRecord
    score: float
    reasons: list[str] = Field(default_factory=list)


class ProductMatchResult(BaseModel):
    matches: list[ProductMatch] = Field(default_factory=list)


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(_TOKEN_RE.findall(value.lower()))


def token_set(value: str | None) -> set[str]:
    return set(normalize_text(value).split())


def _metadata_value(record: ProductRecord, key: str) -> str:
    value = record.metadata.get(key)
    if value is None:
        return ""
    return normalize_text(str(value))


def _explicit_mismatches(left: ProductRecord, right: ProductRecord) -> list[str]:
    mismatches: list[str] = []
    for key in _VARIANT_KEYS:
        left_value = _metadata_value(left, key)
        right_value = _metadata_value(right, key)
        if left_value and right_value and left_value != right_value:
            mismatches.append(f"variant_mismatch:{key}")
    for key in _BUNDLE_KEYS:
        left_value = _metadata_value(left, key)
        right_value = _metadata_value(right, key)
        if left_value and right_value and left_value != right_value:
            mismatches.append(f"bundle_mismatch:{key}")
    return mismatches


def product_similarity(left: ProductRecord, right: ProductRecord) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0

    left_name = normalize_text(left.name)
    right_name = normalize_text(right.name)
    if left_name and right_name:
        name_ratio = SequenceMatcher(None, left_name, right_name).ratio()
        score += 0.55 * name_ratio
        if name_ratio >= 0.85:
            reasons.append("strong_name_match")

    left_tokens = token_set(left.name)
    right_tokens = token_set(right.name)
    if left_tokens and right_tokens:
        jaccard = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
        score += 0.2 * jaccard
        if jaccard >= 0.6:
            reasons.append("shared_name_tokens")

    left_brand = normalize_text(left.brand)
    right_brand = normalize_text(right.brand)
    brand_mismatch = bool(left_brand and right_brand and left_brand != right_brand)
    if left_brand and right_brand:
        if left_brand == right_brand:
            score += 0.15
            reasons.append("brand_match")
        else:
            score -= 0.05
            reasons.append("brand_mismatch")

    if left.currency and right.currency and left.currency.upper() == right.currency.upper():
        score += 0.03
        reasons.append("currency_match")

    if left.amount is not None and right.amount is not None and max(left.amount, right.amount) > 0:
        gap = abs(left.amount - right.amount) / max(left.amount, right.amount)
        if gap <= 0.1:
            score += 0.05
            reasons.append("similar_price")
        elif gap > 0.5:
            score -= 0.03
            reasons.append("large_price_gap")

    left_domain = _domain(left.url)
    right_domain = _domain(right.url)
    if left_domain and right_domain and left_domain == right_domain:
        score += 0.02
        reasons.append("same_domain")

    mismatches = _explicit_mismatches(left, right)
    reasons.extend(mismatches)
    score = max(0.0, min(1.0, score))

    # Explicit structured attributes are stronger evidence than fuzzy title similarity.
    # A variant, bundle, or brand conflict must not cross the default match threshold.
    if any(reason.startswith("bundle_mismatch:") for reason in mismatches):
        score = min(score, 0.40)
    elif any(reason.startswith("variant_mismatch:model") for reason in mismatches):
        score = min(score, 0.45)
    elif mismatches:
        score = min(score, 0.55)
    if brand_mismatch:
        score = min(score, 0.50)

    return score, reasons


def match_products(
    left_records: list[ProductRecord],
    right_records: list[ProductRecord],
    threshold: float = DEFAULT_MATCH_THRESHOLD,
    top_k: int = 1,
) -> ProductMatchResult:
    matches: list[ProductMatch] = []
    for left in left_records:
        candidates: list[ProductMatch] = []
        for right in right_records:
            score, reasons = product_similarity(left, right)
            if score >= threshold:
                candidates.append(
                    ProductMatch(left=left, right=right, score=score, reasons=reasons)
                )
        candidates.sort(key=lambda item: item.score, reverse=True)
        matches.extend(candidates[:top_k])
    return ProductMatchResult(matches=matches)


def _domain(url: str | None) -> str:
    if not url:
        return ""
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""
