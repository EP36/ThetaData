#!/usr/bin/env python3
"""Run the theta strategy orchestration loop.

Evaluates all registered strategies each iteration, ranks by expected edge,
applies global risk limits, and executes the best opportunity.

Usage:
    source .venv/bin/activate

    # Dry-run: evaluate + log decisions, no real orders:
    python -m scripts.run_strategies --dry-run

    # 3 iterations, 30s apart:
    python -m scripts.run_strategies --dry-run --iterations 3 --sleep 30

    # Inject a synthetic edge to test the spot strategy fires in dry-run:
    python -m scripts.run_strategies --dry-run --inject-edge-bps 200

    # Live (real orders, be careful!):
    python -m scripts.run_strategies --iterations 1

    # Show registered strategies and exit:
    python -m scripts.run_strategies --list

Required env vars:
    COINBASE_API_KEY, COINBASE_API_SECRET   — for Coinbase spot strategies
    HL_PRIVATE_KEY, HL_WALLET              — for Hyperliquid funding arb

Optional env vars (strategy tuning):
    SPOT_EDGE_BPS                  — static edge signal for coinbase_spot strategy
    MOMENTUM_PRODUCT               — product for momentum strategy (default ETH-USD)
    MOMENTUM_FAST_BARS / SLOW_BARS — momentum window sizes
    HL_MIN_FUNDING_RATE            — funding rate threshold for arb
    MAX_NOTIONAL_PER_TRADE_USD     — global per-trade cap (default 500)
    DAILY_NOTIONAL_COINBASE_USD    — daily budget for Coinbase (default 2000)
    DAILY_NOTIONAL_HL_USD          — daily budget for Hyperliquid (default 500)
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
LOGGER = logging.getLogger("theta.scripts.run_strategies")


# ---------------------------------------------------------------------------
# Env loading (PEM-safe, identical to test_coinbase_trade.py)
# ---------------------------------------------------------------------------

def _load_env_file() -> None:
    """Inject /etc/trauto/env into os.environ (shell env takes precedence).

    Skips lines that don't look like ENV_VAR=value so multi-line PEM values
    (e.g. COINBASE_API_SECRET) don't corrupt the parse.
    """
    _env_key = re.compile(r'^[A-Z_][A-Z0-9_]*$')
    try:
        with open("/etc/trauto/env") as fh:
            for line in fh:
                line = line.strip()
                if "=" not in line or line.startswith("#"):
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                if not _env_key.match(k):
                    continue
                v = v.strip()
                if k not in os.environ:
                    os.environ[k] = v
    except FileNotFoundError:
        LOGGER.debug("no /etc/trauto/env — using shell environment only")


# ---------------------------------------------------------------------------
# Strategy factory
# ---------------------------------------------------------------------------

def _build_strategies(inject_edge_bps: float | None):
    """Instantiate and return all configured strategies."""
    strategies = []

    # 1. Coinbase spot edge strategy.
    try:
        from theta.strategies.coinbase_spot import CoinbaseSpotEdgeStrategy
        strat = CoinbaseSpotEdgeStrategy(
            signal_edge_bps=inject_edge_bps,     # None → reads SPOT_EDGE_BPS from env
            test_notional_usd=10.0 if inject_edge_bps else None,
        )
        strategies.append(strat)
        LOGGER.info("strategy_registered name=%s", strat.name)
    except Exception as exc:
        LOGGER.warning("strategy_load_failed name=coinbase_spot error=%s", exc)

    # 2. Momentum strategy.
    try:
        from theta.strategies.momentum import SimpleMomentumStrategy
        strat = SimpleMomentumStrategy()
        strategies.append(strat)
        LOGGER.info("strategy_registered name=%s", strat.name)
    except Exception as exc:
        LOGGER.warning("strategy_load_failed name=momentum error=%s", exc)

    # 3. Funding arb strategy (requires HL credentials for execution).
    try:
        from theta.strategies.funding_arb import FundingArbStrategy
        strat = FundingArbStrategy()
        strategies.append(strat)
        LOGGER.info("strategy_registered name=%s", strat.name)
    except Exception as exc:
        LOGGER.warning("strategy_load_failed name=funding_arb error=%s", exc)

    return strategies


def _build_risk_limits():
    from theta.orchestration.runner import GlobalRiskLimits
    return GlobalRiskLimits(
        max_notional_per_trade_usd=float(
            os.getenv("MAX_NOTIONAL_PER_TRADE_USD", "500")
        ),
        max_daily_notional_per_exchange={
            "coinbase":    float(os.getenv("DAILY_NOTIONAL_COINBASE_USD", "2000")),
            "hyperliquid": float(os.getenv("DAILY_NOTIONAL_HL_USD", "500")),
        },
        min_score_threshold=float(os.getenv("MIN_SCORE_THRESHOLD", "0")),
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run theta strategy orchestration loop",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run", action="store_true", dest="dry_run",
        help="Evaluate strategies and log decisions without sending real orders.",
    )
    parser.add_argument(
        "--iterations", type=int, default=1,
        help="Number of runner ticks to execute (default: 1).",
    )
    parser.add_argument(
        "--sleep", type=float, default=0.0,
        help="Seconds to sleep between iterations (default: 0).",
    )
    parser.add_argument(
        "--inject-edge-bps", type=float, default=None, dest="inject_edge_bps",
        help=(
            "Override expected_edge_bps for the Coinbase spot strategy.  "
            "Set above hurdle (~150) to force it to propose a trade in dry-run."
        ),
    )
    parser.add_argument(
        "--list", action="store_true",
        help="Print registered strategy names and exit.",
    )
    args = parser.parse_args()

    _load_env_file()

    # Late imports after env is loaded.
    try:
        from theta.orchestration.runner import StrategyRunner
    except ImportError as exc:
        LOGGER.error("import_failed error=%s", exc)
        return 1

    strategies = _build_strategies(args.inject_edge_bps)
    if not strategies:
        LOGGER.error("no strategies loaded — aborting")
        return 1

    if args.list:
        print("\nRegistered strategies:")
        for s in strategies:
            print(f"  {s.name}")
        print()
        return 0

    from theta.config.basis import BasisConfig
    from theta.orchestration.status_writer import write_runner_status

    cfg = BasisConfig.from_env()
    mode = "dry_run" if args.dry_run else "live"

    risk = _build_risk_limits()
    runner = StrategyRunner(strategies=strategies, risk=risk)

    LOGGER.info(
        "run_strategies_start strategies=%s iterations=%d sleep=%.1fs "
        "dry_run=%s inject_edge_bps=%s",
        runner.strategy_names, args.iterations, args.sleep,
        args.dry_run, args.inject_edge_bps,
    )

    iterations_completed = 0

    for i in range(1, args.iterations + 1):
        LOGGER.info("iteration %d/%d", i, args.iterations)
        tick_error: str | None = None
        result = None
        try:
            result = runner.run_once(dry_run=args.dry_run)
        except Exception as exc:
            LOGGER.error("runner_tick_error iteration=%d error=%s", i, exc)
            tick_error = str(exc)

        iterations_completed += 1

        # Derive last_result label from outcome.
        if tick_error is not None:
            last_result = "error"
        elif result is None:
            last_result = "no_opportunity"
        elif args.dry_run:
            last_result = "dry_run_would_execute" if result.success else "failed"
        else:
            last_result = "executed" if result.success else "failed"

        selected = result.strategy_name if result is not None else None

        write_runner_status(
            cfg.log_dir,
            mode=mode,
            strategies_evaluated=runner.strategy_names,
            iterations_completed=iterations_completed,
            selected_strategy=selected,
            last_result=last_result,
            last_error=tick_error or (result.error if result and not result.success else None),
        )

        if result is None and tick_error is None:
            LOGGER.info("iteration %d result=no_trade", i)
        elif result is not None:
            LOGGER.info(
                "iteration %d result=%s strategy=%s "
                "order_id=%s client_order_id=%s",
                i, last_result, result.strategy_name,
                result.order_id, result.client_order_id,
            )

        if i < args.iterations and args.sleep > 0:
            LOGGER.info("sleeping %.1fs before next iteration", args.sleep)
            time.sleep(args.sleep)

    LOGGER.info("run_strategies_done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
