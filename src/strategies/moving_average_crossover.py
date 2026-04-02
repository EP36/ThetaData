"""Moving average crossover strategy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import pandas as pd

from src.strategies.base import Strategy


@dataclass(slots=True)
class MovingAverageCrossoverStrategy(Strategy):
    """Simple long/flat moving-average crossover strategy."""

    name: ClassVar[str] = "moving_average_crossover"
    required_columns: ClassVar[tuple[str, ...]] = ("close",)
    short_window: int = 20
    long_window: int = 50

    def __post_init__(self) -> None:
        """Validate strategy parameters."""
        if self.short_window <= 0 or self.long_window <= 0:
            raise ValueError("Moving-average windows must be positive")
        if self.short_window >= self.long_window:
            raise ValueError("short_window must be < long_window")

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """Generate long/flat signals based on MA crossover."""
        self.validate_required_columns(data)

        close = data["close"].astype(float)
        short_ma = close.rolling(window=self.short_window, min_periods=1).mean()
        long_ma = close.rolling(window=self.long_window, min_periods=1).mean()

        signal = (short_ma > long_ma).astype(float)
        return pd.DataFrame({"signal": signal}, index=data.index)
