"""Polymarket orderbook spread arb scanner strategy."""

from __future__ import annotations

import logging
from typing import Any

from trauto.strategies.base import BaseStrategy, Signal, StrategySchedule, StrategyStatus

LOGGER = logging.getLogger("trauto.strategies.polymarket.arb_scanner")


class ArbScannerStrategy(BaseStrategy):
    """Orderbook spread arbitrage scanner for Polymarket.

    Wraps src.polymarket.opportunities.detect_orderbook_spread.
    On each tick, runs scan_and_execute() and emits signals for top opportunities.
    """

    name = "polymarket.arb_scanner"
    broker = "polymarket"

    def __init__(
        self,
        config: "PolymarketConfig | None" = None,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("schedule", StrategySchedule(type="interval", interval_sec=30.0))  # type: ignore[arg-type]
        super().__init__(**kwargs)
        self._config = config
        self._last_scan_opps: list[Any] = []

    def on_start(self) -> None:
        super().on_start()
        self._last_scan_opps = []

    async def on_tick(self, market_data: dict[str, Any]) -> None:
        """Run scanner on each scheduled tick and emit signals."""
        if self._config is None:
            return

        try:
            import asyncio
            from src.polymarket.runner import scan as _scan
            opps = await asyncio.to_thread(_scan, self._config)
            self._last_scan_opps = opps

            for opp in opps[:self.max_positions]:
                self.emit_signal(Signal(
                    strategy_name=self.name,
                    broker="polymarket",
                    symbol=opp.condition_id or opp.market_question[:40],
                    action="buy",
                    confidence=opp.confidence_score if opp.confidence_score > 0 else 0.5,
                    price=opp.entry_price_yes,
                    size_usd=self._config.max_trade_usdc,
                    notes=f"edge={opp.edge_pct:.2f}% strategy={opp.strategy}",
                    extra={
                        "opportunity": {
                            "strategy": opp.strategy,
                            "market_question": opp.market_question,
                            "edge_pct": opp.edge_pct,
                            "condition_id": opp.condition_id,
                            "yes_token_id": opp.yes_token_id,
                            "no_token_id": opp.no_token_id,
                            "entry_price_yes": opp.entry_price_yes,
                            "entry_price_no": opp.entry_price_no,
                            "direction": opp.direction,
                            "signal_notes": list(opp.signal_notes),
                        },
                    },
                ))
        except Exception as exc:
            LOGGER.warning("arb_scanner_tick_error error=%s", exc)

    def get_status(self) -> StrategyStatus:
        return self._base_status(
            last_opportunities=len(self._last_scan_opps),
            top_opportunity=(
                {
                    "market": self._last_scan_opps[0].market_question[:60],
                    "edge_pct": self._last_scan_opps[0].edge_pct,
                }
                if self._last_scan_opps else None
            ),
        )
