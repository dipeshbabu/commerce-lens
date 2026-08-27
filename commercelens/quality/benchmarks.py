from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

from pydantic import BaseModel, Field

from commercelens.extractors.listing import extract_listing_from_html
from commercelens.extractors.product import extract_product_from_html


BenchmarkKind = Literal["product", "listing"]
BenchmarkMode = Literal["static", "rendered"]


class BenchmarkExpectation(BaseModel):
    kind: BenchmarkKind
    source_url: str | None = None
    fields: dict[str, Any] = Field(default_factory=dict)


class BenchmarkManifestCase(BenchmarkExpectation):
    name: str
    html: str
    mode: BenchmarkMode = "static"
    adapter: str = "generic"
    tags: list[str] = Field(default_factory=list)
    degraded: bool = False


class BenchmarkCaseResult(BaseModel):
    name: str
    kind: BenchmarkKind
    mode: BenchmarkMode = "static"
    adapter: str = "legacy"
    tags: list[str] = Field(default_factory=list)
    degraded: bool = False
    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    passed_fields: int = 0
    total_fields: int = 0
    failures: dict[str, dict[str, Any]] = Field(default_factory=dict)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    latency_ms: float = Field(default=0.0, ge=0.0)
    expected_listing_count: int | None = None
    actual_listing_count: int | None = None


class BenchmarkSuiteResult(BaseModel):
    fixture_dir: str
    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    passed_cases: int = 0
    total_cases: int = 0
    cases: list[BenchmarkCaseResult] = Field(default_factory=list)


class BenchmarkFieldAccuracy(BaseModel):
    field: str
    passed: int = 0
    total: int = 0
    score: float = Field(default=1.0, ge=0.0, le=1.0)


class BenchmarkLatencySummary(BaseModel):
    mode: BenchmarkMode
    cases: int = 0
    average_ms: float = 0.0
    p95_ms: float = 0.0


class BenchmarkConfidenceBucket(BaseModel):
    bucket: str
    cases: int = 0
    passed: int = 0
    pass_rate: float = Field(default=1.0, ge=0.0, le=1.0)


class BenchmarkGateConfig(BaseModel):
    minimum_cases: int = 25
    minimum_score: float = Field(default=0.98, ge=0.0, le=1.0)
    minimum_product_field_accuracy: float = Field(default=0.98, ge=0.0, le=1.0)
    minimum_price_accuracy: float = Field(default=0.98, ge=0.0, le=1.0)
    minimum_availability_accuracy: float = Field(default=0.98, ge=0.0, le=1.0)
    minimum_listing_recall: float = Field(default=0.98, ge=0.0, le=1.0)


class BenchmarkQualityReport(BaseModel):
    fixture_dir: str
    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    passed_cases: int = 0
    total_cases: int = 0
    passed_fields: int = 0
    total_fields: int = 0
    by_kind: dict[str, float] = Field(default_factory=dict)
    by_mode: dict[str, float] = Field(default_factory=dict)
    by_adapter: dict[str, float] = Field(default_factory=dict)
    field_accuracy: list[BenchmarkFieldAccuracy] = Field(default_factory=list)
    product_field_accuracy: float = Field(default=1.0, ge=0.0, le=1.0)
    price_accuracy: float = Field(default=1.0, ge=0.0, le=1.0)
    availability_accuracy: float = Field(default=1.0, ge=0.0, le=1.0)
    listing_recall: float = Field(default=1.0, ge=0.0, le=1.0)
    latency: list[BenchmarkLatencySummary] = Field(default_factory=list)
    failure_distribution: dict[str, int] = Field(default_factory=dict)
    confidence_calibration: list[BenchmarkConfidenceBucket] = Field(default_factory=list)
    failing_fields: dict[str, int] = Field(default_factory=dict)
    gate: BenchmarkGateConfig = Field(default_factory=BenchmarkGateConfig)
    gate_failures: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    cases: list[BenchmarkCaseResult] = Field(default_factory=list)


def _value_at_path(payload: Any, path: str) -> Any:
    current = payload
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return current


