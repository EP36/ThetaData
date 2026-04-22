"""Run the background trading worker process.

Starts two concurrent loops:
  1. Alpaca multi-strategy worker  (main thread, blocking)
  2. Polymarket scanner + monitor + AI analyst  (daemon thread)

Active strategies (seeded at startup):
  - moving_average_crossover  enabled  short_window=20 long_window=50  (META, QQQ, 1d)
  - breakout_momentum         enabled  (default params, all universe symbols)

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


_MAC_STRATEGY = "moving_average_crossover"
_MAC_PARAMS: dict[str, object] = {"short_window": 20, "long_window": 50}

# Strategies that must be enabled on every worker restart regardless of DB state.
# Breakout momentum is enabled by default (no DB override needed) so it is not listed here.
_REQUIRED_ENABLED_STRATEGIES: tuple[tuple[str, dict[str, object]], ...] = (
    (_MAC_STRATEGY, _MAC_PARAMS),
)


def _seed_strategy_configs(repository: PersistenceRepository) -> None:
    """Ensure required strategies are active before the worker loop starts.

    Only strategies listed in _REQUIRED_ENABLED_STRATEGIES are touched.
    All other strategy configs are left exactly as the DB has them.
    """
    for strategy_name, params in _REQUIRED_ENABLED_STRATEGIES:
        repository.upsert_strategy_config(
            name=strategy_name,
            status="enabled",
            parameters=params,
        )
        LOGGER.info(
            "strategy_seeded name=%s status=enabled params=%s",
            strategy_name,
            params,
        )


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

    # Seed strategy configs before the loop so the correct state is in the DB
    # from the very first cycle. moving_average_crossover targets META and QQQ
    # on a 1d timeframe in paper trading mode (PAPER_TRADING=true).
    _seed_strategy_configs(repository)

    worker = TradingWorker(settings=settings, repository=repository)
    worker.run_forever()


if __name__ == "__main__":
    main()
