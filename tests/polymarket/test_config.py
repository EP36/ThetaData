"""Tests for PolymarketConfig env-var loading and validation."""

from __future__ import annotations

import pytest

from src.polymarket.config import PolymarketConfig


def _set_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POLY_API_KEY", "test-key")
    monkeypatch.setenv("POLY_API_SECRET", "test-secret")
    monkeypatch.setenv("POLY_PASSPHRASE", "test-passphrase")
    monkeypatch.setenv("POLY_PRIVATE_KEY", "test-private-key")


def test_config_loads_required_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required(monkeypatch)

    cfg = PolymarketConfig.from_env()

    assert cfg.api_key == "test-key"
    assert cfg.api_secret == "test-secret"
    assert cfg.passphrase == "test-passphrase"
    assert cfg.private_key == "test-private-key"


def test_config_default_values(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required(monkeypatch)

    cfg = PolymarketConfig.from_env()

    assert cfg.scan_interval_sec == 30
    assert cfg.min_edge_pct == 1.5
    assert cfg.max_retries == 3
    assert cfg.timeout_seconds == 15.0
    assert cfg.clob_base_url == "https://clob.polymarket.com"
    assert "kalshi" in cfg.kalshi_base_url


def test_config_override_interval_and_edge(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required(monkeypatch)
    monkeypatch.setenv("POLY_SCAN_INTERVAL_SEC", "60")
    monkeypatch.setenv("POLY_MIN_EDGE_PCT", "3.0")

    cfg = PolymarketConfig.from_env()

    assert cfg.scan_interval_sec == 60
    assert cfg.min_edge_pct == 3.0


def test_config_raises_missing_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required(monkeypatch)
    monkeypatch.setenv("POLY_API_KEY", "")

    with pytest.raises(ValueError, match="POLY_API_KEY"):
        PolymarketConfig.from_env()


def test_config_raises_missing_api_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required(monkeypatch)
    monkeypatch.setenv("POLY_API_SECRET", "")

    with pytest.raises(ValueError, match="POLY_API_SECRET"):
        PolymarketConfig.from_env()


def test_config_raises_missing_passphrase(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required(monkeypatch)
    monkeypatch.setenv("POLY_PASSPHRASE", "")

    with pytest.raises(ValueError, match="POLY_PASSPHRASE"):
        PolymarketConfig.from_env()


def test_config_raises_missing_private_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required(monkeypatch)
    monkeypatch.setenv("POLY_PRIVATE_KEY", "")

    with pytest.raises(ValueError, match="POLY_PRIVATE_KEY"):
        PolymarketConfig.from_env()


def test_config_raises_non_positive_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required(monkeypatch)
    monkeypatch.setenv("POLY_SCAN_INTERVAL_SEC", "0")

    with pytest.raises(ValueError, match="scan_interval_sec"):
        PolymarketConfig.from_env()


def test_config_raises_non_positive_edge_pct(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required(monkeypatch)
    monkeypatch.setenv("POLY_MIN_EDGE_PCT", "-1.0")

    with pytest.raises(ValueError, match="min_edge_pct"):
        PolymarketConfig.from_env()


def test_live_config_requires_explicit_live_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required(monkeypatch)
    monkeypatch.setenv("POLY_DRY_RUN", "false")
    monkeypatch.setenv("TRADING_VENUE", "polymarket")
    monkeypatch.setenv("TRADING_MODE", "dry_run")
    monkeypatch.setenv("LIVE_TRADING", "false")

    with pytest.raises(ValueError, match="TRADING_MODE=live"):
        PolymarketConfig.from_env()


def test_live_config_loads_with_explicit_live_polymarket_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required(monkeypatch)
    monkeypatch.setenv("POLY_DRY_RUN", "false")
    monkeypatch.setenv("TRADING_VENUE", "polymarket")
    monkeypatch.setenv("TRADING_MODE", "live")
    monkeypatch.setenv("LIVE_TRADING", "true")

    cfg = PolymarketConfig.from_env()

    assert cfg.dry_run is False
    assert cfg.trading_mode == "live"
    assert cfg.trading_venue == "polymarket"
    assert cfg.live_trading_enabled is True
