"""Standalone theta strategy runner — entry point for the theta-runner systemd unit.

Loads env, builds all enabled strategies, then loops forever:
  evaluate → rank → gate → execute → write heartbeat → sleep

Env vars (set in /etc/trauto/env):
    WORKER_DRY_RUN                  bool   default=true   — no real orders
    THETA_TICK_INTERVAL_SECONDS     int    default=60      — sleep between ticks
    THETA_COINBASE_SPOT_ENABLED     bool   default=false   — enable coinbase spot strategy
    THETA_MOMENTUM_ENABLED          bool   default=false   — enable momentum strategy
    THETA_FUNDING_ARB_ENABLED       bool   default=false   — enable funding arb strategy

    Risk limits (passed to GlobalRiskLimits):
    MAX_NOTIONAL_PER_TRADE_USD      float  default=500
    DAILY_NOTIONAL_COINBASE_USD     float  default=2000
    DAILY_NOTIONAL_HL_USD           float  default=500
    MIN_SCORE_THRESHOLD             float  default=0

    Strategy tuning (passed through to strategy constructors):
    SPOT_EDGE_BPS, MOMENTUM_PRODUCT, MOMENTUM_FAST_BARS, MOMENTUM_SLOW_BARS,
    HL_MIN_FUNDING_RATE, HL_MAX_POSITION_USD, TRADE_LOG_DIR
"""
from __future__ import annotations

import logging
import os
import re
import signal
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
LOGGER = logging.getLogger("theta.orchestration.runner_worker")

_SHUTDOWN = False


def _handle_sigterm(signum, frame) -> None:
    global _SHUTDOWN
    LOGGER.info("runner_worker received SIGTERM — finishing current tick then exiting")
    _SHUTDOWN = True


signal.signal(signal.SIGTERM, _handle_sigterm)
signal.signal(signal.SIGINT, _handle_sigterm)


# ---------------------------------------------------------------------------
# Env helpers
# ---------------------------------------------------------------------------

def _load_env_file() -> None:
    """Inject /etc/trauto/env (PEM-safe: skips base64 continuation lines)."""
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


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").lower()
    if raw in ("1", "true", "yes"):
        return True
    if raw in ("0", "false", "no"):
        return False
    return default


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw else default


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


# ---------------------------------------------------------------------------
# Strategy factory
# ---------------------------------------------------------------------------

def _build_strategies() -> list:
    strategies = []

    if _bool_env("THETA_COINBASE_SPOT_ENABLED", False):
        try:
            from theta.strategies.coinbase_spot import CoinbaseSpotEdgeStrategy
            strat = CoinbaseSpotEdgeStrategy()
            strategies.append(strat)
            LOGGER.info("strategy_registered name=%s", strat.name)
        except Exception as exc:
            LOGGER.warning("strategy_load_failed name=coinbase_spot error=%s", exc)
    else:
        LOGGER.info("strategy_disabled name=coinbase_spot (set THETA_COINBASE_SPOT_ENABLED=true to enable)")

    if _bool_env("THETA_MOMENTUM_ENABLED", False):
        try:
            from theta.strategies.momentum import SimpleMomentumStrategy
            strat = SimpleMomentumStrategy()
            strategies.append(strat)
            LOGGER.info("strategy_registered name=%s", strat.name)
        except Exception as exc:
            LOGGER.warning("strategy_load_failed name=momentum error=%s", exc)
    else:
        LOGGER.info("strategy_disabled name=momentum (set THETA_MOMENTUM_ENABLED=true to enable)")

    if _bool_env("THETA_FUNDING_ARB_ENABLED", False):
        try:
            from theta.strategies.funding_arb import FundingArbStrategy
            strat = FundingArbStrategy()
            strategies.append(strat)
            LOGGER.info("strategy_registered name=%s", strat.name)
        except Exception as exc:
            LOGGER.warning("strategy_load_failed name=funding_arb error=%s", exc)
    else:
        LOGGER.info("strategy_disabled name=funding_arb (set THETA_FUNDING_ARB_ENABLED=true to enable)")

    return strategies


def _build_risk_limits():
    from theta.orchestration.runner import GlobalRiskLimits
    return GlobalRiskLimits(
        max_notional_per_trade_usd=_float_env("MAX_NOTIONAL_PER_TRADE_USD", 500.0),
        max_daily_notional_per_exchange={
            "coinbase":    _float_env("DAILY_NOTIONAL_COINBASE_USD", 2_000.0),
            "hyperliquid": _float_env("DAILY_NOTIONAL_HL_USD", 500.0),
        },
        min_score_threshold=_float_env("MIN_SCORE_THRESHOLD", 0.0),
    )


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run() -> int:
    _load_env_file()

    dry_run = _bool_env("WORKER_DRY_RUN", True)
    tick_interval = _int_env("THETA_TICK_INTERVAL_SECONDS", 60)
    mode = "dry_run" if dry_run else "live"

    LOGGER.info(
        "runner_worker_start dry_run=%s tick_interval=%ds",
        dry_run, tick_interval,
    )

    strategies = _build_strategies()
    if not strategies:
        LOGGER.error(
            "no strategies enabled — set at least one of "
            "THETA_COINBASE_SPOT_ENABLED, THETA_MOMENTUM_ENABLED, "
            "THETA_FUNDING_ARB_ENABLED to true in /etc/trauto/env"
        )
        return 1

    from theta.config.basis import BasisConfig
    from theta.orchestration.runner import StrategyRunner
    from theta.orchestration.status_writer import write_runner_status

    cfg = BasisConfig.from_env()
    risk = _build_risk_limits()
    runner = StrategyRunner(strategies=strategies, risk=risk)

    LOGGER.info(
        "runner_worker_ready strategies=%s mode=%s log_dir=%s",
        runner.strategy_names, mode, cfg.log_dir,
    )

    iterations_completed = 0

    while not _SHUTDOWN:
        tick_error: str | None = None
        result = None
        try:
            result = runner.run_once(dry_run=dry_run)
        except Exception as exc:
            LOGGER.error("runner_tick_error error=%s", exc)
            tick_error = str(exc)

        iterations_completed += 1

        if tick_error is not None:
            last_result = "error"
        elif result is None:
            last_result = "no_opportunity"
        elif dry_run:
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

        LOGGER.info(
            "runner_tick_done iteration=%d result=%s strategy=%s",
            iterations_completed, last_result, selected or "none",
        )

        if _SHUTDOWN:
            break

        LOGGER.debug("sleeping %ds before next tick", tick_interval)
        # Sleep in short segments so SIGTERM is handled promptly.
        deadline = time.monotonic() + tick_interval
        while not _SHUTDOWN and time.monotonic() < deadline:
            time.sleep(min(1.0, deadline - time.monotonic()))

    LOGGER.info("runner_worker_shutdown iterations_completed=%d", iterations_completed)
    return 0


if __name__ == "__main__":
    sys.exit(run())
