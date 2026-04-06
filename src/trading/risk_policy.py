"""Lightweight entry-risk policy checks for paper-trading readiness."""

from __future__ import annotations

from dataclasses import dataclass

from src.trading.types import GatedTradeIntent, RiskDecision, SizedTradeIntent, TradingRiskState

EPSILON = 1e-12


@dataclass(frozen=True, slots=True)
class RiskPolicyConfig:
    """Hard caps for new entry approval."""

    daily_drawdown_limit_pct: float = 0.02
    max_concurrent_positions: int = 3
    max_portfolio_exposure_pct: float = 0.30


def evaluate_risk_policy(
    intent: GatedTradeIntent | SizedTradeIntent,
    *,
    state: TradingRiskState,
    config: RiskPolicyConfig,
    proposed_notional: float,
) -> RiskDecision:
    """Reject new entries that breach portfolio or stop-policy constraints."""
    reasons: list[str] = []
    equity = state.account_equity
    day_start_equity = state.day_start_equity

    if equity is None or equity <= 0 or day_start_equity is None or day_start_equity <= 0:
        reasons.append("missing_account_equity")
    else:
        drawdown_pct = max((day_start_equity - equity) / day_start_equity, 0.0)
        if drawdown_pct >= config.daily_drawdown_limit_pct:
            reasons.append("daily_drawdown_limit_exceeded")

    if state.active_positions >= config.max_concurrent_positions:
        reasons.append("max_concurrent_positions_exceeded")

    stop_loss_pct = intent.stop_loss_pct
    stop_price = intent.stop_price
    if stop_price is None and (stop_loss_pct is None or stop_loss_pct <= 0 or stop_loss_pct >= 1):
        reasons.append("invalid_stop_configuration")

    if equity is not None and equity > 0:
        max_exposure_dollars = equity * config.max_portfolio_exposure_pct
        if (state.gross_exposure + proposed_notional) > max_exposure_dollars + EPSILON:
            reasons.append("max_portfolio_exposure_exceeded")

    if reasons:
        return RiskDecision.reject(*reasons)  # type: ignore[arg-type]
    return RiskDecision.allow()
