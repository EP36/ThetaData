"""Minimal backtest skeleton for theta strategies.

Lets you replay a Strategy against a sequence of OHLCV bars offline,
without touching live exchanges.  The signal generation (evaluate_opportunity)
is replayed bar-by-bar; execution is simulated at bar close price.

Usage (once data plumbing is wired):
    from theta.backtest.simple_runner import backtest, Bar
    from theta.strategies.momentum import SimpleMomentumStrategy

    bars = load_bars("ETH-USD", "2024-01-01", "2024-12-31")
    result = backtest(SimpleMomentumStrategy(), bars)
    print(result)

Status: SKELETON — Bar injection into strategy evaluate() is not yet wired.
The interface is defined so downstream code can be written against it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from theta.strategies.base import Strategy


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class Bar:
    """A single OHLCV bar."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    product_id: str = ""


@dataclass
class BacktestTrade:
    bar_index: int
    timestamp: datetime
    side: str
    notional_usd: float
    fill_price: float
    expected_edge_bps: float
    strategy_name: str


@dataclass
class BacktestResult:
    strategy_name: str
    bars_tested: int
    trades: list[BacktestTrade] = field(default_factory=list)

    # Aggregate stats (populated by _compute_stats).
    total_trades: int = 0
    gross_pnl_usd: float = 0.0
    total_fees_usd: float = 0.0
    net_pnl_usd: float = 0.0
    win_rate: float = 0.0

    def __str__(self) -> str:
        return (
            f"BacktestResult strategy={self.strategy_name} "
            f"bars={self.bars_tested} trades={self.total_trades} "
            f"net_pnl=${self.net_pnl_usd:.2f} win_rate={self.win_rate:.1%}"
        )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def backtest(strategy: "Strategy", bars: list[Bar]) -> BacktestResult:
    """Replay strategy over historical bars.

    NOTE: evaluate_opportunity() is called with the bar's timestamp but the
    strategy's internal price-fetching (e.g. get_candles) is NOT injected
    with historical data yet — that requires wiring a historical data provider.
    This skeleton iterates bars and records structure; real price injection
    is a TODO.

    Args:
        strategy: Any object satisfying the Strategy Protocol.
        bars:     Chronological list of OHLCV bars.

    Returns:
        BacktestResult with trade log and aggregate stats.
    """
    result = BacktestResult(
        strategy_name=strategy.name,
        bars_tested=len(bars),
    )

    for i, bar in enumerate(bars):
        # TODO: inject bar prices into strategy before calling evaluate
        # (requires a historical data provider or strategy.set_price_context(bar))
        planned = strategy.evaluate_opportunity(bar.timestamp)
        if planned is None:
            continue

        # Simulate fill at bar close.
        from theta.config.basis import BasisConfig
        cfg = BasisConfig()
        fee_usd = planned.notional_usd * cfg.cb_taker_fee_bps / 10_000.0
        slip_usd = planned.notional_usd * cfg.slippage_buffer_bps / 10_000.0

        result.trades.append(BacktestTrade(
            bar_index=i,
            timestamp=bar.timestamp,
            side=planned.side,
            notional_usd=planned.notional_usd,
            fill_price=bar.close,
            expected_edge_bps=planned.expected_edge_bps,
            strategy_name=strategy.name,
        ))

    # --- Compute aggregate stats ---
    result.total_trades = len(result.trades)
    if result.trades:
        # Placeholder P&L: assume expected_edge_bps of each trade is the actual
        # return.  Real P&L requires next-bar price comparison.
        for t in result.trades:
            gross = t.notional_usd * t.expected_edge_bps / 10_000.0
            fee = t.notional_usd * (BasisConfig().round_trip_cost_bps) / 10_000.0
            result.gross_pnl_usd += gross
            result.total_fees_usd += fee
            result.net_pnl_usd += gross - fee
        wins = sum(1 for t in result.trades if t.expected_edge_bps > 0)
        result.win_rate = wins / result.total_trades

    return result
