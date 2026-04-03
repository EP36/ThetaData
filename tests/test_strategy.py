"""Tests for strategy modules."""

from __future__ import annotations

import pandas as pd
import pytest

from src.strategies.breakout_momentum import BreakoutMomentumStrategy
from src.strategies.moving_average_crossover import MovingAverageCrossoverStrategy
from src.strategies.rsi_mean_reversion import RSIMeanReversionStrategy
from src.strategies.vwap_mean_reversion import VWAPMeanReversionStrategy


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


def test_breakout_momentum_generates_entry_signal() -> None:
    index = pd.date_range("2025-01-01", periods=12, freq="D")
    data = pd.DataFrame(
        {
            "high": [100, 101, 102, 103, 104, 103, 104, 106, 108, 110, 112, 114],
            "close": [99, 100, 101, 102, 103, 102, 103, 105, 107, 109, 111, 113],
            "volume": [1000, 1000, 1000, 1000, 1000, 1100, 1200, 1300, 1800, 2100, 2200, 2300],
        },
        index=index,
    )
    strategy = BreakoutMomentumStrategy(
        lookback_period=5,
        breakout_threshold=1.005,
        volume_multiplier=1.2,
    )
    signal = strategy.generate_signals(data)["signal"]
    assert signal.index.equals(data.index)
    assert set(signal.unique()).issubset({0.0, 1.0})
    assert signal.max() == 1.0


def test_vwap_mean_reversion_generates_entry_signal() -> None:
    index = pd.date_range("2025-01-01", periods=15, freq="D")
    data = pd.DataFrame(
        {
            "high": [100, 101, 102, 102, 101, 100, 99, 98, 98, 99, 100, 101, 102, 103, 104],
            "low": [99, 100, 101, 101, 100, 99, 98, 97, 97, 98, 99, 100, 101, 102, 103],
            "close": [100, 101, 102, 101, 100, 99, 98, 97, 97, 98, 99, 100, 101, 102, 103],
            "volume": [1000] * 15,
        },
        index=index,
    )
    strategy = VWAPMeanReversionStrategy(vwap_window=5, vwap_deviation=0.01, rsi_lookback=3)
    signal = strategy.generate_signals(data)["signal"]
    assert signal.index.equals(data.index)
    assert set(signal.unique()).issubset({0.0, 1.0})


def test_new_strategy_parameter_validation() -> None:
    with pytest.raises(ValueError, match="breakout_threshold"):
        BreakoutMomentumStrategy(breakout_threshold=0.99)
    with pytest.raises(ValueError, match="target must be 'vwap'"):
        VWAPMeanReversionStrategy(target="close")
