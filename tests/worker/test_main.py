"""Tests for worker entrypoint venue routing."""

from __future__ import annotations

from src.config.deployment import DeploymentSettings
from src.worker import __main__ as worker_main


def test_polymarket_venue_routes_only_to_polymarket(
    monkeypatch,
) -> None:
    settings = DeploymentSettings(
        trading_venue="polymarket",
        trading_mode="live",
        live_trading_enabled=True,
        worker_enable_trading=True,
        worker_dry_run=False,
        paper_trading_enabled=False,
        polymarket_dry_run=False,
        polymarket_credentials_configured=True,
    )
    calls: list[str] = []

    def _poly(settings_arg: DeploymentSettings) -> None:
        calls.append(settings_arg.execution_adapter)

    def _equities(_: DeploymentSettings) -> None:
        raise AssertionError("equities worker must not start for polymarket venue")

    monkeypatch.setattr(worker_main, "_run_polymarket_worker", _poly)
    monkeypatch.setattr(worker_main, "_run_equities_worker", _equities)

    worker_main._run_worker_for_settings(settings)

    assert calls == ["polymarket_clob"]
