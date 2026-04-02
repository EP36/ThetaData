"""Reusable service functions for CLI workflows."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path

import pandas as pd

from src.analytics.reporting import AnalyticsReport, generate_analytics_report
from src.backtest.engine import BacktestEngine, BacktestResult
from src.data.cache import DataCache
from src.data.loaders import HistoricalDataLoader
from src.data.providers.synthetic import SyntheticMarketDataProvider
from src.observability import clear_run, configure_logging, start_run
from src.risk.manager import RiskManager
from src.strategies import create_strategy

LOGGER = logging.getLogger("theta.cli.services")


@dataclass(slots=True)
class DownloadDataResult:
    """Result for download-data workflow."""

    rows: int
    cache_file: str


def make_default_loader(cache_dir: str | Path) -> HistoricalDataLoader:
    """Create default loader backed by synthetic provider + parquet cache."""
    provider = SyntheticMarketDataProvider()
    cache = DataCache(root_dir=Path(cache_dir))
    return HistoricalDataLoader(provider=provider, cache=cache)


def download_data(
    symbol: str,
    timeframe: str,
    start: str | None,
    end: str | None,
    cache_dir: str | Path,
    force_refresh: bool,
) -> DownloadDataResult:
    """Run data download/caching flow."""
    configure_logging()
    start_run()
    LOGGER.info(
        "download_data_start symbol=%s timeframe=%s start=%s end=%s force_refresh=%s",
        symbol,
        timeframe,
        start,
        end,
        force_refresh,
    )
    try:
        loader = make_default_loader(cache_dir=cache_dir)
        data = loader.load(
            symbol=symbol,
            timeframe=timeframe,
            start=start,
            end=end,
            force_refresh=force_refresh,
        )
        cache_path = loader.cache.cache_path(symbol=symbol, timeframe=timeframe)
        LOGGER.info(
            "download_data_complete symbol=%s timeframe=%s rows=%d cache_file=%s",
            symbol,
            timeframe,
            len(data),
            cache_path.resolve(),
        )
        return DownloadDataResult(rows=len(data), cache_file=str(cache_path.resolve()))
    finally:
        clear_run()


def run_backtest(
    symbol: str,
    timeframe: str,
    strategy_name: str,
    strategy_params: dict[str, object],
    start: str | None,
    end: str | None,
    cache_dir: str | Path,
    trade_log_path: str | Path,
    initial_capital: float,
    position_size_pct: float,
    fixed_fee: float,
    slippage_pct: float,
    stop_loss_pct: float | None,
    take_profit_pct: float | None,
    max_position_size: float,
    max_daily_loss: float,
    force_refresh: bool,
    run_id: str | None = None,
) -> BacktestResult:
    """Run backtest from cached/provider data and selected strategy."""
    configure_logging()
    active_run_id = start_run(run_id=run_id)
    LOGGER.info(
        "backtest_workflow_start symbol=%s timeframe=%s strategy=%s run_id=%s",
        symbol,
        timeframe,
        strategy_name,
        active_run_id,
    )

    loader = make_default_loader(cache_dir=cache_dir)
    data = loader.load(
        symbol=symbol,
        timeframe=timeframe,
        start=start,
        end=end,
        force_refresh=force_refresh,
    )

    strategy = create_strategy(strategy_name, **strategy_params)
    risk = RiskManager(
        max_position_size=max_position_size,
        max_daily_loss=max_daily_loss,
    )
    engine = BacktestEngine(
        initial_capital=initial_capital,
        position_size_pct=position_size_pct,
        fixed_fee=fixed_fee,
        slippage_pct=slippage_pct,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
    )
    try:
        result = engine.run(
            data=data,
            strategy=strategy,
            risk_manager=risk,
            trade_log_path=trade_log_path,
            symbol=symbol,
        )
        LOGGER.info(
            "backtest_workflow_complete symbol=%s strategy=%s run_id=%s trades=%d ending_equity=%.2f",
            symbol,
            strategy_name,
            active_run_id,
            len(result.trades),
            float(result.equity_curve.iloc[-1]) if not result.equity_curve.empty else 0.0,
        )
        return result
    finally:
        clear_run()


def generate_report(
    backtest_result: BacktestResult,
    output_dir: str | Path,
) -> AnalyticsReport:
    """Generate analytics report artifacts for a backtest result."""
    return generate_analytics_report(
        equity_curve=backtest_result.equity_curve,
        strategy_returns=backtest_result.strategy_returns,
        output_dir=output_dir,
    )


def parse_optional_float(value: str | None) -> float | None:
    """Parse optional float CLI argument."""
    if value is None or value == "":
        return None
    return float(value)


def parse_strategy_params(pairs: list[str] | None) -> dict[str, object]:
    """Parse strategy parameter pairs like key=value."""
    if not pairs:
        return {}

    parsed: dict[str, object] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"Invalid strategy param '{pair}'. Expected key=value format.")
        key, value = pair.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise ValueError("Strategy parameter key cannot be empty")

        if value.lower() in {"true", "false"}:
            parsed[key] = value.lower() == "true"
        else:
            try:
                parsed[key] = int(value)
            except ValueError:
                try:
                    parsed[key] = float(value)
                except ValueError:
                    parsed[key] = value
    return parsed
