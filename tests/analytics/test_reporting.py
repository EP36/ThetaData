"""Tests for analytics reporting artifact generation."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.analytics.reporting import build_monthly_returns_table, generate_analytics_report


def test_monthly_returns_table_structure() -> None:
    index = pd.date_range("2025-01-01", periods=90, freq="D")
    equity = pd.Series(100.0 + pd.Series(range(90), index=index), index=index)

    monthly = build_monthly_returns_table(equity)

    assert "return" in monthly.columns
    assert len(monthly) >= 2


def test_generate_analytics_report_outputs_artifacts(tmp_path) -> None:
    index = pd.date_range("2025-01-01", periods=60, freq="D")
    equity = pd.Series(100.0 + pd.Series(range(60), index=index), index=index)
    returns = equity.pct_change().fillna(0.0)

    report = generate_analytics_report(
        equity_curve=equity,
        strategy_returns=returns,
        output_dir=tmp_path / "report",
    )

    assert "total_return" in report.metrics
    assert "monthly_returns_csv" in report.artifacts

    for artifact_path in report.artifacts.values():
        assert Path(artifact_path).exists()
