from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel, Field

from commercelens.connectors.datasets import ProductRecord
from commercelens.matching.products import product_similarity


DEFAULT_EVALUATION_THRESHOLDS = (0.60, 0.65, 0.70, 0.72, 0.75, 0.80, 0.85)


class MatchingEvaluationCase(BaseModel):
    name: str
    matched: bool
    category: str
    left: ProductRecord
    right: ProductRecord
    notes: str | None = None


class MatchingThresholdMetrics(BaseModel):
    threshold: float = Field(ge=0.0, le=1.0)
    true_positive: int = 0
    false_positive: int = 0
    true_negative: int = 0
    false_negative: int = 0
    precision: float = Field(ge=0.0, le=1.0)
    recall: float = Field(ge=0.0, le=1.0)
    f1: float = Field(ge=0.0, le=1.0)
    false_match_rate: float = Field(ge=0.0, le=1.0)


class MatchingCalibrationBucket(BaseModel):
    lower: float
    upper: float
    count: int
    average_confidence: float = 0.0
    observed_match_rate: float = 0.0


class MatchingEvaluationReport(BaseModel):
    case_count: int
    positive_count: int
    negative_count: int
    selected_threshold: float
    selected: MatchingThresholdMetrics
    thresholds: list[MatchingThresholdMetrics] = Field(default_factory=list)
    calibration: list[MatchingCalibrationBucket] = Field(default_factory=list)
    category_counts: dict[str, int] = Field(default_factory=dict)


def load_matching_cases(path: str | Path) -> list[MatchingEvaluationCase]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Matching evaluation data must be a JSON list.")
    return [MatchingEvaluationCase.model_validate(item) for item in raw]


def evaluate_matching_cases(
    cases: Iterable[MatchingEvaluationCase],
    *,
    thresholds: Iterable[float] = DEFAULT_EVALUATION_THRESHOLDS,
) -> MatchingEvaluationReport:
    rows = list(cases)
    scored = [(case, product_similarity(case.left, case.right)[0]) for case in rows]
    metrics = [_threshold_metrics(scored, float(threshold)) for threshold in thresholds]
    if not metrics:
        raise ValueError("At least one threshold is required.")
    selected = max(
        metrics,
        key=lambda item: (
            item.f1,
            item.precision,
            -item.false_match_rate,
            item.threshold,
        ),
    )
    categories: dict[str, int] = {}
    for case in rows:
        categories[case.category] = categories.get(case.category, 0) + 1
    return MatchingEvaluationReport(
        case_count=len(rows),
        positive_count=sum(1 for case in rows if case.matched),
        negative_count=sum(1 for case in rows if not case.matched),
        selected_threshold=selected.threshold,
        selected=selected,
        thresholds=metrics,
        calibration=_calibration(scored),
        category_counts=dict(sorted(categories.items())),
    )


def _threshold_metrics(
    scored: list[tuple[MatchingEvaluationCase, float]], threshold: float
) -> MatchingThresholdMetrics:
    tp = fp = tn = fn = 0
    for case, score in scored:
        predicted = score >= threshold
        if predicted and case.matched:
            tp += 1
        elif predicted and not case.matched:
            fp += 1
        elif not predicted and not case.matched:
            tn += 1
        else:
            fn += 1
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    false_match_rate = fp / (fp + tn) if fp + tn else 0.0
    return MatchingThresholdMetrics(
        threshold=threshold,
        true_positive=tp,
        false_positive=fp,
        true_negative=tn,
        false_negative=fn,
        precision=precision,
        recall=recall,
        f1=f1,
        false_match_rate=false_match_rate,
    )


def _calibration(
    scored: list[tuple[MatchingEvaluationCase, float]],
) -> list[MatchingCalibrationBucket]:
    boundaries = ((0.0, 0.5), (0.5, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.000001))
    buckets: list[MatchingCalibrationBucket] = []
    for lower, upper in boundaries:
        items = [(case, score) for case, score in scored if lower <= score < upper]
        if not items:
            continue
        buckets.append(
            MatchingCalibrationBucket(
                lower=lower,
                upper=min(upper, 1.0),
                count=len(items),
                average_confidence=sum(score for _, score in items) / len(items),
                observed_match_rate=sum(1 for case, _ in items if case.matched) / len(items),
            )
        )
    return buckets
