"""Tests for analytics metric calculations."""

from __future__ import annotations

import pandas as pd

from src.analytics.metrics import compute_metrics


def test_compute_metrics_known_sample() -> None:
    equity = pd.Series([100.0, 120.0, 90.0, 95.0])
    returns = equity.pct_change().fillna(0.0)

    metrics = compute_metrics(equity_curve=equity, strategy_returns=returns)

    assert round(metrics["total_return"], 4) == -0.05
    assert round(metrics["max_drawdown"], 4) == 0.25
    assert "profit_factor" in metrics
    assert "expectancy" in metrics
