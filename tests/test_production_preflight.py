from __future__ import annotations

from commercelens.ops.preflight import run_production_preflight


def test_production_preflight_blocks_missing_required_env() -> None:
    result = run_production_preflight({})

    assert result.passed is False
    assert result.blockers == 5
    assert result.warnings == 2


def test_production_preflight_passes_required_env_with_warnings() -> None:
    result = run_production_preflight(
        {
            "COMMERCELENS_ENV": "production",
            "COMMERCELENS_STORE_BACKEND": "postgres",
            "COMMERCELENS_DATABASE_URL": "postgresql://user:pass@localhost/db",
            "COMMERCELENS_REQUIRE_API_KEY": "true",
            "COMMERCELENS_ADMIN_TOKEN": "a-very-long-random-admin-token",
        }
    )

    assert result.passed is True
    assert result.blockers == 0
    assert result.warnings == 2
