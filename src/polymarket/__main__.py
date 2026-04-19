"""Polymarket arb scanner — standalone entrypoint.

Run:
    python -m src.polymarket

Environment variables must be set (see src/polymarket/README.md or .env.example).
"""

from __future__ import annotations

import logging
import time

from src.observability.logging import configure_logging
from src.polymarket.config import PolymarketConfig
from src.polymarket.runner import scan_and_execute

LOGGER = logging.getLogger("theta.polymarket.main")


def main() -> None:
    configure_logging()
    config = PolymarketConfig.from_env()

    LOGGER.info(
        "polymarket_scanner_starting interval_sec=%d min_edge_pct=%.2f "
        "dry_run=%s max_trade_usdc=%.2f",
        config.scan_interval_sec,
        config.min_edge_pct,
        config.dry_run,
        config.max_trade_usdc,
    )

    while True:
        try:
            scan_and_execute(config)
        except Exception as exc:
            LOGGER.error("polymarket_scan_error error=%s", exc)

        LOGGER.info("polymarket_scan_sleeping seconds=%d", config.scan_interval_sec)
        time.sleep(config.scan_interval_sec)


if __name__ == "__main__":
    main()
