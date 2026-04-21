"""Alpaca broker adapter — delegates to existing src.execution and src.data."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import pandas as pd

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

LOGGER = logging.getLogger("trauto.brokers.alpaca")


class AlpacaBroker(BrokerInterface):
    """Wraps src.execution.executor.PaperTradingExecutor behind BrokerInterface.

    In paper mode (the only currently supported mode), order execution
    delegates to PaperTradingExecutor. Market data delegates to the Alpaca
    data provider via src.data.providers.alpaca.

    The async methods use asyncio.to_thread() to avoid blocking the engine
    tick loop — the underlying executor and data provider are synchronous.
    """

    def __init__(self, executor: "PaperTradingExecutor", data_provider: "Any | None" = None) -> None:
        from src.execution.executor import PaperTradingExecutor as _PTE  # noqa: F401
        self._executor = executor
        self._data_provider = data_provider

    @property
    def name(self) -> str:
        return "alpaca"

    async def get_account(self) -> AccountSnapshot:
        def _sync() -> AccountSnapshot:
            equity = self._executor.current_equity()
            cash = self._executor.cash
            realized = self._executor.realized_pnl()
            unrealized = self._executor.unrealized_pnl()
            return AccountSnapshot(
                broker="alpaca",
                cash=round(cash, 2),
                portfolio_value=round(equity, 2),
                buying_power=round(cash, 2),
                unrealized_pnl=round(unrealized, 2),
                realized_pnl_today=round(realized, 2),
            )
        return await asyncio.to_thread(_sync)

    async def get_positions(self) -> list[Position]:
        def _sync() -> list[Position]:
            positions = []
            for sym, pos in self._executor.positions.items():
                qty = float(pos.quantity)
                if qty <= 0:
                    continue
                avg = float(pos.avg_price)
                unrealized = float(pos.unrealized_pnl)
                size_usd = qty * avg
                pct = (unrealized / size_usd * 100.0) if size_usd > 0 else 0.0
                current = avg + (unrealized / qty if qty > 0 else 0.0)
                positions.append(Position(
                    broker="alpaca",
                    symbol=sym,
                    side="long",
                    quantity=qty,
                    avg_price=avg,
                    current_price=round(current, 4),
                    unrealized_pnl=round(unrealized, 2),
                    unrealized_pnl_pct=round(pct, 4),
                    size_usd=round(size_usd, 2),
                ))
            return positions
        return await asyncio.to_thread(_sync)

    async def place_order(self, order: Order) -> OrderResult:
        def _sync() -> OrderResult:
            from src.execution.models import Order as _SrcOrder
            src_order = _SrcOrder(
                order_id="",
                symbol=order.symbol,
                side=order.side.upper(),
                quantity=order.quantity,
                price=order.price,
                order_type=order.order_type.upper(),
                limit_price=order.limit_price,
                stop_loss_pct=order.stop_loss_pct,
                extended_hours=order.extended_hours,
                timestamp=pd.Timestamp.now(tz="UTC"),
            )
            result = self._executor.submit_order(src_order)
            filled = result.status == "filled"
            return OrderResult(
                broker="alpaca",
                symbol=result.symbol,
                side=result.side,
                quantity=result.quantity,
                price=result.price,
                order_id=result.order_id,
                status=result.status,
                filled_qty=result.quantity if filled else 0.0,
                filled_price=result.price if filled else 0.0,
                rejection_reason=(
                    ",".join(result.rejection_reasons) if result.rejection_reasons else ""
                ),
            )
        return await asyncio.to_thread(_sync)

    async def cancel_order(self, order_id: str) -> bool:
        def _sync() -> bool:
            result = self._executor.cancel_order(order_id)
            return result is not None
        return await asyncio.to_thread(_sync)

    async def get_order_status(self, order_id: str) -> OrderStatus:
        def _sync() -> OrderStatus:
            for order in self._executor.submitted_orders:
                if order.order_id == order_id:
                    return OrderStatus(order_id=order_id, status=order.status)
            return OrderStatus(order_id=order_id, status="not_found")
        return await asyncio.to_thread(_sync)

    async def get_bars(
        self,
        symbol: str,
        timeframe: str,
        start: str,
        end: str,
        limit: int = 1000,
    ) -> list[Bar]:
        if self._data_provider is None:
            return []

        def _sync() -> list[Bar]:
            try:
                df = self._data_provider.get_bars(
                    symbol=symbol,
                    timeframe=timeframe,
                    start=start,
                    end=end,
                    limit=limit,
                )
                bars = []
                for ts, row in df.iterrows():
                    bars.append(Bar(
                        symbol=symbol,
                        timestamp=str(ts),
                        open=float(row.get("open", 0)),
                        high=float(row.get("high", 0)),
                        low=float(row.get("low", 0)),
                        close=float(row.get("close", 0)),
                        volume=float(row.get("volume", 0)),
                    ))
                return bars
            except Exception as exc:
                LOGGER.warning("alpaca_get_bars_failed symbol=%s error=%s", symbol, exc)
                return []
        return await asyncio.to_thread(_sync)

    async def get_quote(self, symbol: str) -> Quote:
        def _sync() -> Quote:
            last_price = self._executor._last_prices.get(symbol, 0.0)
            return Quote(symbol=symbol, bid=last_price, ask=last_price)
        return await asyncio.to_thread(_sync)

    async def is_market_open(self) -> bool:
        from datetime import time as _time
        now = datetime.now(tz=timezone.utc)
        market_open = _time(14, 30)   # 09:30 ET = 14:30 UTC
        market_close = _time(21, 0)   # 16:00 ET = 21:00 UTC
        if now.weekday() >= 5:        # weekend
            return False
        return market_open <= now.time() <= market_close
