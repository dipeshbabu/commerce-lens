from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from commercelens.extractors.listing import extract_listing_from_html
from commercelens.extractors.product import extract_product_from_html


BenchmarkKind = Literal["product", "listing"]


class BenchmarkExpectation(BaseModel):
    kind: BenchmarkKind
    source_url: str | None = None
    fields: dict[str, Any] = Field(default_factory=dict)


class BenchmarkCaseResult(BaseModel):
    name: str
    kind: BenchmarkKind
    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    passed_fields: int = 0
    total_fields: int = 0
    failures: dict[str, dict[str, Any]] = Field(default_factory=dict)


class BenchmarkSuiteResult(BaseModel):
    fixture_dir: str
    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    passed_cases: int = 0
    total_cases: int = 0
    cases: list[BenchmarkCaseResult] = Field(default_factory=list)


def _value_at_path(payload: Any, path: str) -> Any:
    current = payload
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            current = current[int(part)]
        else:
            return None
    return current


def _run_case(html_path: Path, expectation: BenchmarkExpectation) -> BenchmarkCaseResult:
    html = html_path.read_text(encoding="utf-8")
    if expectation.kind == "product":
        extracted = extract_product_from_html(html, url=expectation.source_url).model_dump(mode="json")
    else:
        extracted = extract_listing_from_html(html, url=expectation.source_url).model_dump(mode="json")

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
    return BenchmarkCaseResult(
        name=html_path.stem,
        kind=expectation.kind,
        passed=not failures,
        score=score,
        passed_fields=passed_fields,
        total_fields=total_fields,
        failures=failures,
    )


def run_benchmark_suite(fixture_dir: str | Path) -> BenchmarkSuiteResult:
    root = Path(fixture_dir)
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
        cases.append(_run_case(html_path, expectation))

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
