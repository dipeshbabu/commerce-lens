from __future__ import annotations

from pathlib import Path

from commercelens.quality.benchmarks import build_quality_report, run_benchmark_suite


def test_run_benchmark_suite() -> None:
    result = run_benchmark_suite(Path("tests/fixtures/benchmarks"))

    assert result.passed is True
    assert result.total_cases == 3
    assert result.score == 1.0


def test_build_quality_report_includes_field_accuracy() -> None:
    report = build_quality_report(Path("tests/fixtures/benchmarks"))

    assert report.passed is True
    assert report.total_cases == 3
    assert report.total_fields > 0
    assert report.passed_fields == report.total_fields
    assert report.by_kind["product"] == 1.0
    assert any(item.field == "product.name" for item in report.field_accuracy)
    assert report.recommendations