def _run_html_case(
    *,
    name: str,
    html: str,
    expectation: BenchmarkExpectation,
    mode: BenchmarkMode = "static",
    adapter: str = "legacy",
    tags: list[str] | None = None,
    degraded: bool = False,
) -> BenchmarkCaseResult:
    started = perf_counter()
    if expectation.kind == "product":
        extracted = extract_product_from_html(html, url=expectation.source_url).model_dump(
            mode="json"
        )
    else:
        extracted = extract_listing_from_html(html, url=expectation.source_url).model_dump(
            mode="json"
        )
    latency_ms = (perf_counter() - started) * 1000

    failures: dict[str, dict[str, Any]] = {}
    passed_fields = 0
    for path, expected in expectation.fields.items():
        actual = _value_at_path(extracted, path)
        if actual == expected:
            passed_fields += 1
        else:
            failures[path] = {"expected": expected, "actual": actual}

    total_fields = len(expectation.fields)
    score = 1.0 if total_fields == 0 else passed_fields / total_fields
    expected_listing_count = None
    actual_listing_count = None
    if expectation.kind == "listing":
        expected_count = expectation.fields.get("product_count")
        if isinstance(expected_count, int):
            expected_listing_count = expected_count
            actual_value = extracted.get("product_count")
            actual_listing_count = actual_value if isinstance(actual_value, int) else 0

    confidence = extracted.get("confidence")
    return BenchmarkCaseResult(
        name=name,
        kind=expectation.kind,
        mode=mode,
        adapter=adapter,
        tags=tags or [],
        degraded=degraded,
        passed=not failures,
        score=score,
        passed_fields=passed_fields,
        total_fields=total_fields,
        failures=failures,
        confidence=confidence if isinstance(confidence, (int, float)) else None,
        latency_ms=round(latency_ms, 3),
        expected_listing_count=expected_listing_count,
        actual_listing_count=actual_listing_count,
    )


def _legacy_cases(root: Path) -> list[BenchmarkCaseResult]:
    cases: list[BenchmarkCaseResult] = []
    for expectation_path in sorted(root.glob("*.expected.json")):
        html_path = expectation_path.with_suffix("").with_suffix(".html")
        if not html_path.exists():
            cases.append(
                BenchmarkCaseResult(
                    name=expectation_path.stem.removesuffix(".expected"),
                    kind="product",
                    passed=False,
                    score=0.0,
                    failures={"html": {"expected": str(html_path), "actual": None}},
                )
            )
            continue
        expectation = BenchmarkExpectation.model_validate_json(
            expectation_path.read_text(encoding="utf-8")
        )
        cases.append(
            _run_html_case(
                name=html_path.stem,
                html=html_path.read_text(encoding="utf-8"),
                expectation=expectation,
            )
        )
    return cases


def _manifest_cases(root: Path) -> list[BenchmarkCaseResult]:
    manifest_path = root / "quality_cases.json"
    if not manifest_path.exists():
        return []
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("quality_cases.json must contain a JSON array.")
    cases: list[BenchmarkCaseResult] = []
    names: set[str] = set()
    for item in raw:
        case = BenchmarkManifestCase.model_validate(item)
        if case.name in names:
            raise ValueError(f"Duplicate benchmark case name: {case.name}")
        names.add(case.name)
        cases.append(
            _run_html_case(
                name=case.name,
                html=case.html,
                expectation=case,
                mode=case.mode,
                adapter=case.adapter,
                tags=case.tags,
                degraded=case.degraded,
            )
        )
    return cases


def run_benchmark_suite(fixture_dir: str | Path) -> BenchmarkSuiteResult:
    root = Path(fixture_dir)
    cases = _legacy_cases(root) + _manifest_cases(root)
    total_cases = len(cases)
    passed_cases = sum(1 for case in cases if case.passed)
    score = 1.0 if not cases else sum(case.score for case in cases) / total_cases
    return BenchmarkSuiteResult(
        fixture_dir=str(root),
        passed=all(case.passed for case in cases),
        score=score,
        passed_cases=passed_cases,
        total_cases=total_cases,
        cases=cases,
    )


