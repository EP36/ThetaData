"""Conservative fixed-risk position sizing for approved trade intents."""

from __future__ import annotations

from dataclasses import dataclass
import math

from src.trading.types import GatedTradeIntent, RiskDecision, SizedTradeIntent, TradingRiskState

EPSILON = 1e-12


@dataclass(frozen=True, slots=True)
class PositionSizingConfig:
    """Inputs for fixed-risk sizing and exposure enforcement."""

    risk_per_trade_pct: float = 0.005
    max_portfolio_exposure_pct: float = 0.30
    max_concurrent_positions: int = 3


def calculate_position_size(
    intent: GatedTradeIntent,
    *,
    state: TradingRiskState,
    config: PositionSizingConfig,
) -> tuple[SizedTradeIntent | None, RiskDecision]:
    """Convert an approved trade intent into a conservative share quantity."""
    equity = state.account_equity
    if equity is None or equity <= 0:
        return None, RiskDecision.reject("missing_account_equity")
    if state.active_positions >= config.max_concurrent_positions:
        return None, RiskDecision.reject("max_concurrent_positions_exceeded")

    stop_price = _resolve_stop_price(intent)
    if stop_price is None or stop_price <= 0:
        return None, RiskDecision.reject("invalid_stop_configuration")

    risk_per_share = abs(float(intent.entry_price) - stop_price)
    if risk_per_share <= EPSILON:
        return None, RiskDecision.reject("risk_per_share_non_positive")
    if stop_price >= intent.entry_price:
        return None, RiskDecision.reject("invalid_stop_configuration")

    dollars_at_risk = float(equity * config.risk_per_trade_pct * intent.regime_size_multiplier)
    raw_quantity = math.floor(dollars_at_risk / risk_per_share)
    if raw_quantity < 1:
        return None, RiskDecision.reject("position_size_below_minimum")

    max_exposure_dollars = float(equity * config.max_portfolio_exposure_pct)
    exposure_headroom = max(max_exposure_dollars - state.gross_exposure, 0.0)
    max_quantity_by_exposure = math.floor(exposure_headroom / max(float(intent.entry_price), EPSILON))
    if max_quantity_by_exposure < 1:
        return None, RiskDecision.reject("max_portfolio_exposure_exceeded")

    quantity = min(raw_quantity, max_quantity_by_exposure)
    if quantity < 1:
        return None, RiskDecision.reject("max_portfolio_exposure_exceeded")

    return (
        SizedTradeIntent(
            symbol=intent.symbol,
            strategy_id=intent.strategy_id,
            side=intent.side,
            entry_price=float(intent.entry_price),
            timestamp=intent.timestamp,
            signal=float(intent.signal),
            regime=intent.regime,
            stop_price=stop_price,
            stop_loss_pct=intent.stop_loss_pct,
            trailing_stop_pct=intent.trailing_stop_pct,
            regime_size_multiplier=float(intent.regime_size_multiplier),
            quantity=int(quantity),
            dollars_at_risk=float(dollars_at_risk),
            risk_per_share=float(risk_per_share),
            projected_notional=float(quantity * intent.entry_price),
        ),
        RiskDecision.allow(),
    )


def _resolve_stop_price(intent: GatedTradeIntent) -> float | None:
    """Resolve a concrete stop price from either an absolute or percent stop."""
    if intent.stop_price is not None:
        return float(intent.stop_price)
    if intent.stop_loss_pct is None:
        return None
    stop_loss_pct = float(intent.stop_loss_pct)
    if stop_loss_pct <= 0 or stop_loss_pct >= 1:
        return None
    return float(intent.entry_price * (1.0 - stop_loss_pct))
