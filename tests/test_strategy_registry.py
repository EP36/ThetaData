"""Tests for strategy registry and strategy contract behavior."""

from __future__ import annotations

import pandas as pd
import pytest

from src.backtest.engine import BacktestEngine
from src.strategies import create_strategy, get_strategy_class, list_strategies
from src.strategies.base import Strategy
from src.strategies.registry import clear_registry, register_strategy


def test_registry_contains_default_strategy() -> None:
    assert "moving_average_crossover" in list_strategies()
    assert "rsi_mean_reversion" in list_strategies()
    assert "breakout_momentum" in list_strategies()
    assert "vwap_mean_reversion" in list_strategies()
    assert "breakout_momentum_intraday" in list_strategies()
    assert "opening_range_breakout" in list_strategies()
    assert "vwap_reclaim_intraday" in list_strategies()
    assert "pullback_trend_continuation" in list_strategies()
    assert "mean_reversion_scalp" in list_strategies()
    strategy_cls = get_strategy_class("moving_average_crossover")
    strategy = strategy_cls(short_window=5, long_window=10)
    assert strategy.name == "moving_average_crossover"


def test_create_strategy_by_name() -> None:
    strategy = create_strategy("moving_average_crossover", short_window=3, long_window=6)
    assert strategy.name == "moving_average_crossover"


def test_required_column_validation_fails_clearly() -> None:
    index = pd.date_range("2025-01-01", periods=5, freq="D")
    bad_data = pd.DataFrame(
        {
            "open": [1, 1, 1, 1, 1],
            "high": [1, 1, 1, 1, 1],
            "low": [1, 1, 1, 1, 1],
            "volume": [1, 1, 1, 1, 1],
        },
        index=index,
    )
    strategy = create_strategy("moving_average_crossover", short_window=2, long_window=3)

    with pytest.raises(ValueError, match="required columns"):
        strategy.generate_signals(bad_data)


def test_register_duplicate_strategy_name_raises() -> None:
    clear_registry()

    class DummyStrategy(Strategy):
        name = "dummy"
        required_columns = ("close",)

        def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
            return pd.DataFrame({"signal": 0.0}, index=data.index)

    register_strategy(DummyStrategy)

    class DuplicateDummyStrategy(Strategy):
        name = "dummy"
        required_columns = ("close",)

        def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
            return pd.DataFrame({"signal": 0.0}, index=data.index)

    with pytest.raises(ValueError, match="already registered"):
        register_strategy(DuplicateDummyStrategy)

    # Restore default strategies for other tests.
    clear_registry()
    from src.strategies import (
        BreakoutMomentumIntradayStrategy,
        BreakoutMomentumStrategy,
        MeanReversionScalpStrategy,
        MovingAverageCrossoverStrategy,
        OpeningRangeBreakoutStrategy,
        PullbackTrendContinuationStrategy,
        RSIMeanReversionStrategy,
        VWAPReclaimIntradayStrategy,
        VWAPMeanReversionStrategy,
    )

    register_strategy(MovingAverageCrossoverStrategy)
    register_strategy(RSIMeanReversionStrategy)
    register_strategy(BreakoutMomentumStrategy)
    register_strategy(VWAPMeanReversionStrategy)
    register_strategy(BreakoutMomentumIntradayStrategy)
    register_strategy(OpeningRangeBreakoutStrategy)
    register_strategy(VWAPReclaimIntradayStrategy)
    register_strategy(PullbackTrendContinuationStrategy)
    register_strategy(MeanReversionScalpStrategy)


def test_engine_uses_strategy_required_column_validation() -> None:
    class NeedsCustomColumnStrategy(Strategy):
        name = "needs_custom_column"
        required_columns = ("custom",)

        def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
            return pd.DataFrame({"signal": 0.0}, index=data.index)

    index = pd.date_range("2025-01-01", periods=3, freq="D")
    data = pd.DataFrame(
        {
            "open": [100, 100, 100],
            "high": [101, 101, 101],
            "low": [99, 99, 99],
            "close": [100, 100, 100],
            "volume": [1000, 1000, 1000],
        },
        index=index,
    )

    engine = BacktestEngine(
        initial_capital=10_000.0,
        position_size_pct=1.0,
        fixed_fee=0.0,
        slippage_pct=0.0,
    )

    with pytest.raises(ValueError, match="missing required columns"):
        engine.run(data=data, strategy=NeedsCustomColumnStrategy())


def test_both_sample_strategies_run_through_backtester() -> None:
    index = pd.date_range("2025-01-01", periods=40, freq="D")
    data = pd.DataFrame(
        {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": pd.Series(range(80, 120), index=index, dtype=float).values,
            "volume": 1000.0,
        },
        index=index,
    )
    engine = BacktestEngine(
        initial_capital=10_000.0,
        position_size_pct=1.0,
        fixed_fee=0.0,
        slippage_pct=0.0,
    )

    ma = create_strategy("moving_average_crossover", short_window=5, long_window=20)
    rsi = create_strategy("rsi_mean_reversion", lookback=5, oversold=30, overbought=70)
    breakout = create_strategy("breakout_momentum", lookback_period=5)
    vwap = create_strategy("vwap_mean_reversion", vwap_window=5)

    ma_result = engine.run(data=data, strategy=ma)
    rsi_result = engine.run(data=data, strategy=rsi)
    breakout_result = engine.run(data=data, strategy=breakout)
    vwap_result = engine.run(data=data, strategy=vwap)

    assert len(ma_result.equity_curve) == len(data)
    assert len(rsi_result.equity_curve) == len(data)
    assert len(breakout_result.equity_curve) == len(data)
    assert len(vwap_result.equity_curve) == len(data)