def _accuracy_for_fields(field_accuracy: list[BenchmarkFieldAccuracy], predicate: Any) -> float:
    selected = [item for item in field_accuracy if predicate(item.field)]
    passed = sum(item.passed for item in selected)
    total = sum(item.total for item in selected)
    return 1.0 if total == 0 else passed / total


def _group_scores(cases: list[BenchmarkCaseResult], attribute: str) -> dict[str, float]:
    groups: dict[str, list[float]] = {}
    for case in cases:
        value = str(getattr(case, attribute))
        groups.setdefault(value, []).append(case.score)
    return {key: sum(values) / len(values) for key, values in sorted(groups.items())}


def _latency_summary(cases: list[BenchmarkCaseResult]) -> list[BenchmarkLatencySummary]:
    summaries: list[BenchmarkLatencySummary] = []
    for mode in ("static", "rendered"):
        values = sorted(case.latency_ms for case in cases if case.mode == mode)
        if not values:
            continue
        p95_index = max(0, min(len(values) - 1, int(round(0.95 * len(values) + 0.5)) - 1))
        summaries.append(
            BenchmarkLatencySummary(
                mode=mode,
                cases=len(values),
                average_ms=round(sum(values) / len(values), 3),
                p95_ms=round(values[p95_index], 3),
            )
        )
    return summaries


def _confidence_summary(cases: list[BenchmarkCaseResult]) -> list[BenchmarkConfidenceBucket]:
    buckets: dict[str, list[BenchmarkCaseResult]] = {"low": [], "medium": [], "high": []}
    for case in cases:
        confidence = case.confidence or 0.0
        bucket = "high" if confidence >= 0.8 else "medium" if confidence >= 0.5 else "low"
        buckets[bucket].append(case)
    result: list[BenchmarkConfidenceBucket] = []
    for bucket in ("low", "medium", "high"):
        items = buckets[bucket]
        if not items:
            continue
        passed = sum(1 for item in items if item.passed)
        result.append(
            BenchmarkConfidenceBucket(
                bucket=bucket,
                cases=len(items),
                passed=passed,
                pass_rate=passed / len(items),
            )
        )
    return result


def _listing_recall(cases: list[BenchmarkCaseResult]) -> float:
    recalls: list[float] = []
    for case in cases:
        if case.kind != "listing" or case.expected_listing_count is None:
            continue
        expected = case.expected_listing_count
        actual = case.actual_listing_count or 0
        recalls.append(1.0 if expected == 0 else min(actual / expected, 1.0))
    return 1.0 if not recalls else sum(recalls) / len(recalls)


