"""Backtest results formatter — computes metrics and writes JSON output."""

from __future__ import annotations

import json
import math
import statistics
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

_RISK_FREE_RATE = 0.05  # annual
_RESULTS_DIR = Path("data/backtest_results")


@dataclass
class TradeRecord:
    """One completed backtest trade."""
    symbol: str
    strategy: str
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    pnl_pct: float
    entry_at: str
    exit_at: str
    hold_bars: int


@dataclass
class BacktestMetrics:
    """Computed performance metrics for a completed backtest."""
    run_id: str
    strategy_name: str
    start_date: str
    end_date: str
    initial_capital: float
    final_capital: float
    total_return_pct: float
    win_rate: float
    max_drawdown_pct: float
    sharpe_ratio: float
    total_trades: int
    avg_hold_bars: float
    best_trade_pnl: float
    worst_trade_pnl: float
    avg_pnl_per_trade: float
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    trades: list[dict[str, Any]] = field(default_factory=list)
    per_strategy: dict[str, Any] = field(default_factory=dict)
    generated_at: str = field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())


def compute_metrics(
    trades: list[TradeRecord],
    equity_curve: list[float],
    initial_capital: float,
    strategy_name: str,
    start_date: str,
    end_date: str,
    risk_free_rate: float = _RISK_FREE_RATE,
    run_id: str = "",
) -> BacktestMetrics:
    """Compute all performance metrics from raw trades and equity curve."""
    run_id = run_id or str(uuid.uuid4())[:8]

    final_capital = equity_curve[-1] if equity_curve else initial_capital
    total_return_pct = (final_capital - initial_capital) / initial_capital * 100.0 if initial_capital > 0 else 0.0

    wins = [t for t in trades if t.pnl > 0]
    win_rate = len(wins) / len(trades) if trades else 0.0

    max_drawdown_pct = _max_drawdown(equity_curve)
    sharpe = _sharpe_ratio(equity_curve, risk_free_rate)

    avg_hold = statistics.mean([t.hold_bars for t in trades]) if trades else 0.0
    best_pnl = max((t.pnl for t in trades), default=0.0)
    worst_pnl = min((t.pnl for t in trades), default=0.0)
    avg_pnl = statistics.mean([t.pnl for t in trades]) if trades else 0.0

    curve_points = [
        {"bar": i, "equity": round(v, 2)}
        for i, v in enumerate(equity_curve)
    ]

    return BacktestMetrics(
        run_id=run_id,
        strategy_name=strategy_name,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        final_capital=round(final_capital, 2),
        total_return_pct=round(total_return_pct, 4),
        win_rate=round(win_rate, 4),
        max_drawdown_pct=round(max_drawdown_pct, 4),
        sharpe_ratio=round(sharpe, 4),
        total_trades=len(trades),
        avg_hold_bars=round(avg_hold, 1),
        best_trade_pnl=round(best_pnl, 4),
        worst_trade_pnl=round(worst_pnl, 4),
        avg_pnl_per_trade=round(avg_pnl, 4),
        equity_curve=curve_points,
        trades=[asdict(t) for t in trades],
    )


def write_results(metrics: BacktestMetrics) -> Path:
    """Write metrics to data/backtest_results/<run_id>.json."""
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = _RESULTS_DIR / f"{metrics.run_id}.json"
    path.write_text(json.dumps(asdict(metrics), indent=2), encoding="utf-8")
    return path


def list_results() -> list[dict[str, Any]]:
    """Return summary list of all backtest runs (most recent first)."""
    if not _RESULTS_DIR.exists():
        return []
    results = []
    for f in sorted(_RESULTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            results.append({
                "run_id": data.get("run_id", f.stem),
                "strategy_name": data.get("strategy_name", ""),
                "start_date": data.get("start_date", ""),
                "end_date": data.get("end_date", ""),
                "total_return_pct": data.get("total_return_pct", 0),
                "win_rate": data.get("win_rate", 0),
                "total_trades": data.get("total_trades", 0),
                "sharpe_ratio": data.get("sharpe_ratio", 0),
                "generated_at": data.get("generated_at", ""),
            })
        except Exception:
            pass
    return results


def read_result(run_id: str) -> dict[str, Any] | None:
    """Return full result dict for a run_id, or None if not found."""
    path = _RESULTS_DIR / f"{run_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------

def _max_drawdown(equity: list[float]) -> float:
    """Maximum drawdown as a percentage of peak equity."""
    if len(equity) < 2:
        return 0.0
    peak = equity[0]
    max_dd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
    return max_dd * 100.0


def _sharpe_ratio(equity: list[float], risk_free_rate: float = 0.05) -> float:
    """Annualized Sharpe ratio (daily returns basis)."""
    if len(equity) < 2:
        return 0.0
    returns = [
        (equity[i] - equity[i - 1]) / equity[i - 1]
        for i in range(1, len(equity))
        if equity[i - 1] > 0
    ]
    if not returns:
        return 0.0
    mean_r = statistics.mean(returns)
    std_r = statistics.stdev(returns) if len(returns) > 1 else 0.0
    if std_r == 0:
        return 0.0
    daily_rf = (1 + risk_free_rate) ** (1 / 252) - 1
    return (mean_r - daily_rf) / std_r * math.sqrt(252)
