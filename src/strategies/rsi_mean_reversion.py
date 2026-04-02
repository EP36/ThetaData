"""RSI mean reversion strategy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import numpy as np
import pandas as pd

from src.strategies.base import Strategy


@dataclass(slots=True)
class RSIMeanReversionStrategy(Strategy):
    """Long-only RSI mean reversion strategy."""

    name: ClassVar[str] = "rsi_mean_reversion"
    required_columns: ClassVar[tuple[str, ...]] = ("close",)
    lookback: int = 14
    oversold: float = 30.0
    overbought: float = 70.0

    def __post_init__(self) -> None:
        """Validate strategy parameters."""
        if self.lookback <= 1:
            raise ValueError("lookback must be > 1")
        if not 0 < self.oversold < 100:
            raise ValueError("oversold must be in (0, 100)")
        if not 0 < self.overbought < 100:
            raise ValueError("overbought must be in (0, 100)")
        if self.oversold >= self.overbought:
            raise ValueError("oversold must be < overbought")

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """Generate long/flat signals from RSI thresholds."""
        self.validate_required_columns(data)

        close = data["close"].astype(float)
        delta = close.diff().fillna(0.0)
        gains = np.where(delta > 0, delta, 0.0)
        losses = np.where(delta < 0, -delta, 0.0)

        avg_gain = pd.Series(gains, index=data.index).rolling(
            window=self.lookback, min_periods=1
        ).mean()
        avg_loss = pd.Series(losses, index=data.index).rolling(
            window=self.lookback, min_periods=1
        ).mean()

        rs = avg_gain / avg_loss.replace(0.0, np.nan)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        rsi = rsi.fillna(50.0)

        signal = (rsi < self.oversold).astype(float)
        return pd.DataFrame({"signal": signal}, index=data.index)
