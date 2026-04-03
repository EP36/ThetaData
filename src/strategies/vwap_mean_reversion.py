"""VWAP mean-reversion strategy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import numpy as np
import pandas as pd

from src.strategies.base import Strategy


@dataclass(slots=True)
class VWAPMeanReversionStrategy(Strategy):
    """Long-only VWAP reversion strategy with RSI confirmation."""

    name: ClassVar[str] = "vwap_mean_reversion"
    required_columns: ClassVar[tuple[str, ...]] = ("high", "low", "close", "volume")

    vwap_window: int = 20
    vwap_deviation: float = 0.02
    rsi_lookback: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    stop_loss_pct: float = 0.015
    target: str = "vwap"

    def __post_init__(self) -> None:
        """Validate strategy parameters."""
        if self.vwap_window <= 1:
            raise ValueError("vwap_window must be > 1")
        if self.vwap_deviation <= 0 or self.vwap_deviation >= 1:
            raise ValueError("vwap_deviation must be in (0, 1)")
        if self.rsi_lookback <= 1:
            raise ValueError("rsi_lookback must be > 1")
        if not 0 < self.rsi_oversold < 100:
            raise ValueError("rsi_oversold must be in (0, 100)")
        if not 0 < self.rsi_overbought < 100:
            raise ValueError("rsi_overbought must be in (0, 100)")
        if self.rsi_oversold >= self.rsi_overbought:
            raise ValueError("rsi_oversold must be < rsi_overbought")
        if self.stop_loss_pct <= 0 or self.stop_loss_pct >= 1:
            raise ValueError("stop_loss_pct must be in (0, 1)")
        if self.target.strip().lower() != "vwap":
            raise ValueError("target must be 'vwap'")

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """Generate long/flat regime from VWAP deviations + RSI filters."""
        self.validate_required_columns(data)

        high = data["high"].astype(float)
        low = data["low"].astype(float)
        close = data["close"].astype(float)
        volume = data["volume"].astype(float)

        typical_price = (high + low + close) / 3.0
        volume_window = volume.rolling(window=self.vwap_window, min_periods=1).sum()
        pv_window = (typical_price * volume).rolling(window=self.vwap_window, min_periods=1).sum()
        rolling_vwap = pv_window / volume_window.replace(0.0, np.nan)
        rolling_vwap = rolling_vwap.fillna(close)

        delta = close.diff().fillna(0.0)
        gains = np.where(delta > 0, delta, 0.0)
        losses = np.where(delta < 0, -delta, 0.0)
        avg_gain = pd.Series(gains, index=data.index).rolling(
            window=self.rsi_lookback,
            min_periods=1,
        ).mean()
        avg_loss = pd.Series(losses, index=data.index).rolling(
            window=self.rsi_lookback,
            min_periods=1,
        ).mean()
        rs = avg_gain / avg_loss.replace(0.0, np.nan)
        rsi = (100.0 - (100.0 / (1.0 + rs))).fillna(50.0)

        entry_condition = (
            (close <= rolling_vwap * (1.0 - self.vwap_deviation))
            & (rsi <= self.rsi_oversold)
        ).fillna(False)
        exit_condition = ((close >= rolling_vwap) | (rsi >= self.rsi_overbought)).fillna(False)

        signal_values: list[float] = []
        in_position = False
        for timestamp in data.index:
            if not in_position and bool(entry_condition.loc[timestamp]):
                in_position = True
            elif in_position and bool(exit_condition.loc[timestamp]):
                in_position = False
            signal_values.append(1.0 if in_position else 0.0)

        signal = pd.Series(signal_values, index=data.index, dtype=float)
        return pd.DataFrame({"signal": signal}, index=data.index)
