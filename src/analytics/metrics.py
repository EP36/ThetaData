"""Performance analytics metrics for backtest results."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _clean_returns(returns: pd.Series) -> pd.Series:
    """Normalize return series for metric calculations."""
    return returns.replace([np.inf, -np.inf], np.nan).dropna()


def compute_total_return(equity_curve: pd.Series) -> float:
    """Compute total return from first to last equity values."""
    if len(equity_curve) < 2:
        return 0.0
    return float(equity_curve.iloc[-1] / equity_curve.iloc[0] - 1.0)


def compute_annualized_return(returns: pd.Series, periods_per_year: int = 252) -> float:
    """Compute annualized return from periodic returns."""
    clean = _clean_returns(returns)
    if clean.empty:
        return 0.0

    cumulative = float((1.0 + clean).prod())
    n_periods = len(clean)
    if cumulative <= 0 or n_periods == 0:
        return 0.0

    years = n_periods / periods_per_year
    if years <= 0:
        return 0.0

    return float(cumulative ** (1.0 / years) - 1.0)


def compute_volatility(returns: pd.Series, periods_per_year: int = 252) -> float:
    """Compute annualized volatility."""
    clean = _clean_returns(returns)
    if clean.empty:
        return 0.0
    return float(clean.std(ddof=0) * np.sqrt(periods_per_year))


def compute_sharpe(returns: pd.Series, periods_per_year: int = 252) -> float:
    """Compute annualized Sharpe ratio."""
    clean = _clean_returns(returns)
    if clean.empty:
        return 0.0

    std = float(clean.std(ddof=0))
    if std == 0.0:
        return 0.0
    return float(np.sqrt(periods_per_year) * clean.mean() / std)


def compute_sortino(returns: pd.Series, periods_per_year: int = 252) -> float:
    """Compute annualized Sortino ratio."""
    clean = _clean_returns(returns)
    if clean.empty:
        return 0.0

    downside = clean[clean < 0]
    downside_std = float(downside.std(ddof=0)) if not downside.empty else 0.0
    if downside_std == 0.0:
        return 0.0

    return float(np.sqrt(periods_per_year) * clean.mean() / downside_std)


def compute_max_drawdown(equity_curve: pd.Series) -> float:
    """Compute maximum drawdown magnitude as a positive value."""
    if equity_curve.empty:
        return 0.0
    running_max = equity_curve.cummax()
    drawdown = equity_curve / running_max - 1.0
    return float(abs(drawdown.min()))


def compute_calmar(
    returns: pd.Series,
    equity_curve: pd.Series,
    periods_per_year: int = 252,
) -> float:
    """Compute Calmar ratio (annualized return / max drawdown)."""
    annualized_return = compute_annualized_return(returns, periods_per_year)
    max_drawdown = compute_max_drawdown(equity_curve)
    if max_drawdown == 0.0:
        return 0.0
    return float(annualized_return / max_drawdown)


def compute_win_rate(returns: pd.Series) -> float:
    """Compute fraction of positive non-zero return periods."""
    clean = _clean_returns(returns)
    active = clean[clean != 0.0]
    if active.empty:
        return 0.0
    return float((active > 0.0).sum() / len(active))


def compute_avg_win(returns: pd.Series) -> float:
    """Compute mean positive return."""
    clean = _clean_returns(returns)
    wins = clean[clean > 0.0]
    if wins.empty:
        return 0.0
    return float(wins.mean())


def compute_avg_loss(returns: pd.Series) -> float:
    """Compute mean negative return."""
    clean = _clean_returns(returns)
    losses = clean[clean < 0.0]
    if losses.empty:
        return 0.0
    return float(losses.mean())


def compute_profit_factor(returns: pd.Series) -> float:
    """Compute profit factor from periodic returns."""
    clean = _clean_returns(returns)
    gross_profit = float(clean[clean > 0.0].sum())
    gross_loss = float(abs(clean[clean < 0.0].sum()))
    if gross_loss == 0.0:
        return 0.0
    return float(gross_profit / gross_loss)


def compute_expectancy(returns: pd.Series) -> float:
    """Compute expectancy using win rate and average win/loss."""
    win_rate = compute_win_rate(returns)
    avg_win = compute_avg_win(returns)
    avg_loss = abs(compute_avg_loss(returns))
    return float((win_rate * avg_win) - ((1.0 - win_rate) * avg_loss))


def compute_metrics(
    equity_curve: pd.Series,
    strategy_returns: pd.Series | None = None,
    periods_per_year: int = 252,
) -> dict[str, float]:
    """Compute full analytics metric set from backtest results."""
    returns = (
        strategy_returns
        if strategy_returns is not None
        else equity_curve.pct_change().fillna(0.0)
    )

    return {
        "total_return": compute_total_return(equity_curve),
        "annualized_return": compute_annualized_return(returns, periods_per_year),
        "volatility": compute_volatility(returns, periods_per_year),
        "sharpe": compute_sharpe(returns, periods_per_year),
        "sortino": compute_sortino(returns, periods_per_year),
        "max_drawdown": compute_max_drawdown(equity_curve),
        "calmar": compute_calmar(returns, equity_curve, periods_per_year),
        "win_rate": compute_win_rate(returns),
        "average_win": compute_avg_win(returns),
        "average_loss": compute_avg_loss(returns),
        "profit_factor": compute_profit_factor(returns),
        "expectancy": compute_expectancy(returns),
    }
