"""Simple rule-based market regime classification for strategy selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

RegimeState = Literal["trending", "mean_reverting", "neutral"]


@dataclass(frozen=True, slots=True)
class RegimeClassification:
    """Output from deterministic regime classification."""

    state: RegimeState
    moving_average_slope: float
    price_vs_moving_average: float
    atr_pct: float
    directional_persistence: float

    def as_signals(self) -> dict[str, float]:
        """Serialize signals used in classification for API/logging."""
        return {
            "moving_average_slope": float(self.moving_average_slope),
            "price_vs_moving_average": float(self.price_vs_moving_average),
            "atr_pct": float(self.atr_pct),
            "directional_persistence": float(self.directional_persistence),
        }


def classify_regime(
    data: pd.DataFrame,
    lookback: int = 20,
) -> RegimeClassification:
    """Classify market regime from OHLCV data using transparent rule-based signals."""
    required = {"high", "low", "close"}
    if not required.issubset(set(data.columns)) or len(data) < max(lookback, 3):
        return RegimeClassification(
            state="neutral",
            moving_average_slope=0.0,
            price_vs_moving_average=0.0,
            atr_pct=0.0,
            directional_persistence=0.0,
        )

    close = data["close"].astype(float)
    high = data["high"].astype(float)
    low = data["low"].astype(float)

    moving_average = close.rolling(window=lookback, min_periods=lookback).mean()
    if moving_average.isna().all():
        ma_slope = 0.0
        price_vs_ma = 0.0
    else:
        ma_recent = moving_average.dropna()
        if len(ma_recent) >= 2:
            ma_slope = float((ma_recent.iloc[-1] - ma_recent.iloc[-2]) / max(abs(ma_recent.iloc[-2]), 1e-9))
        else:
            ma_slope = 0.0
        ma_last = float(ma_recent.iloc[-1])
        price_vs_ma = float((close.iloc[-1] - ma_last) / max(abs(ma_last), 1e-9))

    prev_close = close.shift(1)
    true_range = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = true_range.rolling(window=lookback, min_periods=lookback).mean()
    atr_last = float(atr.iloc[-1]) if not np.isnan(atr.iloc[-1]) else 0.0
    atr_pct = float(atr_last / max(abs(close.iloc[-1]), 1e-9))

    returns = close.pct_change().dropna()
    recent_returns = returns.iloc[-lookback:] if len(returns) >= lookback else returns
    if recent_returns.empty:
        directional_persistence = 0.0
    else:
        signs = np.sign(recent_returns.to_numpy())
        directional_persistence = float(abs(signs.mean()))

    # Interpretable rules:
    # trending: strong MA slope + price dislocation + persistent direction
    # mean-reverting: weak slope + low directional persistence + moderate volatility
    if (
        abs(ma_slope) >= 0.001
        and abs(price_vs_ma) >= 0.005
        and directional_persistence >= 0.45
    ):
        state: RegimeState = "trending"
    elif (
        abs(ma_slope) < 0.0008
        and abs(price_vs_ma) < 0.01
        and directional_persistence <= 0.35
        and atr_pct > 0.0
    ):
        state = "mean_reverting"
    else:
        state = "neutral"

    return RegimeClassification(
        state=state,
        moving_average_slope=float(ma_slope),
        price_vs_moving_average=float(price_vs_ma),
        atr_pct=float(atr_pct),
        directional_persistence=float(directional_persistence),
    )
