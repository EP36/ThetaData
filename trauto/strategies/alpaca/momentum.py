"""Alpaca momentum strategy — wraps MovingAverageCrossoverStrategy."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from trauto.strategies.base import BaseStrategy, Signal, StrategyStatus

LOGGER = logging.getLogger("trauto.strategies.alpaca.momentum")


class MomentumStrategy(BaseStrategy):
    """Moving-average crossover momentum strategy for Alpaca equities.

    Wraps src.strategies.moving_average_crossover.MovingAverageCrossoverStrategy.
    Emits a 'buy' signal when short MA crosses above long MA, 'sell' when below.
    """

    name = "alpaca.momentum"
    broker = "alpaca"

    def __init__(
        self,
        short_window: int = 20,
        long_window: int = 50,
        symbols: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.short_window = short_window
        self.long_window = long_window
        self.symbols = symbols or ["SPY"]

        from src.strategies.moving_average_crossover import MovingAverageCrossoverStrategy
        self._inner = MovingAverageCrossoverStrategy(
            short_window=short_window,
            long_window=long_window,
        )
        self._last_signals: dict[str, float] = {}  # symbol → last signal value

    def on_start(self) -> None:
        super().on_start()
        self._last_signals.clear()

    async def on_bar(self, bars: dict[str, Any]) -> None:
        """Generate signals from completed bars for tracked symbols."""
        for symbol in self.symbols:
            if symbol not in bars:
                continue
            data = bars[symbol]
            if not isinstance(data, pd.DataFrame) or data.empty:
                continue
            try:
                sigs = self._inner.generate_signals(data)
                current_signal = float(sigs["signal"].iloc[-1])
                prev_signal = self._last_signals.get(symbol, 0.0)

                if current_signal > 0 and prev_signal <= 0:
                    # Crossover: short MA crossed above long MA — buy
                    price = float(data["close"].iloc[-1])
                    self.emit_signal(Signal(
                        strategy_name=self.name,
                        broker="alpaca",
                        symbol=symbol,
                        action="buy",
                        confidence=0.65,
                        price=price,
                        notes=f"ma_crossover short={self.short_window} long={self.long_window}",
                    ))
                elif current_signal <= 0 and prev_signal > 0:
                    # Short MA crossed below long MA — close position
                    price = float(data["close"].iloc[-1])
                    self.emit_signal(Signal(
                        strategy_name=self.name,
                        broker="alpaca",
                        symbol=symbol,
                        action="sell",
                        confidence=0.65,
                        price=price,
                        notes=f"ma_crossover_exit short={self.short_window} long={self.long_window}",
                    ))

                self._last_signals[symbol] = current_signal
            except Exception as exc:
                LOGGER.warning("momentum_signal_error symbol=%s error=%s", symbol, exc)

    def get_status(self) -> StrategyStatus:
        return self._base_status(
            short_window=self.short_window,
            long_window=self.long_window,
            symbols=self.symbols,
            tracked_signals=dict(self._last_signals),
        )
