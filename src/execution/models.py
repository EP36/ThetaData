"""Execution domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

import pandas as pd

ORDER_STATUS_SUBMITTED = "SUBMITTED"
ORDER_STATUS_FILLED = "FILLED"
ORDER_STATUS_CANCELED = "CANCELED"
ORDER_STATUS_REJECTED = "REJECTED"


@dataclass(slots=True)
class Order:
    """Paper order instruction."""

    symbol: str
    side: str
    quantity: float
    price: float
    timestamp: pd.Timestamp
    stop_loss_pct: float | None = None
    trailing_stop_pct: float | None = None
    order_id: str = field(default_factory=lambda: uuid4().hex)
    status: str = ORDER_STATUS_SUBMITTED
    rejection_reasons: tuple[str, ...] = ()


@dataclass(slots=True)
class Fill:
    """Executed paper-trade fill."""

    order_id: str
    symbol: str
    side: str
    quantity: float
    price: float
    timestamp: pd.Timestamp
    notional: float


@dataclass(slots=True)
class Position:
    """Tracked position state for paper execution."""

    symbol: str
    quantity: float = 0.0
    avg_price: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
