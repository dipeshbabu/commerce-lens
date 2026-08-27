from __future__ import annotations

from pathlib import Path

from commercelens.quality.benchmarks import (
    BenchmarkGateConfig,
    build_quality_report,
    run_benchmark_suite,
)


FIXTURES = Path("tests/fixtures/benchmarks")


def test_run_benchmark_suite_covers_representative_cases() -> None:
    result = run_benchmark_suite(FIXTURES)

    assert result.passed is True
    assert result.total_cases == 25
    assert result.passed_cases == 25
    assert result.score == 1.0
    assert {case.mode for case in result.cases} == {"static", "rendered"}
    assert {case.kind for case in result.cases} == {"product", "listing"}
    assert any(case.degraded for case in result.cases)
    assert any("pagination" in case.tags for case in result.cases)
    assert any("variant" in case.tags for case in result.cases)
    assert any("bundle" in case.tags for case in result.cases)


def test_build_quality_report_exposes_release_metrics() -> None:
    report = build_quality_report(FIXTURES)

    assert report.passed is True
    assert report.total_cases == 25
    assert report.total_fields > 0
    assert report.passed_fields == report.total_fields
    assert report.by_kind["product"] == 1.0
    assert report.by_kind["listing"] == 1.0
    assert report.by_mode["static"] == 1.0
    assert report.by_mode["rendered"] == 1.0
    assert report.product_field_accuracy == 1.0
    assert report.price_accuracy == 1.0
    assert report.availability_accuracy == 1.0
    assert report.listing_recall == 1.0
    assert report.gate_failures == []
    assert report.latency
    assert report.confidence_calibration
    assert report.failure_distribution["degraded_but_recovered"] >= 1
    assert any(item.field == "product.name" for item in report.field_accuracy)


def test_quality_gate_rejects_regressed_threshold() -> None:
    report = build_quality_report(
        FIXTURES,
        gate=BenchmarkGateConfig(minimum_cases=26),
    )

    assert report.passed is False
    assert report.gate_failures == ["benchmark cases 25 < 26"]
