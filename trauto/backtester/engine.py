"""Backtesting engine — runs in complete isolation from live brokers.

Never touches live broker clients, never places real orders, never
modifies positions.json or any live data files.

Usage:
    runner = BacktestRunner()
    job_id = runner.submit(
        strategy_name="alpaca.momentum",
        start_date="2024-01-01",
        end_date="2024-12-31",
        symbol="SPY",
    )
    # Async job — poll status:
    status = runner.get_status(job_id)
    result = runner.get_result(job_id)   # None until complete
"""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import pandas as pd

from trauto.backtester.data_loader import load_alpaca_bars, load_polymarket_history
from trauto.backtester.report import (
    BacktestMetrics,
    TradeRecord,
    compute_metrics,
    write_results,
    list_results,
    read_result,
)

LOGGER = logging.getLogger("trauto.backtester.engine")

_SLIPPAGE_PCT_DEFAULT = 0.001  # 0.1%


class BacktestStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class BacktestJob:
    """Metadata for a submitted backtest job."""
    job_id: str
    strategy_name: str
    start_date: str
    end_date: str
    symbol: str
    initial_capital: float
    status: BacktestStatus = BacktestStatus.PENDING
    submitted_at: str = field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())
    completed_at: str = ""
    error: str = ""
    result_path: str = ""


