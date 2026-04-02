"""Reporting helpers for backtest outputs."""

from __future__ import annotations

from dataclasses import asdict
from typing import Sequence

import pandas as pd

from src.analytics.metrics import compute_metrics
from src.backtest.types import Trade

TRADE_LOG_COLUMNS = (
    "timestamp",
    "side",
    "quantity",
    "fill_price",
    "fee",
    "reason",
    "cash_after",
    "shares_after",
    "equity_after",
)


def trades_to_frame(trades: Sequence[Trade]) -> pd.DataFrame:
    """Convert trade records into a DataFrame with stable column ordering."""
    if not trades:
        return pd.DataFrame(columns=TRADE_LOG_COLUMNS)

    return pd.DataFrame([asdict(trade) for trade in trades], columns=TRADE_LOG_COLUMNS)


def build_summary_metrics(
    equity_curve: pd.Series,
    strategy_returns: pd.Series,
    trades: Sequence[Trade],
) -> dict[str, float]:
    """Build summary metrics for reporting."""
    metrics = compute_metrics(
        equity_curve=equity_curve,
        strategy_returns=strategy_returns,
    )
    metrics["ending_equity"] = float(equity_curve.iloc[-1]) if not equity_curve.empty else 0.0
    metrics["num_trades"] = float(len(trades))
    return metrics
