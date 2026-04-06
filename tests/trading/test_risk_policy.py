"""Tests for additive entry risk-policy checks."""

from __future__ import annotations

import pandas as pd

from src.trading.risk_policy import RiskPolicyConfig, evaluate_risk_policy
from src.trading.types import GatedTradeIntent, TradingRiskState


def _intent() -> GatedTradeIntent:
    return GatedTradeIntent(
        symbol="SPY",
        strategy_id="breakout_momentum",
        side="BUY",
        entry_price=100.0,
        timestamp=pd.Timestamp("2026-01-05 10:00"),
        signal=1.0,
        regime="bullish",
        stop_price=98.0,
        stop_loss_pct=0.02,
        trailing_stop_pct=0.02,
        regime_size_multiplier=1.0,
    )


def test_risk_policy_blocks_max_concurrent_positions() -> None:
    decision = evaluate_risk_policy(
        _intent(),
        state=TradingRiskState(
            account_equity=100_000.0,
            day_start_equity=100_000.0,
            gross_exposure=0.0,
            active_positions=3,
        ),
        config=RiskPolicyConfig(max_concurrent_positions=3),
        proposed_notional=10_000.0,
    )
    assert decision.reasons == ("max_concurrent_positions_exceeded",)


def test_risk_policy_blocks_daily_drawdown_limit() -> None:
    decision = evaluate_risk_policy(
        _intent(),
        state=TradingRiskState(
            account_equity=97_000.0,
            day_start_equity=100_000.0,
            gross_exposure=0.0,
            active_positions=0,
        ),
        config=RiskPolicyConfig(daily_drawdown_limit_pct=0.02),
        proposed_notional=10_000.0,
    )
    assert decision.reasons == ("daily_drawdown_limit_exceeded",)


def test_risk_policy_blocks_missing_equity() -> None:
    decision = evaluate_risk_policy(
        _intent(),
        state=TradingRiskState(
            account_equity=None,
            day_start_equity=100_000.0,
            gross_exposure=0.0,
            active_positions=0,
        ),
        config=RiskPolicyConfig(),
        proposed_notional=10_000.0,
    )
    assert decision.reasons == ("missing_account_equity",)


def test_risk_policy_allows_valid_trade() -> None:
    decision = evaluate_risk_policy(
        _intent(),
        state=TradingRiskState(
            account_equity=100_000.0,
            day_start_equity=100_000.0,
            gross_exposure=5_000.0,
            active_positions=1,
        ),
        config=RiskPolicyConfig(),
        proposed_notional=10_000.0,
    )
    assert decision.approved is True
