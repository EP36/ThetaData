"""Tests for dashboard trading-status mode display."""

from __future__ import annotations

from src.api.services import TradingApiService
from src.config.deployment import DeploymentSettings


def _summary(settings: DeploymentSettings):
    service = TradingApiService(deployment_settings=settings)
    return service.dashboard_summary()


def test_polymarket_live_with_alpaca_disabled_status() -> None:
    summary = _summary(
        DeploymentSettings(
            trading_venue="polymarket",
            trading_mode="live",
            live_trading_enabled=True,
            signal_provider="alpaca",
            alpaca_api_key="alpaca-key",
            alpaca_api_secret="alpaca-secret",
            alpaca_trading_mode="disabled",
            poly_trading_mode="live",
            polymarket_dry_run=False,
            polymarket_credentials_configured=True,
            paper_trading_enabled=False,
            worker_enable_trading=True,
            worker_dry_run=False,
        )
    )

    assert summary.system_status == "polymarket_live"
    assert summary.trading_status.signal_provider == "alpaca"
    assert summary.trading_status.trading_venue == "polymarket"
    assert summary.trading_status.poly_trading_mode == "live"
    assert summary.trading_status.alpaca_trading_mode == "disabled"
    assert summary.trading_status.paper_trading_enabled is False


def test_polymarket_dry_run_status() -> None:
    summary = _summary(
        DeploymentSettings(
            trading_venue="polymarket",
            trading_mode="dry_run",
            signal_provider="synthetic",
            alpaca_trading_mode="disabled",
            poly_trading_mode="dry_run",
            polymarket_dry_run=True,
            paper_trading_enabled=False,
            worker_enable_trading=True,
            worker_dry_run=True,
        )
    )

    assert summary.system_status == "polymarket_dry_run"
    assert summary.trading_status.poly_trading_mode == "dry_run"
    assert summary.trading_status.poly_dry_run is True


def test_alpaca_paper_only_status() -> None:
    summary = _summary(
        DeploymentSettings(
            trading_venue="alpaca",
            trading_mode="paper",
            alpaca_trading_mode="paper",
            poly_trading_mode="disabled",
            polymarket_dry_run=True,
            paper_trading_enabled=True,
            worker_enable_trading=True,
            worker_dry_run=False,
        )
    )

    assert summary.system_status == "paper_only_idle"
    assert summary.trading_status.trading_venue == "alpaca"
    assert summary.trading_status.alpaca_trading_mode == "paper"
    assert summary.trading_status.poly_trading_mode == "disabled"


def test_both_venues_disabled_status() -> None:
    summary = _summary(
        DeploymentSettings(
            trading_venue="alpaca",
            trading_mode="disabled",
            alpaca_trading_mode="disabled",
            poly_trading_mode="disabled",
            polymarket_dry_run=True,
            paper_trading_enabled=False,
            worker_enable_trading=False,
            worker_dry_run=True,
        )
    )

    assert summary.system_status == "trading_disabled"
    assert summary.trading_status.alpaca_trading_mode == "disabled"
    assert summary.trading_status.poly_trading_mode == "disabled"
