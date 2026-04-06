"""Simple moving-average regime helper for paper-trading gating."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.trading.types import MarketRegime

EPSILON = 1e-12


@dataclass(frozen=True, slots=True)
class MarketRegimeEvaluation:
    """Deterministic market-regime output for gating and logging."""

    regime: MarketRegime
    short_moving_average: float | None
    long_moving_average: float | None
    spread_pct: float | None


def get_market_regime(
    data: pd.DataFrame,
    *,
    short_window: int,
    long_window: int,
    threshold_pct: float = 0.001,
) -> MarketRegimeEvaluation:
    """Classify a simple bullish/sideways/bearish regime from MA spread."""
    if (
        "close" not in data.columns
        or short_window <= 0
        or long_window <= 0
        or short_window >= long_window
        or len(data) < long_window
    ):
        return MarketRegimeEvaluation(
            regime="unknown",
            short_moving_average=None,
            long_moving_average=None,
            spread_pct=None,
        )

    close = data["close"].astype(float)
    short_ma = close.rolling(window=short_window, min_periods=short_window).mean().iloc[-1]
    long_ma = close.rolling(window=long_window, min_periods=long_window).mean().iloc[-1]
    if pd.isna(short_ma) or pd.isna(long_ma) or abs(float(long_ma)) <= EPSILON:
        return MarketRegimeEvaluation(
            regime="unknown",
            short_moving_average=None,
            long_moving_average=None,
            spread_pct=None,
        )

    short_value = float(short_ma)
    long_value = float(long_ma)
    spread_pct = float((short_value - long_value) / abs(long_value))
    if spread_pct >= threshold_pct:
        regime: MarketRegime = "bullish"
    elif spread_pct <= -threshold_pct:
        regime = "bearish"
    else:
        regime = "sideways"

    return MarketRegimeEvaluation(
        regime=regime,
        short_moving_average=short_value,
        long_moving_average=long_value,
        spread_pct=spread_pct,
    )
