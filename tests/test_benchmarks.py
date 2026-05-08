from __future__ import annotations

from pathlib import Path

from commercelens.quality.benchmarks import run_benchmark_suite


def test_run_benchmark_suite() -> None:
    result = run_benchmark_suite(Path("tests/fixtures/benchmarks"))

    assert result.passed is True
    assert result.total_cases == 3
    assert result.score == 1.0
