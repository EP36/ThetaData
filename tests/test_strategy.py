"""Tests for strategy modules."""

from __future__ import annotations

import pandas as pd
import pytest

from src.strategies.moving_average_crossover import MovingAverageCrossoverStrategy
from src.strategies.rsi_mean_reversion import RSIMeanReversionStrategy


def test_moving_average_strategy_generates_expected_regime() -> None:
    index = pd.date_range("2025-01-01", periods=10, freq="D")
    close = [1, 2, 3, 4, 5, 4, 3, 2, 1, 1]
    data = pd.DataFrame({"close": close}, index=index)

    strategy = MovingAverageCrossoverStrategy(short_window=2, long_window=3)
    signal_frame = strategy.generate_signals(data)
    signals = signal_frame["signal"]

    assert signal_frame.index.equals(data.index)
    assert "signal" in signal_frame.columns
    assert set(signals.unique()).issubset({0.0, 1.0})
    assert signals.iloc[4] == 1.0
    assert signals.iloc[-1] == 0.0


def test_rsi_mean_reversion_generates_long_signal_when_oversold() -> None:
    index = pd.date_range("2025-01-01", periods=10, freq="D")
    close = [100, 99, 98, 97, 96, 95, 94, 95, 96, 97]
    data = pd.DataFrame({"close": close}, index=index)

    strategy = RSIMeanReversionStrategy(lookback=3, oversold=40, overbought=60)
    signals = strategy.generate_signals(data)["signal"]

    assert signals.index.equals(data.index)
    assert set(signals.unique()).issubset({0.0, 1.0})
    assert signals.max() == 1.0


def test_rsi_parameters_are_validated() -> None:
    with pytest.raises(ValueError, match="oversold must be < overbought"):
        RSIMeanReversionStrategy(lookback=14, oversold=70, overbought=30)


def test_strategy_handles_short_data_without_error() -> None:
    data = pd.DataFrame({"close": [100.0]}, index=pd.date_range("2025-01-01", periods=1))
    strategy = RSIMeanReversionStrategy(lookback=14, oversold=30, overbought=70)
    signal = strategy.generate_signals(data)["signal"]
    assert len(signal) == 1
    assert signal.iloc[0] in {0.0, 1.0}
