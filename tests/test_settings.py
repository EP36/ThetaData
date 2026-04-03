"""Tests for runtime settings validation."""

from __future__ import annotations

import pytest

from src.config.settings import Settings


def build_settings(**overrides: object) -> Settings:
    """Create a valid Settings object with optional overrides."""
    base: dict[str, object] = {
        "data_api_key": "",
        "alpaca_api_key": "",
        "alpaca_api_secret": "",
        "alpaca_base_url": "https://paper-api.alpaca.markets",
        "initial_capital": 100_000.0,
        "position_size_pct": 1.0,
        "fixed_fee": 1.0,
        "slippage_pct": 0.0005,
        "stop_loss_pct": None,
        "take_profit_pct": None,
        "max_position_size": 1.0,
        "max_daily_loss": 2_000.0,
        "paper_trading_enabled": False,
        "max_notional_per_trade": 100_000.0,
        "executor_max_open_positions": 10,
        "executor_daily_loss_cap": 2_000.0,
        "trade_log_path": "logs/trades.csv",
    }
    base.update(overrides)
    return Settings(**base)


def test_settings_reject_invalid_initial_capital() -> None:
    with pytest.raises(ValueError, match="initial_capital"):
        build_settings(initial_capital=0.0)


def test_settings_reject_empty_trade_log_path() -> None:
    with pytest.raises(ValueError, match="trade_log_path"):
        build_settings(trade_log_path=" ")


def test_settings_reject_invalid_position_size() -> None:
    with pytest.raises(ValueError, match="position_size_pct"):
        build_settings(position_size_pct=1.5)


def test_settings_from_env_reads_canonical_alpaca_execution_vars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_API_SECRET", "secret")
    monkeypatch.setenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    settings = Settings.from_env()
    assert settings.alpaca_api_key == "key"
    assert settings.alpaca_api_secret == "secret"
    assert settings.alpaca_base_url == "https://paper-api.alpaca.markets"


def test_settings_from_env_supports_legacy_secret_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    monkeypatch.setenv("ALPACA_SECRET_KEY", "legacy-secret")
    settings = Settings.from_env()
    assert settings.alpaca_api_secret == "legacy-secret"
