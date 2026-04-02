"""Walk-forward optimization and out-of-sample evaluation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Any

import pandas as pd

from src.analytics.metrics import compute_metrics
from src.backtest.engine import BacktestEngine, BacktestResult
from src.risk.manager import RiskManager
from src.strategies import create_strategy


@dataclass(slots=True, frozen=True)
class WalkForwardWindow:
    """Train/test window boundaries."""

    train_start: int
    train_end: int
    test_start: int
    test_end: int


@dataclass(slots=True)
class WalkForwardWindowResult:
    """Result for one walk-forward train/test window."""

    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    best_params: dict[str, Any]
    train_score: float
    test_metrics: dict[str, float]


@dataclass(slots=True)
class WalkForwardResult:
    """Aggregate walk-forward output."""

    window_results: list[WalkForwardWindowResult]
    aggregate_metrics: dict[str, float]

    @property
    def selected_parameters(self) -> list[dict[str, Any]]:
        """Return selected parameter set for each window."""
        return [result.best_params for result in self.window_results]


@dataclass(slots=True)
class WalkForwardRunner:
    """Simple walk-forward runner over fixed train/test windows."""

    strategy_name: str
    parameter_grid: dict[str, list[Any]]
    train_size: int
    test_size: int
    step_size: int | None = None
    initial_capital: float = 100_000.0
    position_size_pct: float = 1.0
    fixed_fee: float = 1.0
    slippage_pct: float = 0.0005
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    max_position_size: float = 1.0
    max_daily_loss: float = 2_000.0

    def __post_init__(self) -> None:
        """Validate walk-forward configuration."""
        if self.train_size <= 0:
            raise ValueError("train_size must be positive")
        if self.test_size <= 0:
            raise ValueError("test_size must be positive")
        if self.step_size is not None and self.step_size <= 0:
            raise ValueError("step_size must be positive when provided")
        if not self.parameter_grid:
            raise ValueError("parameter_grid cannot be empty")
        for key, values in self.parameter_grid.items():
            if not values:
                raise ValueError(f"parameter_grid for '{key}' cannot be empty")

    def run(self, data: pd.DataFrame) -> WalkForwardResult:
        """Run walk-forward optimization and OOS evaluation."""
        windows = self.generate_windows(
            data_length=len(data),
            train_size=self.train_size,
            test_size=self.test_size,
            step_size=self.step_size or self.test_size,
        )
        if not windows:
            raise ValueError("No walk-forward windows generated for provided data length")

        results: list[WalkForwardWindowResult] = []
        out_of_sample_returns: list[pd.Series] = []

        for window in windows:
            train_data = data.iloc[window.train_start : window.train_end]
            test_data = data.iloc[window.test_start : window.test_end]
            best_params, train_score = self._select_best_params(train_data)
            test_result = self._run_backtest(test_data, best_params)
            out_of_sample_returns.append(test_result.strategy_returns)

            results.append(
                WalkForwardWindowResult(
                    train_start=pd.Timestamp(train_data.index[0]),
                    train_end=pd.Timestamp(train_data.index[-1]),
                    test_start=pd.Timestamp(test_data.index[0]),
                    test_end=pd.Timestamp(test_data.index[-1]),
                    best_params=best_params,
                    train_score=train_score,
                    test_metrics={key: float(value) for key, value in test_result.metrics.items()},
                )
            )

        aggregate_metrics = self._aggregate_metrics(out_of_sample_returns)
        return WalkForwardResult(window_results=results, aggregate_metrics=aggregate_metrics)

    @staticmethod
    def generate_windows(
        data_length: int,
        train_size: int,
        test_size: int,
        step_size: int,
    ) -> list[WalkForwardWindow]:
        """Generate rolling train/test index windows."""
        windows: list[WalkForwardWindow] = []
        start = 0
        while start + train_size + test_size <= data_length:
            train_start = start
            train_end = train_start + train_size
            test_start = train_end
            test_end = test_start + test_size
            windows.append(
                WalkForwardWindow(
                    train_start=train_start,
                    train_end=train_end,
                    test_start=test_start,
                    test_end=test_end,
                )
            )
            start += step_size
        return windows

    def _run_backtest(self, data: pd.DataFrame, params: dict[str, Any]) -> BacktestResult:
        """Run one backtest for a strategy parameter set."""
        strategy = create_strategy(self.strategy_name, **params)
        engine = BacktestEngine(
            initial_capital=self.initial_capital,
            position_size_pct=self.position_size_pct,
            fixed_fee=self.fixed_fee,
            slippage_pct=self.slippage_pct,
            stop_loss_pct=self.stop_loss_pct,
            take_profit_pct=self.take_profit_pct,
        )
        risk = RiskManager(
            max_position_size=self.max_position_size,
            max_daily_loss=self.max_daily_loss,
        )
        return engine.run(data=data, strategy=strategy, risk_manager=risk, symbol="WFO")

    def _select_best_params(self, train_data: pd.DataFrame) -> tuple[dict[str, Any], float]:
        """Select best parameter set by train total return."""
        best_params: dict[str, Any] | None = None
        best_score = float("-inf")

        for params in self._parameter_combinations():
            result = self._run_backtest(train_data, params)
            score = float(result.metrics.get("total_return", 0.0))
            if score > best_score:
                best_score = score
                best_params = params

        assert best_params is not None
        return best_params, best_score

    def _parameter_combinations(self) -> list[dict[str, Any]]:
        """Expand parameter grid into concrete combinations."""
        keys = sorted(self.parameter_grid)
        values = [self.parameter_grid[key] for key in keys]
        combinations = []
        for combo in product(*values):
            combinations.append(dict(zip(keys, combo)))
        return combinations

    @staticmethod
    def _aggregate_metrics(out_of_sample_returns: list[pd.Series]) -> dict[str, float]:
        """Aggregate OOS returns into one metrics dictionary."""
        if not out_of_sample_returns:
            return {}
        combined_returns = pd.concat(out_of_sample_returns).sort_index()
        combined_returns = combined_returns[~combined_returns.index.duplicated(keep="last")]
        if combined_returns.empty:
            return {}

        equity_curve = (1.0 + combined_returns).cumprod().rename("equity")
        metrics = compute_metrics(
            equity_curve=equity_curve,
            strategy_returns=combined_returns,
        )
        metrics["num_windows"] = float(len(out_of_sample_returns))
        return {key: float(value) for key, value in metrics.items()}
