from __future__ import annotations

from pathlib import Path

from commercelens.connectors.datasets import ProductRecord
from commercelens.matching.evaluation import evaluate_matching_cases, load_matching_cases
from commercelens.matching.products import DEFAULT_MATCH_THRESHOLD, product_similarity


FIXTURE = Path("tests/fixtures/matching/evaluation.json")


def test_matching_evaluation_is_deterministic_and_high_precision() -> None:
    cases = load_matching_cases(FIXTURE)
    report = evaluate_matching_cases(cases)

    assert report.case_count == 31
    assert report.positive_count == 12
    assert report.negative_count == 19
    assert report.selected.precision >= 0.95
    assert report.selected.recall >= 0.95
    assert report.selected.f1 >= 0.95
    assert report.selected.false_match_rate <= 0.05
    assert report.category_counts["variant"] >= 8
    assert report.category_counts["bundle"] >= 4
    assert report.calibration


def test_variant_metadata_blocks_false_match() -> None:
    left = ProductRecord(
        name="Pixel 9 Pro 128GB Obsidian",
        brand="Google",
        metadata={"model": "pixel 9 pro", "storage": "128gb", "color": "obsidian"},
    )
    right = ProductRecord(
        name="Pixel 9 Pro 256GB Obsidian",
        brand="Google",
        metadata={"model": "pixel 9 pro", "storage": "256gb", "color": "obsidian"},
    )

    score, reasons = product_similarity(left, right)

    assert score < DEFAULT_MATCH_THRESHOLD
    assert "variant_mismatch:storage" in reasons


def test_bundle_metadata_blocks_false_match() -> None:
    left = ProductRecord(
        name="BrightHome Filter 1 Pack",
        brand="BrightHome",
        metadata={"model": "filter", "bundle_quantity": 1},
    )
    right = ProductRecord(
        name="BrightHome Filter 3 Pack",
        brand="BrightHome",
        metadata={"model": "filter", "bundle_quantity": 3},
    )

    score, reasons = product_similarity(left, right)

    assert score < DEFAULT_MATCH_THRESHOLD
    assert "bundle_mismatch:bundle_quantity" in reasons


def test_title_variation_still_matches() -> None:
    left = ProductRecord(
        name="Sony WH-1000XM5 Wireless Headphones Black",
        brand="Sony",
        amount=399.99,
        currency="USD",
        metadata={"model": "wh-1000xm5", "color": "black"},
    )
    right = ProductRecord(
        name="Sony Wireless Headphones WH 1000XM5 Black",
        brand="Sony",
        amount=379.99,
        currency="USD",
        metadata={"model": "wh-1000xm5", "color": "black"},
    )

    score, _ = product_similarity(left, right)

    assert score >= DEFAULT_MATCH_THRESHOLD
