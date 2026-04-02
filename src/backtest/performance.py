"""Performance metric calculations for backtests."""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_total_return(equity_curve: pd.Series) -> float:
    """Compute total return from start to finish."""
    if len(equity_curve) < 2:
        return 0.0
    return float(equity_curve.iloc[-1] / equity_curve.iloc[0] - 1.0)


def compute_sharpe(returns: pd.Series, periods_per_year: int = 252) -> float:
    """Compute annualized Sharpe ratio from periodic returns."""
    clean = returns.replace([np.inf, -np.inf], np.nan).dropna()
    if clean.empty:
        return 0.0

    std = float(clean.std(ddof=0))
    if std == 0.0:
        return 0.0

    mean = float(clean.mean())
    return float(np.sqrt(periods_per_year) * mean / std)


def compute_max_drawdown(equity_curve: pd.Series) -> float:
    """Compute maximum drawdown magnitude as a positive value."""
    if equity_curve.empty:
        return 0.0

    running_max = equity_curve.cummax()
    drawdown = equity_curve / running_max - 1.0
    return float(abs(drawdown.min()))


def compute_win_rate(strategy_returns: pd.Series) -> float:
    """Compute fraction of positive active return periods."""
    active = strategy_returns[strategy_returns != 0.0]
    if active.empty:
        return 0.0

    wins = (active > 0.0).sum()
    return float(wins / len(active))


def compute_performance_report(
    equity_curve: pd.Series,
    strategy_returns: pd.Series,
) -> dict[str, float]:
    """Build a standard performance report dictionary."""
    return {
        "total_return": compute_total_return(equity_curve),
        "sharpe": compute_sharpe(strategy_returns),
        "max_drawdown": compute_max_drawdown(equity_curve),
        "win_rate": compute_win_rate(strategy_returns),
    }
