"""Tests for the backtesting engine and report."""

from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from trauto.backtester.report import (
    TradeRecord,
    compute_metrics,
    write_results,
    list_results,
    read_result,
    _max_drawdown,
    _sharpe_ratio,
)
from trauto.backtester.engine import BacktestJob, BacktestRunner, BacktestStatus


# ---------------------------------------------------------------------------
# Report / metrics tests
# ---------------------------------------------------------------------------

class TestMaxDrawdown:
    def test_no_drawdown(self):
        assert _max_drawdown([100, 110, 120, 130]) == pytest.approx(0.0)

    def test_full_loss(self):
        dd = _max_drawdown([100, 50])
        assert dd == pytest.approx(50.0)

    def test_partial_drawdown(self):
        dd = _max_drawdown([100, 120, 90, 130])
        # Peak was 120, trough was 90 → (120-90)/120 = 25%
        assert dd == pytest.approx(25.0)

    def test_single_bar(self):
        assert _max_drawdown([100]) == 0.0

    def test_empty(self):
        assert _max_drawdown([]) == 0.0


class TestSharpeRatio:
    def test_flat_returns_zero(self):
        equity = [100.0] * 10
        s = _sharpe_ratio(equity, risk_free_rate=0.0)
        assert s == 0.0

    def test_positive_returns(self):
        equity = [100.0 + i * 5 for i in range(252)]
        s = _sharpe_ratio(equity, risk_free_rate=0.05)
        assert s > 0

    def test_single_bar(self):
        assert _sharpe_ratio([100.0]) == 0.0

    def test_all_same(self):
        assert _sharpe_ratio([100.0, 100.0, 100.0]) == 0.0


class TestComputeMetrics:
    def _make_trade(self, pnl: float, pnl_pct: float, bars: int = 5) -> TradeRecord:
        return TradeRecord(
            symbol="SPY", strategy="test", side="long",
            entry_price=100.0, exit_price=100.0 + pnl / 10,
            quantity=10.0, pnl=pnl, pnl_pct=pnl_pct,
            entry_at="2024-01-01", exit_at="2024-01-06", hold_bars=bars,
        )

    def test_basic_metrics(self):
        trades = [self._make_trade(100, 10), self._make_trade(-50, -5)]
        equity = [10000.0, 10100.0, 10050.0]
        m = compute_metrics(
            trades=trades, equity_curve=equity, initial_capital=10000.0,
            strategy_name="test", start_date="2024-01-01", end_date="2024-01-31",
        )
        assert m.total_trades == 2
        assert m.win_rate == pytest.approx(0.5)
        assert m.total_return_pct == pytest.approx(0.5, abs=0.01)
        assert m.best_trade_pnl == 100.0
        assert m.worst_trade_pnl == -50.0

    def test_no_trades(self):
        m = compute_metrics(
            trades=[], equity_curve=[10000.0], initial_capital=10000.0,
            strategy_name="test", start_date="2024-01-01", end_date="2024-01-31",
        )
        assert m.total_trades == 0
        assert m.win_rate == 0.0
        assert m.total_return_pct == 0.0

    def test_run_id_assigned(self):
        m = compute_metrics(
            trades=[], equity_curve=[10000.0], initial_capital=10000.0,
            strategy_name="test", start_date="2024-01-01", end_date="2024-01-31",
            run_id="abc123",
        )
        assert m.run_id == "abc123"

    def test_equity_curve_points(self):
        equity = [1000.0, 1050.0, 1025.0]
        m = compute_metrics(
            trades=[], equity_curve=equity, initial_capital=1000.0,
            strategy_name="test", start_date="2024-01-01", end_date="2024-01-31",
        )
        assert len(m.equity_curve) == 3
        assert m.equity_curve[0]["equity"] == 1000.0


