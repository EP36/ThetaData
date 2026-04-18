"""Tests for active intraday strategy profiles."""

from __future__ import annotations

import pandas as pd

from src.strategies.intraday import (
    BreakoutMomentumIntradayStrategy,
    OpeningRangeBreakoutStrategy,
    VWAPReclaimIntradayStrategy,
)


def _frame(
    index: pd.DatetimeIndex,
    close: list[float],
    volume: list[float],
) -> pd.DataFrame:
    close_series = pd.Series(close, index=index, dtype=float)
    return pd.DataFrame(
        {
            "open": close_series * 0.995,
            "high": close_series * 1.01,
            "low": close_series * 0.99,
            "close": close_series,
            "volume": pd.Series(volume, index=index, dtype=float),
        },
        index=index,
    )


def test_breakout_momentum_intraday_generates_entry_signal() -> None:
    index = pd.date_range("2026-04-16 10:00", periods=6, freq="5min")
    data = _frame(
        index=index,
        close=[100.0, 100.1, 100.2, 100.3, 100.4, 103.0],
        volume=[10_000.0, 10_000.0, 10_000.0, 10_000.0, 10_000.0, 30_000.0],
    )
    strategy = BreakoutMomentumIntradayStrategy(
        lookback_period=3,
        breakout_threshold=1.001,
        volume_multiplier=1.1,
    )

    signals = strategy.generate_signals(data)

    assert signals["signal"].iloc[-1] == 1.0


def test_opening_range_breakout_generates_entry_after_range() -> None:
    index = pd.DatetimeIndex(
        [
            "2026-04-16 09:30",
            "2026-04-16 09:45",
            "2026-04-16 10:00",
        ]
    )
    data = _frame(
        index=index,
        close=[100.0, 101.0, 103.0],
        volume=[25_000.0, 25_000.0, 50_000.0],
    )
    strategy = OpeningRangeBreakoutStrategy(
        range_start="09:30",
        range_end="09:45",
        breakout_threshold=1.001,
    )

    signals = strategy.generate_signals(data)

    assert signals["signal"].iloc[-1] == 1.0
    assert signals["signal"].iloc[0] == 0.0


def test_vwap_reclaim_intraday_detects_reclaim() -> None:
    index = pd.date_range("2026-04-16 10:00", periods=4, freq="5min")
    data = _frame(
        index=index,
        close=[100.0, 99.0, 101.0, 101.5],
        volume=[10_000.0, 10_000.0, 10_000.0, 10_000.0],
    )
    strategy = VWAPReclaimIntradayStrategy(vwap_window=3, trend_window=2)

    signals = strategy.generate_signals(data)

    assert signals["signal"].iloc[2] == 1.0
