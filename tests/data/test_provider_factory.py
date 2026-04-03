"""Tests for environment-driven market data provider selection."""

from __future__ import annotations

import pytest

from src.data.providers.alpaca import AlpacaMarketDataProvider
from src.data.providers.factory import make_market_data_provider_from_env
from src.data.providers.synthetic import SyntheticMarketDataProvider


def test_make_market_data_provider_defaults_to_synthetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATA_PROVIDER", raising=False)
    provider = make_market_data_provider_from_env()
    assert isinstance(provider, SyntheticMarketDataProvider)


def test_make_market_data_provider_alpaca_requires_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATA_PROVIDER", "alpaca")
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)

    with pytest.raises(ValueError, match="requires ALPACA_API_KEY and ALPACA_API_SECRET"):
        make_market_data_provider_from_env()


def test_make_market_data_provider_alpaca_ignores_broker_placeholders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATA_PROVIDER", "alpaca")
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    monkeypatch.setenv("BROKER_API_KEY", "test_key")
    monkeypatch.setenv("BROKER_API_SECRET", "test_secret")

    with pytest.raises(ValueError, match="requires ALPACA_API_KEY and ALPACA_API_SECRET"):
        make_market_data_provider_from_env()


def test_make_market_data_provider_alpaca_uses_alpaca_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATA_PROVIDER", "alpaca")
    monkeypatch.setenv("ALPACA_API_KEY", "alpaca_key")
    monkeypatch.setenv("ALPACA_API_SECRET", "alpaca_secret")
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)

    provider = make_market_data_provider_from_env()
    assert isinstance(provider, AlpacaMarketDataProvider)


def test_make_market_data_provider_alpaca_supports_legacy_secret_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATA_PROVIDER", "alpaca")
    monkeypatch.setenv("ALPACA_API_KEY", "alpaca_key")
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    monkeypatch.setenv("ALPACA_SECRET_KEY", "legacy_secret")

    provider = make_market_data_provider_from_env()
    assert isinstance(provider, AlpacaMarketDataProvider)