class TestWriteAndReadResults:
    def test_write_creates_file(self, tmp_path, monkeypatch):
        import trauto.backtester.report as report_mod
        monkeypatch.setattr(report_mod, "_RESULTS_DIR", tmp_path / "backtest_results")
        m = compute_metrics(
            trades=[], equity_curve=[10000.0], initial_capital=10000.0,
            strategy_name="test", start_date="2024-01-01", end_date="2024-01-31",
            run_id="test001",
        )
        path = write_results(m)
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["run_id"] == "test001"

    def test_read_result(self, tmp_path, monkeypatch):
        import trauto.backtester.report as report_mod
        monkeypatch.setattr(report_mod, "_RESULTS_DIR", tmp_path / "backtest_results")
        m = compute_metrics(
            trades=[], equity_curve=[10000.0], initial_capital=10000.0,
            strategy_name="test", start_date="2024-01-01", end_date="2024-01-31",
            run_id="test002",
        )
        write_results(m)
        result = read_result("test002")
        assert result is not None
        assert result["run_id"] == "test002"

    def test_list_results(self, tmp_path, monkeypatch):
        import trauto.backtester.report as report_mod
        monkeypatch.setattr(report_mod, "_RESULTS_DIR", tmp_path / "backtest_results")
        for rid in ["r1", "r2"]:
            m = compute_metrics(
                trades=[], equity_curve=[10000.0], initial_capital=10000.0,
                strategy_name="test", start_date="2024-01-01", end_date="2024-01-31",
                run_id=rid,
            )
            write_results(m)
        results = list_results()
        assert len(results) == 2

    def test_read_nonexistent(self, tmp_path, monkeypatch):
        import trauto.backtester.report as report_mod
        monkeypatch.setattr(report_mod, "_RESULTS_DIR", tmp_path / "backtest_results")
        assert read_result("nonexistent") is None


# ---------------------------------------------------------------------------
# BacktestRunner
# ---------------------------------------------------------------------------

class TestBacktestRunner:
    def test_submit_returns_job_id(self, tmp_path, monkeypatch):
        import trauto.backtester.report as report_mod
        monkeypatch.setattr(report_mod, "_RESULTS_DIR", tmp_path / "backtest_results")
        runner = BacktestRunner()
        job_id = runner.submit(
            strategy_name="alpaca.momentum",
            start_date="2024-01-01",
            end_date="2024-01-31",
        )
        assert isinstance(job_id, str)
        assert len(job_id) > 0

    def test_get_status_pending(self, tmp_path, monkeypatch):
        import trauto.backtester.report as report_mod
        monkeypatch.setattr(report_mod, "_RESULTS_DIR", tmp_path / "backtest_results")
        runner = BacktestRunner()
        job_id = runner.submit(
            strategy_name="alpaca.momentum",
            start_date="2024-01-01",
            end_date="2024-01-31",
        )
        job = runner.get_status(job_id)
        assert job is not None
        assert job.status in (BacktestStatus.PENDING, BacktestStatus.RUNNING, BacktestStatus.COMPLETE)

    def test_get_status_nonexistent(self):
        runner = BacktestRunner()
        assert runner.get_status("nonexistent") is None

    def test_list_jobs(self, tmp_path, monkeypatch):
        import trauto.backtester.report as report_mod
        monkeypatch.setattr(report_mod, "_RESULTS_DIR", tmp_path / "backtest_results")
        runner = BacktestRunner()
        runner.submit("alpaca.momentum", "2024-01-01", "2024-01-31")
        runner.submit("alpaca.mean_revert", "2024-01-01", "2024-01-31")
        jobs = runner.list_jobs()
        assert len(jobs) == 2

    def test_alpaca_backtest_empty_bars(self, tmp_path, monkeypatch):
        """Empty bars → returns empty metrics without crash."""
        import trauto.backtester.report as report_mod
        monkeypatch.setattr(report_mod, "_RESULTS_DIR", tmp_path / "backtest_results")
        with patch("trauto.backtester.engine.load_alpaca_bars", return_value=pd.DataFrame()):
            runner = BacktestRunner()
            job = BacktestJob(
                job_id="test_empty",
                strategy_name="alpaca.momentum",
                start_date="2024-01-01",
                end_date="2024-01-31",
                symbol="SPY",
                initial_capital=10000.0,
            )
            metrics = runner._run_alpaca_backtest(job, use_live_params=False)
            assert metrics.total_trades == 0

    def test_alpaca_backtest_with_bars(self, tmp_path, monkeypatch):
        """Known bars produce deterministic P&L."""
        import trauto.backtester.report as report_mod
        monkeypatch.setattr(report_mod, "_RESULTS_DIR", tmp_path / "backtest_results")

        # Trending up: short MA crosses above long MA → buy → sell at end
        prices = [100] * 4 + [110, 115, 120, 125, 130, 135] * 3
        df = pd.DataFrame(
            {"open": prices, "high": prices, "low": prices, "close": prices, "volume": [1e6] * len(prices)},
            index=pd.date_range("2024-01-01", periods=len(prices)),
        )
        with patch("trauto.backtester.engine.load_alpaca_bars", return_value=df):
            runner = BacktestRunner()
            job = BacktestJob(
                job_id="test_bars",
                strategy_name="alpaca.momentum",
                start_date="2024-01-01",
                end_date="2024-03-01",
                symbol="SPY",
                initial_capital=10000.0,
            )
            metrics = runner._run_alpaca_backtest(job, use_live_params=False)
            assert isinstance(metrics.total_return_pct, float)
            assert not math.isnan(metrics.total_return_pct)
