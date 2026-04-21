"""Polymarket cross-market (Poly vs Kalshi) arb strategy."""

from __future__ import annotations

from typing import Any

from trauto.strategies.base import BaseStrategy, Signal, StrategySchedule, StrategyStatus


class CrossMarketStrategy(BaseStrategy):
    """Cross-venue arb between Polymarket and Kalshi.

    Wraps src.polymarket.opportunities.detect_cross_market.
    Emits signals when a matched question has price discrepancy > min_edge_pct.
    """

    name = "polymarket.cross_market"
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
            from src.polymarket.opportunities import detect_cross_market

            client = ClobClient(config=self._config)

            def _sync() -> list:
                markets = fetch_btc_markets(client)
                if not markets:
                    return []
                orderbooks = fetch_market_orderbooks(client, markets)
                return detect_cross_market(
                    orderbooks,
                    kalshi_base_url=self._config.kalshi_base_url,
                    min_edge_pct=self._config.min_edge_pct,
                    timeout=self._config.timeout_seconds,
                )

            opps = await asyncio.to_thread(_sync)
            self._last_opps = opps
            for opp in opps[:self.max_positions]:
                self.emit_signal(Signal(
                    strategy_name=self.name,
                    broker="polymarket",
                    symbol=opp.condition_id or opp.market_question[:40],
                    action="buy",
                    confidence=0.5,
                    price=0.0,
                    notes=f"cross_market edge={opp.edge_pct:.2f}%",
                    extra={"market_question": opp.market_question, "action": opp.action},
                ))
        except Exception as exc:
            import logging
            logging.getLogger("trauto.strategies.polymarket.cross_market").warning(
                "cross_market_tick_error error=%s", exc
            )

    def get_status(self) -> StrategyStatus:
        return self._base_status(last_opportunities=len(self._last_opps))
