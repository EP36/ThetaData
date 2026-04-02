"""Core datatypes for backtesting."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(slots=True)
class Trade:
    """Executed trade record from the simulator."""

    timestamp: pd.Timestamp
    side: str
    quantity: float
    fill_price: float
    fee: float
    reason: str
    cash_after: float
    shares_after: float
    equity_after: float
