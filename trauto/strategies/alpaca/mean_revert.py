"""Alpaca RSI mean-reversion strategy — wraps RSIMeanReversionStrategy."""

from __future__ import annotations

from typing import Any

import pandas as pd

from trauto.strategies.base import BaseStrategy, Signal, StrategyStatus


class MeanReversionStrategy(BaseStrategy):
    """RSI-based mean reversion strategy for Alpaca equities.

    Wraps src.strategies.rsi_mean_reversion.RSIMeanReversionStrategy.
    Oversold (RSI < oversold_threshold) → buy signal.
    Overbought (RSI > overbought_threshold) → sell signal.
    """

    name = "alpaca.mean_revert"
    broker = "alpaca"

    def __init__(
        self,
        rsi_period: int = 14,
        oversold_threshold: float = 30.0,
        overbought_threshold: float = 70.0,
        symbols: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.rsi_period = rsi_period
        self.oversold_threshold = oversold_threshold
        self.overbought_threshold = overbought_threshold
        self.symbols = symbols or ["SPY"]

        try:
            from src.strategies.rsi_mean_reversion import RSIMeanReversionStrategy
            self._inner = RSIMeanReversionStrategy(
                rsi_period=rsi_period,
                oversold_threshold=oversold_threshold,
                overbought_threshold=overbought_threshold,
            )
        except Exception:
            self._inner = None

    async def on_bar(self, bars: dict[str, Any]) -> None:
        if self._inner is None:
            return
        for symbol in self.symbols:
            if symbol not in bars:
                continue
            data = bars[symbol]
            if not isinstance(data, pd.DataFrame) or data.empty:
                continue
            try:
                sigs = self._inner.generate_signals(data)
                sig_val = float(sigs["signal"].iloc[-1])
                price = float(data["close"].iloc[-1])
                if sig_val > 0:
                    self.emit_signal(Signal(
                        strategy_name=self.name,
                        broker="alpaca",
                        symbol=symbol,
                        action="buy",
                        confidence=0.55,
                        price=price,
                        notes=f"rsi_oversold period={self.rsi_period}",
                    ))
                elif sig_val < 0:
                    self.emit_signal(Signal(
                        strategy_name=self.name,
                        broker="alpaca",
                        symbol=symbol,
                        action="sell",
                        confidence=0.55,
                        price=price,
                        notes=f"rsi_overbought period={self.rsi_period}",
                    ))
            except Exception:
                pass

    def get_status(self) -> StrategyStatus:
        return self._base_status(
            rsi_period=self.rsi_period,
            oversold_threshold=self.oversold_threshold,
            overbought_threshold=self.overbought_threshold,
            symbols=self.symbols,
        )
