"""Structured models for risk engine inputs and decisions."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass(frozen=True, slots=True)
class OrderRiskRequest:
    """Order request for risk evaluation."""

    symbol: str
    side: str
    quantity: float
    price: float
    timestamp: pd.Timestamp
    stop_loss_pct: float | None = None
    trailing_stop_pct: float | None = None

    @property
    def notional(self) -> float:
        """Return requested order notional."""
        return float(self.quantity * self.price)


@dataclass(frozen=True, slots=True)
class PortfolioRiskState:
    """Portfolio state used during risk checks."""

    equity: float
    day_start_equity: float
    peak_equity: float
    gross_exposure: float
    open_positions: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RiskDecision:
    """Structured approval/rejection result."""

    approved: bool
    reasons: tuple[str, ...] = ()
    kill_switch_enabled: bool = False
