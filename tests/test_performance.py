"""Tests for performance metrics."""

from __future__ import annotations

import pandas as pd

from src.backtest.performance import compute_max_drawdown, compute_performance_report


def test_performance_report_values() -> None:
    equity = pd.Series([100.0, 110.0, 105.0, 120.0])
    strategy_returns = pd.Series([0.0, 0.10, -0.0454545, 0.1428571])

    report = compute_performance_report(equity, strategy_returns)

    assert round(report["total_return"], 4) == 0.2
    assert report["max_drawdown"] > 0.0
    assert round(report["win_rate"], 4) == round(2 / 3, 4)


def test_max_drawdown_calculation() -> None:
    equity = pd.Series([100.0, 120.0, 90.0, 95.0])
    assert compute_max_drawdown(equity) == 0.25
