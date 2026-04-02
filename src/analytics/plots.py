"""Matplotlib plotting helpers for analytics artifacts."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd


def plot_equity_curve(equity_curve: pd.Series, output_path: str | Path) -> Path:
    """Generate equity curve plot and save to file."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(10, 4))
    equity_curve.plot(ax=ax)
    ax.set_title("Equity Curve")
    ax.set_xlabel("Timestamp")
    ax.set_ylabel("Equity")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)

    return path.resolve()


def plot_drawdown_curve(equity_curve: pd.Series, output_path: str | Path) -> Path:
    """Generate drawdown curve plot and save to file."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    running_max = equity_curve.cummax()
    drawdown = equity_curve / running_max - 1.0

    fig, ax = plt.subplots(figsize=(10, 4))
    drawdown.plot(ax=ax, color="tab:red")
    ax.set_title("Drawdown Curve")
    ax.set_xlabel("Timestamp")
    ax.set_ylabel("Drawdown")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)

    return path.resolve()
