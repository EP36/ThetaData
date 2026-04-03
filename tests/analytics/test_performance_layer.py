"""Tests for deterministic performance analytics layer."""

from __future__ import annotations

import pandas as pd

from src.analytics.performance_layer import build_performance_snapshot
from src.execution.models import Position
from src.persistence.repository import PortfolioSnapshot


def _portfolio_snapshot() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        cash=100_000.0,
        day_start_equity=100_000.0,
        peak_equity=100_000.0,
        positions={},
    )


def test_strategy_metrics_from_realized_outcomes() -> None:
    fills = [
        {
            "run_id": "run-1",
            "timestamp": pd.Timestamp("2026-01-01T10:00:00Z"),
            "symbol": "SPY",
            "side": "BUY",
            "quantity": 1.0,
            "price": 100.0,
            "strategy": "moving_average_crossover",
        },
        {
            "run_id": "run-1",
            "timestamp": pd.Timestamp("2026-01-02T10:00:00Z"),
            "symbol": "SPY",
            "side": "SELL",
            "quantity": 1.0,
            "price": 110.0,
            "strategy": "moving_average_crossover",
        },
        {
            "run_id": "run-1",
            "timestamp": pd.Timestamp("2026-01-03T10:00:00Z"),
            "symbol": "SPY",
            "side": "BUY",
            "quantity": 1.0,
            "price": 100.0,
            "strategy": "moving_average_crossover",
        },
        {
            "run_id": "run-1",
            "timestamp": pd.Timestamp("2026-01-04T10:00:00Z"),
            "symbol": "SPY",
            "side": "SELL",
            "quantity": 1.0,
            "price": 90.0,
            "strategy": "moving_average_crossover",
        },
    ]
    runs = [
        {
            "run_id": "run-1",
            "strategy": "moving_average_crossover",
            "timeframe": "1d",
            "details": {"selection": {"regime": "trending"}},
        }
    ]

    snapshot = build_performance_snapshot(
        fills=fills,
        runs=runs,
        portfolio_snapshot=_portfolio_snapshot(),
        starting_equity=100_000.0,
    )

    assert len(snapshot.strategies) == 1
    metrics = snapshot.strategies[0]
    assert metrics.strategy == "moving_average_crossover"
    assert metrics.num_trades == 2
    assert metrics.win_rate == 0.5
    assert metrics.average_win == 10.0
    assert metrics.average_loss == -10.0
    assert metrics.profit_factor == 1.0
    assert abs(metrics.expectancy) < 1e-9


def test_rolling_window_metrics_are_deterministic() -> None:
    fills: list[dict[str, object]] = []
    start = pd.Timestamp("2026-01-01T10:00:00Z")
    for idx in range(25):
        entry = start + pd.Timedelta(hours=idx * 2)
        exit_ = entry + pd.Timedelta(hours=1)
        fills.extend(
            [
                {
                    "run_id": "run-roll",
                    "timestamp": entry,
                    "symbol": "QQQ",
                    "side": "BUY",
                    "quantity": 1.0,
                    "price": 100.0,
                    "strategy": "breakout_momentum",
                },
                {
                    "run_id": "run-roll",
                    "timestamp": exit_,
                    "symbol": "QQQ",
                    "side": "SELL",
                    "quantity": 1.0,
                    "price": 101.0,
                    "strategy": "breakout_momentum",
                },
            ]
        )

    runs = [
        {
            "run_id": "run-roll",
            "strategy": "breakout_momentum",
            "timeframe": "1h",
            "details": {"selection": {"regime": "trending"}},
        }
    ]

    snapshot = build_performance_snapshot(
        fills=fills,
        runs=runs,
        portfolio_snapshot=_portfolio_snapshot(),
        starting_equity=100_000.0,
    )

    metrics = snapshot.strategies[0]
    assert metrics.num_trades == 25
    assert len(metrics.rolling_20_series) == 6
    assert metrics.rolling_20_win_rate == 1.0
    assert metrics.last_20.trades == 20
    assert metrics.last_5.trades == 5


def test_empty_state_snapshot_returns_empty_series() -> None:
    snapshot = build_performance_snapshot(
        fills=[],
        runs=[],
        portfolio_snapshot=PortfolioSnapshot(
            cash=100_000.0,
            day_start_equity=100_000.0,
            peak_equity=100_000.0,
            positions={
                "SPY": Position(
                    symbol="SPY",
                    quantity=0.0,
                    avg_price=0.0,
                    realized_pnl=0.0,
                    unrealized_pnl=0.0,
                )
            },
        ),
        starting_equity=100_000.0,
    )

    assert snapshot.strategies == ()
    assert snapshot.portfolio.equity_curve == ()
    assert snapshot.portfolio.daily_pnl == ()
    assert snapshot.context.by_symbol == ()
