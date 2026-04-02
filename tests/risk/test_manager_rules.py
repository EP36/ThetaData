"""Rule-by-rule tests for central risk engine behavior."""

from __future__ import annotations

import pandas as pd

from src.risk.manager import RiskManager
from src.risk.models import OrderRiskRequest, PortfolioRiskState


def make_manager() -> RiskManager:
    return RiskManager(
        max_position_size=0.20,
        max_daily_loss=1_000.0,
        max_gross_exposure=1.00,
        max_open_positions=2,
        max_drawdown_pct=0.20,
        trading_start="09:30",
        trading_end="16:00",
    )


def make_state(**overrides: object) -> PortfolioRiskState:
    payload: dict[str, object] = {
        "equity": 100_000.0,
        "day_start_equity": 100_000.0,
        "peak_equity": 100_000.0,
        "gross_exposure": 10_000.0,
        "open_positions": {"AAPL": 10_000.0},
    }
    payload.update(overrides)
    return PortfolioRiskState(**payload)


def make_request(**overrides: object) -> OrderRiskRequest:
    payload: dict[str, object] = {
        "symbol": "MSFT",
        "side": "BUY",
        "quantity": 10.0,
        "price": 100.0,
        "timestamp": pd.Timestamp("2025-01-02 10:00:00"),
    }
    payload.update(overrides)
    return OrderRiskRequest(**payload)


def test_approves_valid_order() -> None:
    decision = make_manager().validate_order(make_request(), make_state())
    assert decision.approved is True
    assert decision.reasons == ()


def test_rejects_max_position_size_rule() -> None:
    manager = make_manager()
    state = make_state(open_positions={"MSFT": 19_900.0})
    request = make_request(quantity=2.0, price=100.0)
    decision = manager.validate_order(request, state)
    assert decision.approved is False
    assert "max_position_size_exceeded" in decision.reasons


def test_rejects_max_gross_exposure_rule() -> None:
    manager = make_manager()
    state = make_state(gross_exposure=99_900.0)
    request = make_request(quantity=2.0, price=100.0)
    decision = manager.validate_order(request, state)
    assert decision.approved is False
    assert "max_gross_exposure_exceeded" in decision.reasons


def test_rejects_max_open_positions_rule() -> None:
    manager = make_manager()
    state = make_state(open_positions={"AAPL": 5_000.0, "TSLA": 7_000.0})
    request = make_request(symbol="MSFT", quantity=1.0, price=100.0)
    decision = manager.validate_order(request, state)
    assert decision.approved is False
    assert "max_open_positions_exceeded" in decision.reasons


def test_rejects_daily_loss_and_enables_kill_switch() -> None:
    manager = make_manager()
    state = make_state(equity=98_900.0, day_start_equity=100_000.0)
    decision = manager.validate_order(make_request(), state)
    assert decision.approved is False
    assert "max_daily_loss_exceeded" in decision.reasons
    assert decision.kill_switch_enabled is True


def test_rejects_outside_trading_hours() -> None:
    manager = make_manager()
    request = make_request(timestamp=pd.Timestamp("2025-01-02 20:00:00"))
    decision = manager.validate_order(request, make_state())
    assert decision.approved is False
    assert "outside_trading_hours" in decision.reasons


def test_rejects_invalid_stop_and_trailing_stop() -> None:
    manager = make_manager()
    request = make_request(stop_loss_pct=1.2, trailing_stop_pct=-0.2)
    decision = manager.validate_order(request, make_state())
    assert decision.approved is False
    assert "invalid_stop_loss_pct" in decision.reasons
    assert "invalid_trailing_stop_pct" in decision.reasons


def test_drawdown_triggers_kill_switch() -> None:
    manager = make_manager()
    state = make_state(equity=75_000.0, peak_equity=100_000.0)
    decision = manager.validate_order(make_request(), state)
    assert decision.approved is False
    assert "max_drawdown_exceeded" in decision.reasons
    assert decision.kill_switch_enabled is True


def test_combined_rule_evaluation_returns_multiple_reasons() -> None:
    manager = make_manager()
    state = make_state(gross_exposure=99_900.0, open_positions={"AAPL": 5_000.0, "TSLA": 7_000.0})
    request = make_request(timestamp=pd.Timestamp("2025-01-02 20:00:00"), quantity=10.0, price=100.0)
    decision = manager.validate_order(request, state)
    assert decision.approved is False
    assert "outside_trading_hours" in decision.reasons
    assert "max_gross_exposure_exceeded" in decision.reasons
