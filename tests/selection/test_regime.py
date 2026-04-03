"""Tests for simple regime classification."""

from __future__ import annotations

import pandas as pd

from src.selection.regime import classify_regime


def _ohlcv_from_close(close_values: list[float]) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=len(close_values), freq="h")
    close = pd.Series(close_values, index=index)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 1_000.0,
        },
        index=index,
    )


def test_trending_regime_detected() -> None:
    data = _ohlcv_from_close([100 + i * 0.8 for i in range(40)])
    regime = classify_regime(data, lookback=20)
    assert regime.state == "trending"


def test_mean_reverting_regime_detected() -> None:
    base = [100, 101, 99, 100, 101, 99, 100, 101, 99, 100] * 4
    data = _ohlcv_from_close(base)
    regime = classify_regime(data, lookback=20)
    assert regime.state in {"mean_reverting", "neutral"}


def test_insufficient_data_defaults_to_neutral() -> None:
    data = _ohlcv_from_close([100, 101, 102])
    regime = classify_regime(data, lookback=20)
    assert regime.state == "neutral"
