"""Tests for paper execution flow, risk enforcement, and PnL tracking."""

from __future__ import annotations

import pandas as pd

from src.execution.executor import PaperTradingExecutor
from src.execution.models import Order
from src.risk.manager import RiskManager


def build_risk_manager(
    max_position_size: float = 1.0,
    allow_after_hours: bool = False,
) -> RiskManager:
    return RiskManager(
        max_position_size=max_position_size,
        max_daily_loss=2_000.0,
        max_gross_exposure=2.0,
        max_open_positions=10,
        allow_after_hours=allow_after_hours,
    )


def test_risk_rejection_path() -> None:
    executor = PaperTradingExecutor(
        starting_cash=10_000.0,
        risk_manager=build_risk_manager(max_position_size=0.01),
        paper_trading_enabled=True,
    )
    order = Order(
        symbol="SPY",
        side="BUY",
        quantity=20.0,
        price=100.0,
        timestamp=pd.Timestamp("2025-01-01 10:00:00"),
    )
    result = executor.submit_order(order)

    assert result.status == "REJECTED"
    assert "max_position_size_exceeded" in result.rejection_reasons
    assert len(executor.filled_orders) == 0


def test_fill_simulation_and_order_tracking() -> None:
    executor = PaperTradingExecutor(
        starting_cash=10_000.0,
        risk_manager=build_risk_manager(allow_after_hours=True),
        paper_trading_enabled=True,
    )
    buy = executor.submit_order(
        Order(
            symbol="SPY",
            side="BUY",
            quantity=10.0,
            price=100.0,
            timestamp=pd.Timestamp("2025-01-01 10:00:00"),
        )
    )
    sell = executor.submit_order(
        Order(
            symbol="SPY",
            side="SELL",
            quantity=5.0,
            price=101.0,
            timestamp=pd.Timestamp("2025-01-01 11:00:00"),
        )
    )

    assert buy.status == "FILLED"
    assert sell.status == "FILLED"
    assert len(executor.submitted_orders) == 2
    assert len(executor.filled_orders) == 2
    assert executor.positions["SPY"].quantity == 5.0


def test_pnl_tracking_realized_and_unrealized() -> None:
    executor = PaperTradingExecutor(
        starting_cash=10_000.0,
        risk_manager=build_risk_manager(),
        paper_trading_enabled=True,
    )
    executor.submit_order(
        Order(
            symbol="QQQ",
            side="BUY",
            quantity=10.0,
            price=100.0,
            timestamp=pd.Timestamp("2025-01-01 10:00:00"),
        )
    )

    unrealized = executor.mark_to_market({"QQQ": 110.0})
    assert unrealized == 100.0

    executor.submit_order(
        Order(
            symbol="QQQ",
            side="SELL",
            quantity=10.0,
            price=110.0,
            timestamp=pd.Timestamp("2025-01-01 11:00:00"),
        )
    )
    assert executor.realized_pnl() == 100.0
    assert executor.unrealized_pnl() == 0.0


def test_kill_switch_behavior() -> None:
    executor = PaperTradingExecutor(
        starting_cash=1_000.0,
        risk_manager=build_risk_manager(),
        paper_trading_enabled=True,
        daily_loss_cap=50.0,
    )
    executor.submit_order(
        Order(
            symbol="IWM",
            side="BUY",
            quantity=10.0,
            price=100.0,
            timestamp=pd.Timestamp("2025-01-01 10:00:00"),
        )
    )
    executor.submit_order(
        Order(
            symbol="IWM",
            side="SELL",
            quantity=10.0,
            price=90.0,
            timestamp=pd.Timestamp("2025-01-01 11:00:00"),
        )
    )

    assert executor.kill_switch_enabled is True

    rejected = executor.submit_order(
        Order(
            symbol="IWM",
            side="BUY",
            quantity=1.0,
            price=90.0,
            timestamp=pd.Timestamp("2025-01-01 12:00:00"),
        )
    )
    assert rejected.status == "REJECTED"
    assert "kill_switch_enabled" in rejected.rejection_reasons


def test_restore_and_snapshot_state_round_trip() -> None:
    executor = PaperTradingExecutor(
        starting_cash=10_000.0,
        risk_manager=build_risk_manager(),
        paper_trading_enabled=True,
    )
    executor.submit_order(
        Order(
            symbol="SPY",
            side="BUY",
            quantity=2.0,
            price=100.0,
            timestamp=pd.Timestamp("2025-01-01 10:00:00"),
        )
    )
    cash, day_start, peak, positions = executor.snapshot_state()

    restored = PaperTradingExecutor(
        starting_cash=10_000.0,
        risk_manager=build_risk_manager(),
        paper_trading_enabled=True,
    )
    restored.restore_state(
        cash=cash,
        day_start_equity=day_start,
        peak_equity=peak,
        positions=positions,
    )
    restored_cash, _, _, restored_positions = restored.snapshot_state()
    assert restored_cash == cash
    assert "SPY" in restored_positions
    assert restored_positions["SPY"].quantity == positions["SPY"].quantity


def test_extended_hours_market_order_is_rejected() -> None:
    executor = PaperTradingExecutor(
        starting_cash=10_000.0,
        risk_manager=build_risk_manager(),
        paper_trading_enabled=True,
    )

    result = executor.submit_order(
        Order(
            symbol="SPY",
            side="BUY",
            quantity=1.0,
            price=100.0,
            timestamp=pd.Timestamp("2025-01-01 18:00:00"),
            extended_hours=True,
        )
    )

    assert result.status == "REJECTED"
    assert "extended_hours_requires_limit_order" in result.rejection_reasons


def test_extended_hours_limit_order_is_allowed() -> None:
    executor = PaperTradingExecutor(
        starting_cash=10_000.0,
        risk_manager=build_risk_manager(allow_after_hours=True),
        paper_trading_enabled=True,
    )

    result = executor.submit_order(
        Order(
            symbol="SPY",
            side="BUY",
            quantity=1.0,
            price=100.0,
            timestamp=pd.Timestamp("2025-01-01 18:00:00"),
            order_type="LIMIT",
            limit_price=100.0,
            extended_hours=True,
        )
    )

    assert result.status == "FILLED"
