"""Polymarket arb scanner — standalone entrypoint.

Run:
    python -m src.polymarket

Environment variables must be set (see src/polymarket/README.md or .env.example).
"""

from __future__ import annotations

import logging
import os
import time

from src.dashboard.aggregator import is_poly_paused
from src.observability.logging import configure_logging
from src.polymarket.client import ClobClient
from src.polymarket.config import PolymarketConfig
from src.polymarket.feedback import load_feedback_records
from src.polymarket.monitor import monitor_positions
from src.polymarket.positions import make_ledger
from src.polymarket.runner import scan_and_execute
from src.polymarket.tuner import check_minimum_data, propose_tuning, write_proposal

LOGGER = logging.getLogger("theta.polymarket.main")

_TUNING_INTERVAL_HOURS = float(os.getenv("POLY_TUNING_INTERVAL_HOURS", "168"))
_SIGNAL_PARAMS_PATH = os.getenv("POLY_SIGNAL_PARAMS_PATH", "polymarket/signal_params.json")
_TUNER_PROPOSAL_PATH = "polymarket/signal_params_proposed.json"


def _run_tuning_cycle(config: PolymarketConfig) -> None:
    records = load_feedback_records(
        days=30,
        positions_path=config.positions_path,
        log_dir=config.poly_log_dir,
    )
    ok, reason = check_minimum_data(records)
    if not ok:
        LOGGER.info("polymarket_tuning_skipped reason=%s", reason)
        return
    result = propose_tuning(records, days=30, params_path=_SIGNAL_PARAMS_PATH)
    if not result.proposed_changes:
        LOGGER.info("polymarket_tuning_no_changes trade_count=%d", result.trade_count)
        return
    write_proposal(result, _TUNER_PROPOSAL_PATH)
    LOGGER.info(
        "polymarket_tuning_proposal_written changes=%d trade_count=%d",
        len(result.proposed_changes),
        result.trade_count,
    )


def main() -> None:
    configure_logging()
    config = PolymarketConfig.from_env()

    LOGGER.info(
        "polymarket_scanner_starting interval_sec=%d monitor_interval_sec=%d "
        "min_edge_pct=%.2f dry_run=%s max_trade_usdc=%.2f",
        config.scan_interval_sec,
        config.monitor_interval_sec,
        config.min_edge_pct,
        config.dry_run,
        config.max_trade_usdc,
    )

    client = ClobClient(config=config)
    ledger = make_ledger(config.positions_path)
    last_monitor_time = 0.0
    last_tuning_time = 0.0

    while True:
        if is_poly_paused():
            LOGGER.info("polymarket_scan_skipped reason=dashboard_pause_flag")
        else:
            try:
                scan_and_execute(config)
            except Exception as exc:
                LOGGER.error("polymarket_scan_error error=%s", exc)

        now = time.monotonic()
        if now - last_monitor_time >= config.monitor_interval_sec:
            try:
                monitor_positions(config, client, ledger)
            except Exception as exc:
                LOGGER.error("polymarket_monitor_error error=%s", exc)
            last_monitor_time = time.monotonic()

        now = time.monotonic()
        if now - last_tuning_time >= _TUNING_INTERVAL_HOURS * 3600:
            try:
                _run_tuning_cycle(config)
            except Exception as exc:
                LOGGER.error("polymarket_tuning_error error=%s", exc)
            last_tuning_time = time.monotonic()

        LOGGER.info("polymarket_scan_sleeping seconds=%d", config.scan_interval_sec)
        time.sleep(config.scan_interval_sec)


if __name__ == "__main__":
    main()
