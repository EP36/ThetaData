"""Tests for additive market-regime classification."""

from __future__ import annotations

import pandas as pd

from src.trading.regime import get_market_regime


def _frame(closes: list[float]) -> pd.DataFrame:
    index = pd.date_range("2026-01-05 10:00", periods=len(closes), freq="1h")
    return pd.DataFrame({"close": closes}, index=index)


def test_get_market_regime_classifies_bullish() -> None:
    result = get_market_regime(_frame([96.0, 97.0, 98.0, 99.0, 100.0]), short_window=2, long_window=4)
    assert result.regime == "bullish"


def test_get_market_regime_classifies_bearish() -> None:
    result = get_market_regime(_frame([100.0, 99.0, 98.0, 97.0, 96.0]), short_window=2, long_window=4)
    assert result.regime == "bearish"


def test_get_market_regime_classifies_sideways() -> None:
    result = get_market_regime(
        _frame([100.0, 100.0, 100.0, 100.0, 100.1]),
        short_window=2,
        long_window=4,
        threshold_pct=0.001,
    )
    assert result.regime == "sideways"


def test_get_market_regime_returns_unknown_on_insufficient_data() -> None:
    result = get_market_regime(_frame([100.0, 101.0]), short_window=2, long_window=4)
    assert result.regime == "unknown"
