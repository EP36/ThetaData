"""Tests for broker interface implementations."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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


# ---------------------------------------------------------------------------
# BrokerInterface contract tests via a minimal concrete implementation
# ---------------------------------------------------------------------------

class _StubBroker(BrokerInterface):
    """Minimal concrete broker for interface contract testing."""

    @property
    def name(self) -> str:
        return "stub"

    async def get_account(self) -> AccountSnapshot:
        return AccountSnapshot(
            broker="stub", cash=1000.0, portfolio_value=1000.0,
            buying_power=1000.0, unrealized_pnl=0.0, realized_pnl_today=0.0,
        )

    async def get_positions(self) -> list[Position]:
        return []

    async def place_order(self, order: Order) -> OrderResult:
        return OrderResult(
            broker="stub", symbol=order.symbol, side=order.side,
            quantity=order.quantity, price=order.price,
            order_id="stub_001", status="filled",
            filled_qty=order.quantity, filled_price=order.price,
        )

    async def cancel_order(self, order_id: str) -> bool:
        return True

    async def get_order_status(self, order_id: str) -> OrderStatus:
        return OrderStatus(order_id=order_id, status="filled")

    async def get_bars(self, symbol, timeframe, start, end, limit=1000) -> list[Bar]:
        return [Bar(symbol=symbol, timestamp="2024-01-01", open=100.0,
                    high=105.0, low=99.0, close=103.0, volume=1_000_000.0)]

    async def get_quote(self, symbol: str) -> Quote:
        return Quote(symbol=symbol, bid=99.0, ask=101.0)

    async def is_market_open(self) -> bool:
        return True


class TestBrokerInterface:
    def test_name_property(self):
        broker = _StubBroker()
        assert broker.name == "stub"

    def test_get_account_shape(self):
        broker = _StubBroker()
        result = asyncio.get_event_loop().run_until_complete(broker.get_account())
        assert isinstance(result, AccountSnapshot)
        assert result.broker == "stub"
        assert result.cash >= 0

    def test_get_positions_shape(self):
        broker = _StubBroker()
        result = asyncio.get_event_loop().run_until_complete(broker.get_positions())
        assert isinstance(result, list)

    def test_place_order_shape(self):
        broker = _StubBroker()
        order = Order(symbol="SPY", side="buy", quantity=10.0, price=500.0)
        result = asyncio.get_event_loop().run_until_complete(broker.place_order(order))
        assert isinstance(result, OrderResult)
        assert result.symbol == "SPY"
        assert result.status in ("filled", "rejected", "pending", "dry_run", "canceled")

    def test_cancel_order_returns_bool(self):
        broker = _StubBroker()
        result = asyncio.get_event_loop().run_until_complete(broker.cancel_order("order_001"))
        assert isinstance(result, bool)

    def test_get_order_status_shape(self):
        broker = _StubBroker()
        result = asyncio.get_event_loop().run_until_complete(broker.get_order_status("order_001"))
        assert isinstance(result, OrderStatus)
        assert result.order_id == "order_001"

    def test_get_bars_shape(self):
        broker = _StubBroker()
        result = asyncio.get_event_loop().run_until_complete(
            broker.get_bars("SPY", "1d", "2024-01-01", "2024-12-31")
        )
        assert isinstance(result, list)
        if result:
            bar = result[0]
            assert isinstance(bar, Bar)
            assert bar.symbol == "SPY"
            assert bar.close > 0

    def test_get_quote_shape(self):
        broker = _StubBroker()
        result = asyncio.get_event_loop().run_until_complete(broker.get_quote("SPY"))
        assert isinstance(result, Quote)
        assert result.symbol == "SPY"
        assert result.ask >= result.bid >= 0

    def test_is_market_open_returns_bool(self):
        broker = _StubBroker()
        result = asyncio.get_event_loop().run_until_complete(broker.is_market_open())
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# PolymarketBroker interface
# ---------------------------------------------------------------------------

class TestPolymarketBrokerInterface:
    def test_name(self):
        from trauto.brokers.polymarket_broker import PolymarketBroker
        mock_client = MagicMock()
        mock_config = MagicMock()
        mock_config.dry_run = True
        mock_config.max_trade_usdc = 500.0
        mock_ledger = MagicMock()
        mock_ledger.load.return_value = []
        mock_ledger.daily_pnl.return_value = 0.0
        broker = PolymarketBroker(client=mock_client, config=mock_config, ledger=mock_ledger)
        assert broker.name == "polymarket"

    def test_is_market_open_always_true(self):
        from trauto.brokers.polymarket_broker import PolymarketBroker
        mock_client = MagicMock()
        mock_config = MagicMock()
        mock_config.dry_run = True
        mock_config.max_trade_usdc = 500.0
        mock_ledger = MagicMock()
        mock_ledger.load.return_value = []
        mock_ledger.daily_pnl.return_value = 0.0
        broker = PolymarketBroker(client=mock_client, config=mock_config, ledger=mock_ledger)
        result = asyncio.get_event_loop().run_until_complete(broker.is_market_open())
        assert result is True

    def test_place_order_dry_run(self):
        from trauto.brokers.polymarket_broker import PolymarketBroker
        mock_client = MagicMock()
        mock_config = MagicMock()
        mock_config.dry_run = True
        mock_config.max_trade_usdc = 500.0
        mock_ledger = MagicMock()
        mock_ledger.load.return_value = []
        mock_ledger.daily_pnl.return_value = 0.0
        broker = PolymarketBroker(client=mock_client, config=mock_config, ledger=mock_ledger)
        order = Order(symbol="cond_abc", side="buy", quantity=100.0, price=0.55)
        result = asyncio.get_event_loop().run_until_complete(broker.place_order(order))
        assert result.status == "dry_run"

    def test_get_bars_returns_empty(self):
        from trauto.brokers.polymarket_broker import PolymarketBroker
        mock_client = MagicMock()
        mock_config = MagicMock()
        mock_config.dry_run = True
        mock_config.max_trade_usdc = 500.0
        mock_ledger = MagicMock()
        mock_ledger.load.return_value = []
        mock_ledger.daily_pnl.return_value = 0.0
        broker = PolymarketBroker(client=mock_client, config=mock_config, ledger=mock_ledger)
        result = asyncio.get_event_loop().run_until_complete(
            broker.get_bars("cond_abc", "1d", "2024-01-01", "2024-12-31")
        )
        assert result == []
