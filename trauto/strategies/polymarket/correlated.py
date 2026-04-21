"""Polymarket correlated-markets dominance-violation strategy."""

from __future__ import annotations

from typing import Any

from trauto.strategies.base import BaseStrategy, Signal, StrategySchedule, StrategyStatus


class CorrelatedMarketsStrategy(BaseStrategy):
    """BTC price-threshold dominance violation arb.

    Wraps src.polymarket.opportunities.detect_correlated_markets.
    Flags markets where P(BTC > higher_threshold) > P(BTC > lower_threshold).
    """

    name = "polymarket.correlated"
    broker = "polymarket"

    def __init__(self, config: "PolymarketConfig | None" = None, **kwargs: Any) -> None:
        kwargs.setdefault("schedule", StrategySchedule(type="interval", interval_sec=60.0))  # type: ignore[arg-type]
        super().__init__(**kwargs)
        self._config = config
        self._last_opps: list[Any] = []

    async def on_tick(self, market_data: dict[str, Any]) -> None:
        if self._config is None:
            return
        try:
            import asyncio
            from src.polymarket.scanner import fetch_btc_markets, fetch_market_orderbooks
            from src.polymarket.client import ClobClient
            from src.polymarket.opportunities import detect_correlated_markets

            client = ClobClient(config=self._config)

            def _sync() -> list:
                markets = fetch_btc_markets(client)
                if not markets:
                    return []
                orderbooks = fetch_market_orderbooks(client, markets)
                return detect_correlated_markets(orderbooks, min_edge_pct=self._config.min_edge_pct)

            opps = await asyncio.to_thread(_sync)
            self._last_opps = opps
            for opp in opps[:self.max_positions]:
                self.emit_signal(Signal(
                    strategy_name=self.name,
                    broker="polymarket",
                    symbol=opp.market_question[:40],
                    action="buy",
                    confidence=0.7,
                    price=0.0,
                    notes=f"correlated edge={opp.edge_pct:.2f}%",
                    extra={"market_question": opp.market_question, "action": opp.action},
                ))
        except Exception as exc:
            import logging
            logging.getLogger("trauto.strategies.polymarket.correlated").warning(
                "correlated_tick_error error=%s", exc
            )

    def get_status(self) -> StrategyStatus:
        return self._base_status(last_opportunities=len(self._last_opps))
