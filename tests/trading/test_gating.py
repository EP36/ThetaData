"""Tests for additive strategy-regime gating rules."""

from __future__ import annotations

import pandas as pd

from src.trading.gating import StrategyGateConfig, gate_trade_intent
from src.trading.types import TradeIntent


def _intent(strategy_id: str, regime: str) -> TradeIntent:
    return TradeIntent(
        symbol="SPY",
        strategy_id=strategy_id,  # type: ignore[arg-type]
        side="BUY",
        entry_price=100.0,
        timestamp=pd.Timestamp("2026-01-05 10:00"),
        signal=1.0,
        regime=regime,  # type: ignore[arg-type]
        stop_price=98.0,
        stop_loss_pct=0.02,
    )


def test_breakout_is_allowed_in_bullish_regime() -> None:
    gated, decision = gate_trade_intent(
        _intent("breakout_momentum", "bullish"),
        config=StrategyGateConfig(),
    )
    assert decision.approved is True
    assert gated is not None


def test_breakout_is_blocked_in_sideways_regime() -> None:
    gated, decision = gate_trade_intent(
        _intent("breakout_momentum", "sideways"),
        config=StrategyGateConfig(),
    )
    assert gated is None
    assert decision.reasons == ("breakout_blocked_in_sideways_regime",)


def test_rsi_is_allowed_in_sideways_regime() -> None:
    gated, decision = gate_trade_intent(
        _intent("rsi_mean_reversion", "sideways"),
        config=StrategyGateConfig(),
    )
    assert decision.approved is True
    assert gated is not None


def test_long_entries_are_blocked_in_bearish_regime_by_default() -> None:
    gated, decision = gate_trade_intent(
        _intent("vwap_mean_reversion", "bearish"),
        config=StrategyGateConfig(),
    )
    assert gated is None
    assert decision.reasons == ("long_entries_blocked_in_bearish_regime",)
