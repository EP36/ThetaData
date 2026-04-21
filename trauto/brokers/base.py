"""Abstract broker interface that every broker implementation must satisfy."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class AccountSnapshot:
    """Normalized account state across any broker."""
    broker: str
    cash: float
    portfolio_value: float
    buying_power: float
    unrealized_pnl: float
    realized_pnl_today: float
    currency: str = "USD"
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Position:
    """Normalized open position."""
    broker: str
    symbol: str
    side: str          # "long" | "short"
    quantity: float
    avg_price: float
    current_price: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    size_usd: float
    opened_at: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Order:
    """Normalized order request sent to a broker."""
    symbol: str
    side: str          # "buy" | "sell"
    quantity: float
    price: float
    order_type: str = "market"  # "market" | "limit"
    limit_price: float | None = None
    stop_loss_pct: float | None = None
    extended_hours: bool = False
    client_order_id: str = ""


@dataclass(frozen=True)
class OrderResult:
    """Normalized result from a broker order submission."""
    broker: str
    symbol: str
    side: str
    quantity: float
    price: float
    order_id: str
    status: str        # "filled" | "rejected" | "pending" | "canceled"
    filled_qty: float = 0.0
    filled_price: float = 0.0
    rejection_reason: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrderStatus:
    """Current state of a previously submitted order."""
    order_id: str
    status: str
    filled_qty: float = 0.0
    remaining_qty: float = 0.0


@dataclass(frozen=True)
class Bar:
    """One OHLCV bar."""
    symbol: str
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Quote:
    """Best bid/ask quote for a symbol."""
    symbol: str
    bid: float
    ask: float
    bid_size: float = 0.0
    ask_size: float = 0.0
    timestamp: str = ""


class BrokerInterface(ABC):
    """Abstract interface every broker adapter must implement.

    Adapters delegate to their underlying SDK/client and map the result
    to the normalized dataclasses above. They must not raise unexpected
    exceptions — wrap SDK errors in RuntimeError with a descriptive message.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Canonical broker name: 'alpaca' | 'polymarket'."""

    @abstractmethod
    async def get_account(self) -> AccountSnapshot:
        """Return current account/balance snapshot."""

    @abstractmethod
    async def get_positions(self) -> list[Position]:
        """Return all currently open positions."""

    @abstractmethod
    async def place_order(self, order: Order) -> OrderResult:
        """Submit an order. Returns result even on rejection."""

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Attempt to cancel an order. Returns True if canceled."""

    @abstractmethod
    async def get_order_status(self, order_id: str) -> OrderStatus:
        """Return current status of a previously submitted order."""

    @abstractmethod
    async def get_bars(
        self,
        symbol: str,
        timeframe: str,
        start: str,
        end: str,
        limit: int = 1000,
    ) -> list[Bar]:
        """Fetch historical OHLCV bars.

        Args:
            symbol: ticker or market ID
            timeframe: e.g. '1d', '1H', '5Min'
            start: ISO-8601 start datetime
            end: ISO-8601 end datetime
            limit: max bars to return
        """

    @abstractmethod
    async def get_quote(self, symbol: str) -> Quote:
        """Return the latest best bid/ask quote for a symbol."""

    @abstractmethod
    async def is_market_open(self) -> bool:
        """Return True if the relevant market is currently open for trading."""
