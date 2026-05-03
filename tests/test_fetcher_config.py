import pytest

from commercelens.core.fetcher import DEFAULT_USER_AGENT, FetchError, _configured_timeout, _configured_user_agent


def test_user_agent_can_be_configured(monkeypatch) -> None:
    monkeypatch.setenv("COMMERCELENS_USER_AGENT", "CommerceLensTest/1.0")

    assert _configured_user_agent() == "CommerceLensTest/1.0"


def test_user_agent_defaults_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("COMMERCELENS_USER_AGENT", raising=False)

    assert _configured_user_agent() == DEFAULT_USER_AGENT


def test_timeout_can_be_configured(monkeypatch) -> None:
    monkeypatch.setenv("COMMERCELENS_DEFAULT_TIMEOUT_SECONDS", "7.5")

    assert _configured_timeout(20.0) == 7.5


def test_invalid_timeout_is_clear(monkeypatch) -> None:
    monkeypatch.setenv("COMMERCELENS_DEFAULT_TIMEOUT_SECONDS", "slow")

    with pytest.raises(FetchError, match="must be a number"):
        _configured_timeout(20.0)
