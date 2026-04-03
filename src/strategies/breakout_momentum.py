"""Breakout momentum strategy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import pandas as pd

from src.strategies.base import Strategy


@dataclass(slots=True)
class BreakoutMomentumStrategy(Strategy):
    """Long-only breakout strategy using price and volume confirmation."""

    name: ClassVar[str] = "breakout_momentum"
    required_columns: ClassVar[tuple[str, ...]] = ("high", "close", "volume")

    lookback_period: int = 20
    breakout_threshold: float = 1.01
    volume_multiplier: float = 1.5
    stop_loss_pct: float = 0.02
    take_profit_pct: float = 0.05
    trailing_stop_pct: float = 0.02

    def __post_init__(self) -> None:
        """Validate strategy parameters."""
        if self.lookback_period <= 1:
            raise ValueError("lookback_period must be > 1")
        if self.breakout_threshold <= 1.0:
            raise ValueError("breakout_threshold must be > 1.0")
        if self.volume_multiplier <= 0:
            raise ValueError("volume_multiplier must be positive")
        if self.stop_loss_pct <= 0 or self.stop_loss_pct >= 1:
            raise ValueError("stop_loss_pct must be in (0, 1)")
        if self.take_profit_pct <= 0:
            raise ValueError("take_profit_pct must be positive")
        if self.trailing_stop_pct <= 0 or self.trailing_stop_pct >= 1:
            raise ValueError("trailing_stop_pct must be in (0, 1)")

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """Generate long/flat regime using breakout confirmation."""
        self.validate_required_columns(data)

        high = data["high"].astype(float)
        close = data["close"].astype(float)
        volume = data["volume"].astype(float)

        breakout_level = high.rolling(window=self.lookback_period, min_periods=1).max().shift(1)
        avg_volume = volume.rolling(window=self.lookback_period, min_periods=1).mean().shift(1)

        entry_condition = (
            (close >= breakout_level * self.breakout_threshold)
            & (volume >= avg_volume * self.volume_multiplier)
        ).fillna(False)
        exit_condition = (close < breakout_level).fillna(False)

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
