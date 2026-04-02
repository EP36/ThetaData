"""Reporting utilities for analytics outputs and artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.analytics.metrics import compute_metrics
from src.analytics.plots import plot_drawdown_curve, plot_equity_curve


@dataclass(slots=True)
class AnalyticsReport:
    """Container for analytics outputs and artifact locations."""

    metrics: dict[str, float]
    monthly_returns: pd.DataFrame
    artifacts: dict[str, str]


def build_monthly_returns_table(equity_curve: pd.Series) -> pd.DataFrame:
    """Build a monthly returns table from an equity curve."""
    returns = equity_curve.pct_change().fillna(0.0)
    monthly = (1.0 + returns).resample("ME").prod() - 1.0

    table = monthly.to_frame(name="return")
    table.index.name = "month"
    return table


def generate_analytics_report(
    equity_curve: pd.Series,
    strategy_returns: pd.Series,
    output_dir: str | Path,
) -> AnalyticsReport:
    """Generate metrics, plots, and monthly return table artifacts."""
    base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)

    metrics = compute_metrics(equity_curve=equity_curve, strategy_returns=strategy_returns)
    monthly_returns = build_monthly_returns_table(equity_curve)

    monthly_path = base / "monthly_returns.csv"
    monthly_returns.reset_index().to_csv(monthly_path, index=False)

    equity_plot_path = plot_equity_curve(equity_curve, base / "equity_curve.png")
    drawdown_plot_path = plot_drawdown_curve(equity_curve, base / "drawdown_curve.png")

    return AnalyticsReport(
        metrics=metrics,
        monthly_returns=monthly_returns,
        artifacts={
            "equity_curve_plot": str(equity_plot_path),
            "drawdown_plot": str(drawdown_plot_path),
            "monthly_returns_csv": str(monthly_path.resolve()),
        },
    )