class BacktestRunner:
    """Manages async backtest jobs.

    Each backtest runs in a background asyncio task so the caller
    can submit and poll non-blocking.
    """

    def __init__(self, slippage_pct: float = _SLIPPAGE_PCT_DEFAULT) -> None:
        self.slippage_pct = slippage_pct
        self._jobs: dict[str, BacktestJob] = {}
        self._results: dict[str, BacktestMetrics] = {}

    def submit(
        self,
        strategy_name: str,
        start_date: str,
        end_date: str,
        symbol: str = "SPY",
        initial_capital: float = 100_000.0,
        poly_history_path: str = "",
        use_live_params: bool = True,
    ) -> str:
        """Submit a backtest job. Returns job_id. Runs async in background."""
        job_id = str(uuid.uuid4())[:8]
        job = BacktestJob(
            job_id=job_id,
            strategy_name=strategy_name,
            start_date=start_date,
            end_date=end_date,
            symbol=symbol,
            initial_capital=initial_capital,
        )
        self._jobs[job_id] = job

        t = threading.Thread(
            target=self._run_job_sync,
            args=(job, poly_history_path, use_live_params),
            daemon=True,
            name=f"backtest_{job_id}",
        )
        t.start()
        LOGGER.info(
            "backtest_submitted job_id=%s strategy=%s symbol=%s %s→%s",
            job_id,
            strategy_name,
            symbol,
            start_date,
            end_date,
        )
        return job_id

    def get_status(self, job_id: str) -> BacktestJob | None:
        return self._jobs.get(job_id)

    def get_result(self, job_id: str) -> BacktestMetrics | None:
        return self._results.get(job_id)

    def list_jobs(self) -> list[BacktestJob]:
        return sorted(self._jobs.values(), key=lambda j: j.submitted_at, reverse=True)

    # ------------------------------------------------------------------
    # Internal job runner
    # ------------------------------------------------------------------

    def _run_job_sync(
        self,
        job: BacktestJob,
        poly_history_path: str,
        use_live_params: bool,
    ) -> None:
        """Execute the backtest synchronously (called from background thread)."""
        job.status = BacktestStatus.RUNNING
        LOGGER.info("backtest_running job_id=%s", job.job_id)
        try:
            metrics = self._run_sync(job, poly_history_path, use_live_params)
            self._results[job.job_id] = metrics
            result_path = write_results(metrics)
            job.result_path = str(result_path)
            job.status = BacktestStatus.COMPLETE
            LOGGER.info(
                "backtest_complete job_id=%s return=%.2f%% trades=%d",
                job.job_id,
                metrics.total_return_pct,
                metrics.total_trades,
            )
        except Exception as exc:
            job.status = BacktestStatus.FAILED
            job.error = str(exc)
            LOGGER.error("backtest_failed job_id=%s error=%s", job.job_id, exc)
        finally:
            job.completed_at = datetime.now(tz=timezone.utc).isoformat()

    def _run_sync(
        self,
        job: BacktestJob,
        poly_history_path: str,
        use_live_params: bool,
    ) -> BacktestMetrics:
        """Synchronous backtest execution (runs in thread pool)."""
        strategy_name = job.strategy_name

        # Load data
        is_poly_strategy = strategy_name.startswith("polymarket.")
        if is_poly_strategy:
            data = self._run_poly_backtest(job, poly_history_path, use_live_params)
        else:
            data = self._run_alpaca_backtest(job, use_live_params)

        return data

    def _run_alpaca_backtest(self, job: BacktestJob, use_live_params: bool) -> BacktestMetrics:
        """Run backtest for an Alpaca equity strategy."""
        bars = load_alpaca_bars(
            symbol=job.symbol,
            timeframe="1d",
            start=job.start_date,
            end=job.end_date,
        )
        if bars.empty:
            LOGGER.warning("backtest_no_data job_id=%s symbol=%s", job.job_id, job.symbol)
            return self._empty_metrics(job)

        # Instantiate strategy from registry
        strategy = self._load_strategy(job.strategy_name)
        if strategy is None:
            raise ValueError(f"Unknown strategy: {job.strategy_name}")

        # Replay bars through on_bar (strategy uses pandas generate_signals under the hood)
        trades: list[TradeRecord] = []
        equity = float(job.initial_capital)
        equity_curve = [equity]
        position: dict[str, Any] | None = None

        from src.strategies.base import Strategy as _SrcStrategy
        if hasattr(strategy, "_inner") and isinstance(strategy._inner, _SrcStrategy):
            inner = strategy._inner
            signals_df = inner.generate_signals(bars)
            signal_series = signals_df["signal"]
        else:
            signal_series = pd.Series(0.0, index=bars.index)

        for i in range(1, len(bars)):
            prev_sig = float(signal_series.iloc[i - 1])
            curr_sig = float(signal_series.iloc[i])
            price = float(bars["close"].iloc[i])
            ts = str(bars.index[i])

            slipped_price = price * (1 + self.slippage_pct)

            if prev_sig <= 0 and curr_sig > 0 and position is None:
                # Entry
                qty = equity / slipped_price
                position = {"entry_price": slipped_price, "qty": qty, "entry_ts": ts, "bar": i}

            elif prev_sig > 0 and curr_sig <= 0 and position is not None:
                # Exit
                exit_price = price * (1 - self.slippage_pct)
                pnl = (exit_price - position["entry_price"]) * position["qty"]
                pnl_pct = (exit_price - position["entry_price"]) / position["entry_price"] * 100
                equity += pnl
                trades.append(TradeRecord(
                    symbol=job.symbol,
                    strategy=job.strategy_name,
                    side="long",
                    entry_price=position["entry_price"],
                    exit_price=exit_price,
                    quantity=position["qty"],
                    pnl=round(pnl, 4),
                    pnl_pct=round(pnl_pct, 4),
                    entry_at=position["entry_ts"],
                    exit_at=ts,
                    hold_bars=i - position["bar"],
                ))
                position = None

            equity_curve.append(round(equity, 2))

        return compute_metrics(
            trades=trades,
            equity_curve=equity_curve,
            initial_capital=job.initial_capital,
            strategy_name=job.strategy_name,
            start_date=job.start_date,
            end_date=job.end_date,
            run_id=job.job_id,
        )

    def _run_poly_backtest(
        self,
        job: BacktestJob,
        poly_history_path: str,
        use_live_params: bool,
    ) -> BacktestMetrics:
        """Run backtest for a Polymarket strategy using user-provided history."""
        if not poly_history_path:
            LOGGER.warning("backtest_poly_no_history_path job_id=%s", job.job_id)
            return self._empty_metrics(job)

        markets = load_polymarket_history(poly_history_path)
        if not markets:
            return self._empty_metrics(job)

        # Load signal params for scoring
        if use_live_params:
            from src.polymarket.signals import get_signal_params
            params = get_signal_params()
        else:
            from src.polymarket.signals import _DEFAULT_PARAMS
            params = dict(_DEFAULT_PARAMS)

        trades: list[TradeRecord] = []
        equity = float(job.initial_capital)
        equity_curve = [equity]

        for market in markets:
            prices = market.get("yes_prices", [])
            if not prices:
                continue
            resolved = market.get("resolved_outcome", None)
            if resolved is None:
                continue

            # Simulate: enter at first price above 0.5 edge threshold
            entry = None
            for tick in prices:
                p = float(tick.get("price", 0))
                if p <= 0:
                    continue
                if entry is None and p < 0.4:
                    entry = {"price": p * (1 + self.slippage_pct), "ts": tick.get("timestamp", "")}

            if entry is None:
                continue

            exit_price = 1.0 if resolved == "YES" else 0.0
            pnl_pct = (exit_price - entry["price"]) / entry["price"] * 100 if entry["price"] > 0 else 0
            size = min(500.0, equity * 0.05)
            qty = size / entry["price"] if entry["price"] > 0 else 0
            pnl = qty * (exit_price - entry["price"])
            equity += pnl
            trades.append(TradeRecord(
                symbol=market.get("condition_id", "unknown"),
                strategy=job.strategy_name,
                side="YES",
                entry_price=entry["price"],
                exit_price=exit_price,
                quantity=qty,
                pnl=round(pnl, 4),
                pnl_pct=round(pnl_pct, 4),
                entry_at=entry["ts"],
                exit_at="",
                hold_bars=0,
            ))
            equity_curve.append(round(equity, 2))

        return compute_metrics(
            trades=trades,
            equity_curve=equity_curve,
            initial_capital=job.initial_capital,
            strategy_name=job.strategy_name,
            start_date=job.start_date,
            end_date=job.end_date,
            run_id=job.job_id,
        )

    def _empty_metrics(self, job: BacktestJob) -> BacktestMetrics:
        from trauto.backtester.report import BacktestMetrics
        return BacktestMetrics(
            run_id=job.job_id,
            strategy_name=job.strategy_name,
            start_date=job.start_date,
            end_date=job.end_date,
            initial_capital=job.initial_capital,
            final_capital=job.initial_capital,
            total_return_pct=0.0,
            win_rate=0.0,
            max_drawdown_pct=0.0,
            sharpe_ratio=0.0,
            total_trades=0,
            avg_hold_bars=0.0,
            best_trade_pnl=0.0,
            worst_trade_pnl=0.0,
            avg_pnl_per_trade=0.0,
        )

    @staticmethod
    def _load_strategy(name: str) -> Any:
        from trauto.strategies import load_all_strategies
        registry = load_all_strategies()
        cls = registry.get(name)
        if cls is None:
            return None
        try:
            return cls()
        except Exception:
            return None
