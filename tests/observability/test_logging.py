"""Tests for run-scoped logging configuration."""

from __future__ import annotations

import logging

import pandas as pd

from src.backtest.engine import BacktestEngine
from src.observability import (
    clear_run,
    configure_logging,
    current_run_id,
    reset_logging_for_tests,
    start_run,
)
from src.strategies.base import Strategy


class FlatSignalStrategy(Strategy):
    """Strategy returning deterministic flat signals."""

    name = "flat_signal_strategy"
    required_columns = ("close",)

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        self.validate_required_columns(data)
        return pd.DataFrame({"signal": 0.0}, index=data.index)


def test_logging_writes_file_with_run_id(tmp_path) -> None:
    reset_logging_for_tests()
    configure_logging(log_dir=tmp_path)
    run_id = start_run("test-run-123")
    logger = logging.getLogger("theta.test")
    logger.info("integration_log_event")
    clear_run()

    log_file = tmp_path / "system.log"
    content = log_file.read_text()
    assert run_id == "test-run-123"
    assert "integration_log_event" in content
    assert "run_id=test-run-123" in content


def test_backtest_emits_summary_log(tmp_path) -> None:
    reset_logging_for_tests()
    configure_logging(log_dir=tmp_path)
    start_run("backtest-run-1")

    index = pd.date_range("2025-01-01", periods=3, freq="D")
    data = pd.DataFrame(
        {
            "open": [100.0, 101.0, 102.0],
            "high": [101.0, 102.0, 103.0],
            "low": [99.0, 100.0, 101.0],
            "close": [100.0, 101.0, 102.0],
            "volume": [1000.0, 1000.0, 1000.0],
        },
        index=index,
    )

    engine = BacktestEngine(
        initial_capital=10_000.0,
        position_size_pct=1.0,
        fixed_fee=0.0,
        slippage_pct=0.0,
    )
    engine.run(data=data, strategy=FlatSignalStrategy(), symbol="TEST")
    clear_run()

    content = (tmp_path / "system.log").read_text()
    assert "backtest_run_start symbol=TEST" in content
    assert "backtest_run_summary symbol=TEST" in content
    assert current_run_id() == "-"
