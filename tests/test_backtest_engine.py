"""Tests for long-only backtest simulation behavior."""

from __future__ import annotations

import pandas as pd
import pytest

from src.backtest.engine import BacktestEngine
from src.backtest.reporting import TRADE_LOG_COLUMNS
from src.strategies.base import Strategy


class SeriesSignalStrategy(Strategy):
    """Strategy backed by an explicit signal series."""

    name = "series_signal_strategy"
    required_columns = ("close",)

    def __init__(self, signals: list[float]) -> None:
        self._signals = signals

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        self.validate_required_columns(data)
        return pd.DataFrame(
            {"signal": pd.Series(self._signals, index=data.index, dtype=float)},
            index=data.index,
        )


def make_ohlcv(close_prices: list[float]) -> pd.DataFrame:
    """Build a simple OHLCV DataFrame for tests."""
    index = pd.date_range("2025-01-01", periods=len(close_prices), freq="D")
    close = pd.Series(close_prices, index=index)
    data = pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1000.0,
        },
        index=index,
    )
    return data


def test_fill_logic_applies_fixed_fee_and_slippage() -> None:
    data = make_ohlcv([100.0, 100.0, 100.0])
    strategy = SeriesSignalStrategy([1.0, 0.0, 0.0])
    engine = BacktestEngine(
        initial_capital=10_000.0,
        position_size_pct=0.5,
        fixed_fee=10.0,
        slippage_pct=0.01,
    )

    result = engine.run(data=data, strategy=strategy)
    assert len(result.trades) == 2

    buy = result.trades[0]
    sell = result.trades[1]
    assert buy.side == "BUY"
    assert buy.fill_price == pytest.approx(101.0)
    assert buy.quantity == pytest.approx(50.0)
    assert sell.side == "SELL"
    assert sell.fill_price == pytest.approx(99.0)


def test_pnl_calculation_for_round_trip_trade() -> None:
    data = make_ohlcv([100.0, 100.0, 110.0])
    strategy = SeriesSignalStrategy([1.0, 0.0, 0.0])
    engine = BacktestEngine(
        initial_capital=10_000.0,
        position_size_pct=1.0,
        fixed_fee=0.0,
        slippage_pct=0.0,
    )

    result = engine.run(data=data, strategy=strategy)
    assert result.equity_curve.iloc[-1] == pytest.approx(11_000.0)
    assert [trade.side for trade in result.trades] == ["BUY", "SELL"]


def test_fee_and_slippage_reduce_performance() -> None:
    data = make_ohlcv([100.0, 100.0, 100.0])
    strategy = SeriesSignalStrategy([1.0, 0.0, 0.0])

    no_cost_engine = BacktestEngine(
        initial_capital=10_000.0,
        position_size_pct=1.0,
        fixed_fee=0.0,
        slippage_pct=0.0,
    )
    with_cost_engine = BacktestEngine(
        initial_capital=10_000.0,
        position_size_pct=1.0,
        fixed_fee=5.0,
        slippage_pct=0.01,
    )

    result_no_cost = no_cost_engine.run(data=data, strategy=strategy)
    result_with_cost = with_cost_engine.run(data=data, strategy=strategy)

    assert result_no_cost.equity_curve.iloc[-1] > result_with_cost.equity_curve.iloc[-1]


def test_stop_loss_exit_is_applied() -> None:
    data = make_ohlcv([100.0, 100.0, 95.0])
    data.loc[data.index[2], "low"] = 94.0
    strategy = SeriesSignalStrategy([1.0, 1.0, 1.0])
    engine = BacktestEngine(
        initial_capital=10_000.0,
        position_size_pct=1.0,
        fixed_fee=0.0,
        slippage_pct=0.0,
        stop_loss_pct=0.05,
    )

    result = engine.run(data=data, strategy=strategy)
    assert result.trades[-1].reason == "stop_loss"
    assert result.equity_curve.iloc[-1] == pytest.approx(9_500.0)


def test_trade_log_schema_when_no_trades(tmp_path) -> None:
    data = make_ohlcv([100.0, 100.0, 100.0])
    strategy = SeriesSignalStrategy([0.0, 0.0, 0.0])
    engine = BacktestEngine(
        initial_capital=10_000.0,
        position_size_pct=1.0,
        fixed_fee=0.0,
        slippage_pct=0.0,
    )

    output_path = tmp_path / "trades.csv"
    result = engine.run(data=data, strategy=strategy, trade_log_path=output_path)
    persisted = pd.read_csv(output_path)

    assert result.trades == []
    assert list(persisted.columns) == list(TRADE_LOG_COLUMNS)


def test_backtest_engine_rejects_invalid_cost_settings() -> None:
    with pytest.raises(ValueError, match="fixed_fee"):
        BacktestEngine(initial_capital=100_000.0, fixed_fee=-1.0)
