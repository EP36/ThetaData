"""Comprehensive backtest sweep: 4 strategies × 7 symbols × 3 timeframes = 84 combinations."""
from __future__ import annotations

import os
import sys
import logging
from pathlib import Path

# Suppress noisy logs during sweep
logging.disable(logging.CRITICAL)

sys.path.insert(0, str(Path(__file__).parent))

from src.cli.services import run_backtest

STRATEGIES = [
    "moving_average_crossover",
    "rsi_mean_reversion",
    "breakout_momentum",
    "mean_reversion_scalp",
]
SYMBOLS = ["SPY", "QQQ", "NVDA", "TSLA", "AMD", "AAPL", "META"]
TIMEFRAMES = ["1d", "4h", "1h"]

START = "2024-01-01"
END = "2024-12-31"
CACHE_DIR = Path("data/cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

results = []
total = len(STRATEGIES) * len(SYMBOLS) * len(TIMEFRAMES)
done = 0

for strategy in STRATEGIES:
    for symbol in SYMBOLS:
        for timeframe in TIMEFRAMES:
            done += 1
            tag = f"{strategy}/{symbol}/{timeframe}"
            print(f"[{done:>3}/{total}] {tag} ...", end="", flush=True)
            try:
                result = run_backtest(
                    symbol=symbol,
                    timeframe=timeframe,
                    strategy_name=strategy,
                    strategy_params={},
                    start=START,
                    end=END,
                    cache_dir=CACHE_DIR,
                    trade_log_path=CACHE_DIR / f"{symbol}_{strategy}_{timeframe}_sweep.csv",
                    initial_capital=100_000.0,
                    position_size_pct=1.0,
                    fixed_fee=1.0,
                    slippage_pct=0.0005,
                    stop_loss_pct=None,
                    take_profit_pct=None,
                    trailing_stop_pct=None,
                    max_position_size=0.25,
                    max_daily_loss=2000.0,
                    max_open_positions=3,
                    force_refresh=False,
                )
                m = result.metrics
                row = {
                    "strategy": strategy,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "total_return": m.get("total_return", float("nan")),
                    "sharpe": m.get("sharpe_ratio", m.get("sharpe", float("nan"))),
                    "max_drawdown": m.get("max_drawdown", float("nan")),
                    "win_rate": m.get("win_rate", float("nan")),
                    "profit_factor": m.get("profit_factor", float("nan")),
                    "num_trades": m.get("num_trades", m.get("total_trades", 0)),
                }
                results.append(row)
                print(f" sharpe={row['sharpe']:.3f} ret={row['total_return']:.1%} trades={row['num_trades']:.0f}")
            except Exception as exc:
                print(f" ERROR: {exc}")
                results.append({
                    "strategy": strategy, "symbol": symbol, "timeframe": timeframe,
                    "total_return": float("nan"), "sharpe": float("nan"),
                    "max_drawdown": float("nan"), "win_rate": float("nan"),
                    "profit_factor": float("nan"), "num_trades": 0,
                    "error": str(exc),
                })

# Sort by sharpe descending (NaN last)
import math
results_sorted = sorted(
    results,
    key=lambda r: r["sharpe"] if not math.isnan(r["sharpe"]) else float("-inf"),
    reverse=True,
)

print("\n" + "=" * 90)
print("TOP 10 COMBINATIONS BY SHARPE RATIO")
print("=" * 90)
header = f"{'Strategy':<30} {'Symbol':<6} {'TF':<4} {'Return':>8} {'Sharpe':>7} {'Drawdown':>9} {'WinRate':>8} {'PF':>6} {'Trades':>7}"
print(header)
print("-" * 90)

for row in results_sorted[:10]:
    ret_s = f"{row['total_return']:.1%}" if not math.isnan(row['total_return']) else "  N/A"
    sh_s = f"{row['sharpe']:.3f}" if not math.isnan(row['sharpe']) else "  N/A"
    dd_s = f"{row['max_drawdown']:.1%}" if not math.isnan(row['max_drawdown']) else "   N/A"
    wr_s = f"{row['win_rate']:.1%}" if not math.isnan(row['win_rate']) else "  N/A"
    pf_s = f"{row['profit_factor']:.2f}" if not math.isnan(row['profit_factor']) else " N/A"
    print(
        f"{row['strategy']:<30} {row['symbol']:<6} {row['timeframe']:<4} "
        f"{ret_s:>8} {sh_s:>7} {dd_s:>9} {wr_s:>8} {pf_s:>6} {row['num_trades']:>7.0f}"
    )

# Flag combinations meeting all 4 criteria
CRITERIA = {
    "total_return > 5%": lambda r: r["total_return"] > 0.05,
    "sharpe > 0.5": lambda r: r["sharpe"] > 0.5,
    "win_rate > 52%": lambda r: r["win_rate"] > 0.52,
    "max_drawdown < 15%": lambda r: abs(r["max_drawdown"]) < 0.15,
}

stars = [
    r for r in results
    if all(
        not math.isnan(r.get(k.split()[0].split(">")[0].split("<")[0], float("nan")))
        and fn(r)
        for k, fn in CRITERIA.items()
    )
]

# Simpler filter
stars = [
    r for r in results
    if (
        not math.isnan(r["total_return"]) and r["total_return"] > 0.05
        and not math.isnan(r["sharpe"]) and r["sharpe"] > 0.5
        and not math.isnan(r["win_rate"]) and r["win_rate"] > 0.52
        and not math.isnan(r["max_drawdown"]) and abs(r["max_drawdown"]) < 0.15
    )
]

print("\n" + "=" * 90)
print(f"STAR COMBINATIONS (all 4 criteria met): {len(stars)}")
print("  Criteria: total_return > 5%  AND  sharpe > 0.5  AND  win_rate > 52%  AND  |max_drawdown| < 15%")
print("=" * 90)
if stars:
    print(header)
    print("-" * 90)
    for row in sorted(stars, key=lambda r: r["sharpe"], reverse=True):
        ret_s = f"{row['total_return']:.1%}"
        sh_s = f"{row['sharpe']:.3f}"
        dd_s = f"{row['max_drawdown']:.1%}"
        wr_s = f"{row['win_rate']:.1%}"
        pf_s = f"{row['profit_factor']:.2f}" if not math.isnan(row['profit_factor']) else " N/A"
        print(
            f"{row['strategy']:<30} {row['symbol']:<6} {row['timeframe']:<4} "
            f"{ret_s:>8} {sh_s:>7} {dd_s:>9} {wr_s:>8} {pf_s:>6} {row['num_trades']:>7.0f}"
        )
else:
    print("  (none met all 4 criteria)")

print(f"\nTotal combinations run: {len(results)}")
print(f"Errors: {sum(1 for r in results if 'error' in r)}")
