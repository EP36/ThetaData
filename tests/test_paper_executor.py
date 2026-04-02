"""Tests for paper trading executor baseline guards."""

from __future__ import annotations

import pandas as pd

from src.execution.models import Order
from src.execution.paper_executor import PaperTradingExecutor
from src.risk.manager import RiskManager


def make_risk_manager() -> RiskManager:
    return RiskManager(
        max_position_size=1.0,
        max_daily_loss=2_000.0,
        max_gross_exposure=2.0,
        max_open_positions=10,
    )


def test_paper_executor_disabled_by_default() -> None:
    executor = PaperTradingExecutor(starting_cash=10_000.0, risk_manager=make_risk_manager())
    order = Order(
        symbol="SPY",
        side="BUY",
        quantity=1.0,
        price=100.0,
        timestamp=pd.Timestamp("2025-01-01 10:00:00"),
    )
    result = executor.submit_order(order)
    assert result.status == "REJECTED"
    assert "paper_trading_disabled" in result.rejection_reasons
