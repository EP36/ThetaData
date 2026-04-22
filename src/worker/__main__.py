"""Run the background trading worker process.

Starts two concurrent loops:
  1. Alpaca Breakout Momentum worker  (main thread, blocking)
  2. Polymarket scanner + monitor + AI analyst  (daemon thread)

If Polymarket fails to start or crashes at any point the error is logged
and the Alpaca worker continues unaffected.
"""

from __future__ import annotations

import logging
import os
import threading

from src.config.deployment import DeploymentSettings
from src.observability.logging import configure_logging
from src.persistence import DatabaseStore, PersistenceRepository
from src.worker.service import TradingWorker

LOGGER = logging.getLogger("theta.worker.main")


def _check_poly_credentials() -> bool:
    """Return True if all required Polymarket credentials are present in env."""
    required = ("POLY_API_KEY", "POLY_API_SECRET", "POLY_PASSPHRASE", "POLY_PRIVATE_KEY")
    present = all(os.getenv(k, "").strip() for k in required)
    if present:
        LOGGER.info("poly_credentials=configured dry_run=%s", os.getenv("POLY_DRY_RUN", "true"))
    else:
        missing = [k for k in required if not os.getenv(k, "").strip()]
        LOGGER.warning("poly_credentials=MISSING missing_keys=%s — Polymarket loop will not start", missing)
    return present


def _run_polymarket_loop() -> None:
    """Target for the Polymarket daemon thread. Never propagates exceptions."""
    try:
        from src.polymarket.__main__ import main as poly_main
        LOGGER.info("polymarket_thread_starting")
        poly_main()
    except Exception as exc:
        LOGGER.error("polymarket_thread_crashed error=%s — Alpaca worker continues", exc)


def main() -> None:
    configure_logging()

    LOGGER.info("worker_entrypoint_starting")

    # --- Polymarket daemon thread (optional, credential-gated) ---
    if _check_poly_credentials():
        poly_thread = threading.Thread(
            target=_run_polymarket_loop,
            name="polymarket-loop",
            daemon=True,   # dies automatically when main thread exits
        )
        poly_thread.start()
        LOGGER.info("polymarket_thread_started thread_id=%d", poly_thread.ident or 0)
    else:
        LOGGER.info("polymarket_thread_skipped reason=missing_credentials")

    # --- Alpaca worker (main thread, blocks until process exits) ---
    settings = DeploymentSettings.from_env()
    repository = PersistenceRepository(
        store=DatabaseStore(database_url=settings.database_url)
    )
    worker = TradingWorker(settings=settings, repository=repository)
    worker.run_forever()


if __name__ == "__main__":
    main()
