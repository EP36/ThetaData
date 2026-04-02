"""Tests for walk-forward optimization workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import pandas as pd

from src.backtest.walk_forward import WalkForwardRunner
from src.strategies import register_strategy
from src.strategies.base import Strategy


@dataclass(slots=True)
class ThresholdStrategy(Strategy):
    """Test strategy with a threshold parameter for deterministic selection."""

    name: ClassVar[str] = "wf_threshold_strategy"
    required_columns: ClassVar[tuple[str, ...]] = ("close",)
    threshold: float = 100.0

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        self.validate_required_columns(data)
        signal = (data["close"].astype(float) > self.threshold).astype(float)
        return pd.DataFrame({"signal": signal}, index=data.index)


register_strategy(ThresholdStrategy)


def make_data(length: int = 24) -> pd.DataFrame:
    """Create monotonically increasing OHLCV for walk-forward tests."""
    index = pd.date_range("2024-01-01", periods=length, freq="D")
    close = pd.Series([90.0 + i for i in range(length)], index=index)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 1_000.0,
        },
        index=index,
    )


def test_generate_windows() -> None:
    windows = WalkForwardRunner.generate_windows(
        data_length=20,
        train_size=8,
        test_size=4,
        step_size=4,
    )
    assert len(windows) == 3
    assert windows[0].train_start == 0
    assert windows[0].test_end == 12
    assert windows[-1].train_start == 8
    assert windows[-1].test_end == 20


def test_aggregate_metrics_contains_num_windows() -> None:
    first = pd.Series([0.01, -0.01], index=pd.date_range("2024-01-01", periods=2, freq="D"))
    second = pd.Series([0.02], index=pd.date_range("2024-01-03", periods=1, freq="D"))
    metrics = WalkForwardRunner._aggregate_metrics([first, second])
    assert "total_return" in metrics
    assert metrics["num_windows"] == 2.0


def test_walk_forward_parameter_selection_workflow() -> None:
    runner = WalkForwardRunner(
        strategy_name="wf_threshold_strategy",
        parameter_grid={"threshold": [95.0, 125.0]},
        train_size=12,
        test_size=6,
        step_size=6,
        fixed_fee=0.0,
        slippage_pct=0.0,
    )
    result = runner.run(make_data())

    assert len(result.window_results) == 2
    assert all(window.best_params["threshold"] == 95.0 for window in result.window_results)
    assert len(result.selected_parameters) == 2
    assert result.aggregate_metrics["num_windows"] == 2.0
