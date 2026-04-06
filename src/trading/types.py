"""Typed trade-intent models for additive paper-trading controls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

StrategyId = Literal[
    "moving_average_crossover",
    "breakout_momentum",
    "rsi_mean_reversion",
    "vwap_mean_reversion",
]
MarketRegime = Literal["bullish", "sideways", "bearish", "unknown"]
RiskRejectionReason = Literal[
    "regime_unknown",
    "strategy_reserved_for_regime_filter",
    "strategy_blocked_by_regime",
    "rsi_blocked_in_bullish_regime",
    "breakout_blocked_in_sideways_regime",
    "long_entries_blocked_in_bearish_regime",
    "mean_reversion_blocked_in_bearish_regime",
    "missing_account_equity",
    "daily_drawdown_limit_exceeded",
    "max_concurrent_positions_exceeded",
    "max_portfolio_exposure_exceeded",
    "invalid_stop_configuration",
    "risk_per_share_non_positive",
    "position_size_below_minimum",
]

SUPPORTED_STRATEGY_IDS: tuple[StrategyId, ...] = (
    "moving_average_crossover",
    "breakout_momentum",
    "rsi_mean_reversion",
    "vwap_mean_reversion",
)


@dataclass(frozen=True, slots=True)
class TradeIntent:
    """Actionable long-entry intent emitted after signal generation."""

    symbol: str
    strategy_id: StrategyId
    side: Literal["BUY"]
    entry_price: float
    timestamp: pd.Timestamp
    signal: float
    regime: MarketRegime
    stop_price: float | None = None
    stop_loss_pct: float | None = None
    trailing_stop_pct: float | None = None


@dataclass(frozen=True, slots=True)
class GatedTradeIntent(TradeIntent):
    """Trade intent approved by strategy-regime gating."""

    regime_size_multiplier: float = 1.0


@dataclass(frozen=True, slots=True)
class SizedTradeIntent(GatedTradeIntent):
    """Trade intent with a concrete quantity and risk footprint."""

    quantity: int = 0
    dollars_at_risk: float = 0.0
    risk_per_share: float = 0.0
    projected_notional: float = 0.0


@dataclass(frozen=True, slots=True)
class TradingRiskState:
    """Minimal account state used by the additive trading-policy layer."""

    account_equity: float | None
    day_start_equity: float | None
    gross_exposure: float
    active_positions: int


@dataclass(frozen=True, slots=True)
class RiskDecision:
    """Approval or rejection result for gating/sizing/risk-policy checks."""

    approved: bool
    reasons: tuple[RiskRejectionReason, ...] = ()

    @classmethod
    def allow(cls) -> "RiskDecision":
        """Return an approved decision."""
        return cls(approved=True, reasons=())

    @classmethod
    def reject(cls, *reasons: RiskRejectionReason) -> "RiskDecision":
        """Return a rejected decision with de-duplicated reasons."""
        ordered = tuple(dict.fromkeys(reasons))
        return cls(approved=False, reasons=ordered)


def normalize_strategy_id(value: str) -> StrategyId | None:
    """Return a typed strategy identifier when recognized."""
    candidate = value.strip()
    if candidate in SUPPORTED_STRATEGY_IDS:
        return candidate  # type: ignore[return-value]
    return None