def build_quality_report(
    fixture_dir: str | Path,
    gate: BenchmarkGateConfig | None = None,
) -> BenchmarkQualityReport:
    suite = run_benchmark_suite(fixture_dir)
    gate = gate or BenchmarkGateConfig()
    field_totals: dict[str, int] = {}
    field_passed: dict[str, int] = {}
    failing_fields: dict[str, int] = {}
    failure_distribution: dict[str, int] = {}

    expectations: dict[str, dict[str, Any]] = {}
    root = Path(suite.fixture_dir)
    for expectation_path in root.glob("*.expected.json"):
        expectation = BenchmarkExpectation.model_validate_json(
            expectation_path.read_text(encoding="utf-8")
        )
        expectations[expectation_path.stem.removesuffix(".expected")] = expectation.fields
    manifest_path = root / "quality_cases.json"
    if manifest_path.exists():
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        for item in raw:
            manifest_case = BenchmarkManifestCase.model_validate(item)
            expectations[manifest_case.name] = manifest_case.fields

    for case in suite.cases:
        expected_fields = set(expectations.get(case.name, {}))
        for field in expected_fields:
            field_totals[field] = field_totals.get(field, 0) + 1
            if field not in case.failures:
                field_passed[field] = field_passed.get(field, 0) + 1
        for field in case.failures:
            failing_fields[field] = failing_fields.get(field, 0) + 1
        if case.failures:
            failure_distribution["field_mismatch"] = (
                failure_distribution.get("field_mismatch", 0) + 1
            )
        elif case.degraded:
            failure_distribution["degraded_but_recovered"] = (
                failure_distribution.get("degraded_but_recovered", 0) + 1
            )
        else:
            failure_distribution["clean_pass"] = failure_distribution.get("clean_pass", 0) + 1

    field_accuracy = [
        BenchmarkFieldAccuracy(
            field=field,
            passed=field_passed.get(field, 0),
            total=total,
            score=1.0 if total == 0 else field_passed.get(field, 0) / total,
        )
        for field, total in sorted(field_totals.items())
    ]
    product_field_accuracy = _accuracy_for_fields(
        field_accuracy,
        lambda field: (
            field.startswith("product.")
            and ".price." not in field
            and field != "product.availability"
        ),
    )
    price_accuracy = _accuracy_for_fields(field_accuracy, lambda field: ".price." in field)
    availability_accuracy = _accuracy_for_fields(
        field_accuracy, lambda field: field.endswith("availability")
    )
    listing_recall = _listing_recall(suite.cases)

    gate_failures: list[str] = []
    checks = [
        (
            suite.total_cases >= gate.minimum_cases,
            f"benchmark cases {suite.total_cases} < {gate.minimum_cases}",
        ),
        (
            suite.score >= gate.minimum_score,
            f"overall score {suite.score:.3f} < {gate.minimum_score:.3f}",
        ),
        (
            product_field_accuracy >= gate.minimum_product_field_accuracy,
            f"product field accuracy {product_field_accuracy:.3f} < {gate.minimum_product_field_accuracy:.3f}",
        ),
        (
            price_accuracy >= gate.minimum_price_accuracy,
            f"price accuracy {price_accuracy:.3f} < {gate.minimum_price_accuracy:.3f}",
        ),
        (
            availability_accuracy >= gate.minimum_availability_accuracy,
            f"availability accuracy {availability_accuracy:.3f} < {gate.minimum_availability_accuracy:.3f}",
        ),
        (
            listing_recall >= gate.minimum_listing_recall,
            f"listing recall {listing_recall:.3f} < {gate.minimum_listing_recall:.3f}",
        ),
    ]
    gate_failures.extend(message for passed, message in checks if not passed)

    recommendations: list[str] = []
    if failing_fields:
        worst_field = max(failing_fields.items(), key=lambda item: item[1])[0]
        recommendations.append(
            f"Prioritize extractor work on `{worst_field}`; it has the most failures."
        )
    if suite.total_cases < gate.minimum_cases:
        recommendations.append(
            f"Expand the benchmark suite to at least {gate.minimum_cases} representative cases."
        )
    if not gate_failures:
        recommendations.append(
            "Quality gate passed. Add a sanitized fixture for every extraction regression or customer escalation."
        )

    passed_fields = sum(case.passed_fields for case in suite.cases)
    total_fields = sum(case.total_fields for case in suite.cases)
    return BenchmarkQualityReport(
        fixture_dir=suite.fixture_dir,
        passed=suite.passed and not gate_failures,
        score=suite.score,
        passed_cases=suite.passed_cases,
        total_cases=suite.total_cases,
        passed_fields=passed_fields,
        total_fields=total_fields,
        by_kind=_group_scores(suite.cases, "kind"),
        by_mode=_group_scores(suite.cases, "mode"),
        by_adapter=_group_scores(suite.cases, "adapter"),
        field_accuracy=field_accuracy,
        product_field_accuracy=product_field_accuracy,
        price_accuracy=price_accuracy,
        availability_accuracy=availability_accuracy,
        listing_recall=listing_recall,
        latency=_latency_summary(suite.cases),
        failure_distribution=dict(sorted(failure_distribution.items())),
        confidence_calibration=_confidence_summary(suite.cases),
        failing_fields=dict(sorted(failing_fields.items())),
        gate=gate,
        gate_failures=gate_failures,
        recommendations=recommendations,
        cases=suite.cases,
    )
