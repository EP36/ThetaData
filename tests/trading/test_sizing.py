"""Tests for additive fixed-risk position sizing."""

from __future__ import annotations

import pandas as pd

from src.trading.sizing import PositionSizingConfig, calculate_position_size
from src.trading.types import GatedTradeIntent, TradingRiskState


def _intent(*, entry_price: float = 100.0, stop_price: float = 98.0) -> GatedTradeIntent:
    return GatedTradeIntent(
        symbol="SPY",
        strategy_id="breakout_momentum",
        side="BUY",
        entry_price=entry_price,
        timestamp=pd.Timestamp("2026-01-05 10:00"),
        signal=1.0,
        regime="bullish",
        stop_price=stop_price,
        stop_loss_pct=None,
        trailing_stop_pct=0.02,
        regime_size_multiplier=1.0,
    )


def _state(
    *,
    equity: float | None = 100_000.0,
    gross_exposure: float = 0.0,
    active_positions: int = 0,
) -> TradingRiskState:
    return TradingRiskState(
        account_equity=equity,
        day_start_equity=100_000.0,
        gross_exposure=gross_exposure,
        active_positions=active_positions,
    )


def test_position_sizing_calculates_normal_quantity() -> None:
    sized, decision = calculate_position_size(
        _intent(),
        state=_state(),
        config=PositionSizingConfig(risk_per_trade_pct=0.005),
    )
    assert decision.approved is True
    assert sized is not None
    assert sized.quantity == 250


def test_position_sizing_blocks_zero_risk_per_share() -> None:
    sized, decision = calculate_position_size(
        _intent(stop_price=100.0),
        state=_state(),
        config=PositionSizingConfig(),
    )
    assert sized is None
    assert decision.reasons == ("risk_per_share_non_positive",)


def test_position_sizing_rounds_down_safely() -> None:
    sized, decision = calculate_position_size(
        _intent(stop_price=97.0),
        state=_state(),
        config=PositionSizingConfig(risk_per_trade_pct=0.005),
    )
    assert decision.approved is True
    assert sized is not None
    assert sized.quantity == 166


def test_position_sizing_enforces_exposure_cap() -> None:
    sized, decision = calculate_position_size(
        _intent(),
        state=_state(gross_exposure=10_000.0),
        config=PositionSizingConfig(
            risk_per_trade_pct=0.005,
            max_portfolio_exposure_pct=0.20,
        ),
    )
    assert decision.approved is True
    assert sized is not None
    assert sized.quantity == 100


def test_position_sizing_blocks_too_small_position() -> None:
    sized, decision = calculate_position_size(
        _intent(),
        state=_state(equity=1_000.0),
        config=PositionSizingConfig(risk_per_trade_pct=0.001),
    )
    assert sized is None
    assert decision.reasons == ("position_size_below_minimum",)
