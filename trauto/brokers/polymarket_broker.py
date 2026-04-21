"""Polymarket broker adapter — delegates to src.polymarket.client."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from trauto.brokers.base import (
    AccountSnapshot,
    Bar,
    BrokerInterface,
    Order,
    OrderResult,
    OrderStatus,
    Position,
    Quote,
)

LOGGER = logging.getLogger("trauto.brokers.polymarket")

# Polymarket concepts → BrokerInterface mapping:
#   market / condition_id → symbol
#   YES token → long side (buy YES = long)
#   NO  token → short side (buy NO  = short equivalent)
#   best_ask on YES token → Quote.ask
#   best_bid on YES token → Quote.bid
#   PositionRecord.size_usdc → size_usd
#   PositionRecord.status    → Position.extra["status"]


class PolymarketBroker(BrokerInterface):
    """Wraps ClobClient behind BrokerInterface.

    Execution is delegated to src.polymarket.executor.execute() which
    respects dry_run and risk guards. Market data comes from ClobClient.
    """

    def __init__(
        self,
        client: "ClobClient",
        config: "PolymarketConfig",
        ledger: "PositionsLedger",
        risk_guard: "RiskGuard | None" = None,
    ) -> None:
        self._client = client
        self._config = config
        self._ledger = ledger
        self._risk_guard = risk_guard

    @property
    def name(self) -> str:
        return "polymarket"

    async def get_account(self) -> AccountSnapshot:
        def _sync() -> AccountSnapshot:
            daily_pnl = self._ledger.daily_pnl()
            deployed = sum(
                p.size_usdc for p in self._ledger.load()
                if p.status in {"open", "closing", "unhedged"}
            )
            return AccountSnapshot(
                broker="polymarket",
                cash=0.0,           # no cash balance API available
                portfolio_value=round(deployed, 2),
                buying_power=max(0.0, self._config.max_trade_usdc),
                unrealized_pnl=0.0,
                realized_pnl_today=round(daily_pnl, 4),
                currency="USDC",
            )
        return await asyncio.to_thread(_sync)

    async def get_positions(self) -> list[Position]:
        def _sync() -> list[Position]:
            from src.polymarket.positions import ACTIVE_STATUSES
            positions = []
            for rec in self._ledger.load():
                if rec.status not in ACTIVE_STATUSES:
                    continue
                current = rec.exit_price if rec.exit_price is not None else rec.entry_price
                unrealized = rec.unrealized_pnl or 0.0
                pct = rec.unrealized_pnl_pct or 0.0
                positions.append(Position(
                    broker="polymarket",
                    symbol=rec.market_condition_id,
                    side=rec.side.lower(),
                    quantity=rec.contracts_held,
                    avg_price=rec.entry_price,
                    current_price=current,
                    unrealized_pnl=unrealized,
                    unrealized_pnl_pct=pct,
                    size_usd=rec.size_usdc,
                    opened_at=rec.opened_at,
                    extra={
                        "id": rec.id,
                        "market_question": rec.market_question,
                        "strategy": rec.strategy,
                        "status": rec.status,
                        "yes_token_id": rec.yes_token_id,
                        "no_token_id": rec.no_token_id,
                    },
                ))
            return positions
        return await asyncio.to_thread(_sync)

    async def place_order(self, order: Order) -> OrderResult:
        """Submit a Polymarket order via the existing executor.

        Polymarket orders are keyed by condition_id (order.symbol).
        The opportunity must be reconstructed or the executor called directly.
        This method is intentionally minimal — the arb scanner strategy
        calls src.polymarket.executor.execute() directly with a full Opportunity.
        """
        LOGGER.info(
            "polymarket_place_order symbol=%s side=%s qty=%.4f price=%.4f dry_run=%s",
            order.symbol,
            order.side,
            order.quantity,
            order.price,
            self._config.dry_run,
        )
        if self._config.dry_run:
            return OrderResult(
                broker="polymarket",
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                price=order.price,
                order_id=f"dry_{order.symbol}",
                status="dry_run",
            )
        # Live execution is not wired here — the strategy calls execute() directly
        return OrderResult(
            broker="polymarket",
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=order.price,
            order_id="",
            status="rejected",
            rejection_reason="use_strategy_execute_directly",
        )

    async def cancel_order(self, order_id: str) -> bool:
        LOGGER.info("polymarket_cancel_order order_id=%s (no-op — Poly CLOB is immediate)", order_id)
        return False

    async def get_order_status(self, order_id: str) -> OrderStatus:
        return OrderStatus(order_id=order_id, status="unknown")

    async def get_bars(
        self,
        symbol: str,
        timeframe: str,
        start: str,
        end: str,
        limit: int = 1000,
    ) -> list[Bar]:
        # Polymarket has no historical OHLCV API — return empty
        LOGGER.debug("polymarket_get_bars unavailable symbol=%s", symbol)
        return []

    async def get_quote(self, symbol: str) -> Quote:
        """Fetch the current YES/NO best ask from the orderbook.

        Args:
            symbol: condition_id of the market.
        """
        def _sync() -> Quote:
            try:
                # Fetch market detail to get YES token_id
                detail = self._client.fetch_market_detail(symbol)
                tokens = detail.get("tokens", [])
                yes_token = next(
                    (t for t in tokens if t.get("outcome", "").upper() == "YES"), None
                )
                if yes_token is None:
                    return Quote(symbol=symbol, bid=0.0, ask=0.0)
                ob = self._client.fetch_orderbook(yes_token["token_id"])
                bid = float(ob.get("bids", [{}])[0].get("price", 0)) if ob.get("bids") else 0.0
                ask = float(ob.get("asks", [{}])[0].get("price", 0)) if ob.get("asks") else 0.0
                return Quote(symbol=symbol, bid=bid, ask=ask)
            except Exception as exc:
                LOGGER.warning("polymarket_get_quote_failed symbol=%s error=%s", symbol, exc)
                return Quote(symbol=symbol, bid=0.0, ask=0.0)
        return await asyncio.to_thread(_sync)

    async def is_market_open(self) -> bool:
        # Polymarket trades 24/7
        return True
