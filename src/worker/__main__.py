"""Run the background trading worker process for one explicit venue."""

from __future__ import annotations

import logging

from src.config.deployment import DeploymentSettings
from src.observability.logging import configure_logging
from src.persistence import DatabaseStore, PersistenceRepository
from src.worker.service import TradingWorker

LOGGER = logging.getLogger("theta.worker.main")


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


def _log_runtime_mode(settings: DeploymentSettings) -> None:
    """Emit the startup mode/venue/adapter selection for auditability."""
    LOGGER.info(
        "worker_runtime_mode active_trading_mode=%s active_venue=%s "
        "execution_adapter=%s paper_trading=%s worker_dry_run=%s "
        "live_trading=%s worker_enable_trading=%s poly_dry_run=%s "
        "signal_provider=%s data_provider=%s alpaca_trading_mode=%s "
        "poly_trading_mode=%s",
        settings.trading_mode,
        settings.trading_venue,
        settings.execution_adapter,
        settings.paper_trading_enabled,
        settings.worker_dry_run,
        settings.live_trading_enabled,
        settings.worker_enable_trading,
        settings.polymarket_dry_run,
        settings.signal_provider,
        settings.data_provider,
        settings.alpaca_trading_mode,
        settings.poly_trading_mode,
    )


def _run_polymarket_worker(settings: DeploymentSettings) -> None:
    """Run the Polymarket scanner/monitor loop as the only active worker."""
    if not settings.worker_enable_trading:
        LOGGER.info(
            "polymarket_worker_skipped reason=worker_enable_trading_false"
        )
        return
    if settings.poly_trading_mode == "disabled":
        LOGGER.info("polymarket_worker_skipped reason=poly_trading_mode_disabled")
        return
    if not settings.polymarket_credentials_configured:
        LOGGER.warning(
            "polymarket_worker_skipped reason=missing_credentials missing_keys=%s",
            list(settings.missing_polymarket_credentials),
        )
        return

    from src.polymarket.__main__ import main as polymarket_main

    LOGGER.info("polymarket_worker_starting")
    polymarket_main()


def _run_equities_worker(settings: DeploymentSettings) -> None:
    """Run the existing equities-oriented worker as the only active worker."""
    repository = PersistenceRepository(
        store=DatabaseStore(database_url=settings.database_url)
    )

    # Seed strategy configs before the loop so the correct state is in the DB
    # from the very first cycle. moving_average_crossover targets META and QQQ
    # on a 1d timeframe in paper trading mode (PAPER_TRADING=true).
    _seed_strategy_configs(repository)

    worker = TradingWorker(settings=settings, repository=repository)
    worker.run_forever()


def _run_worker_for_settings(settings: DeploymentSettings) -> None:
    """Dispatch to exactly one venue-specific worker."""
    _log_runtime_mode(settings)
    if settings.trading_venue == "polymarket":
        _run_polymarket_worker(settings)
        return
    _run_equities_worker(settings)


def _log_outbound_ip() -> None:
    """Log the server's outbound IP on startup for geo-verification."""
    try:
        import httpx
        r = httpx.get("https://api.ipify.org?format=json", timeout=5)
        ip = r.json().get("ip", "unknown")
        LOGGER.info("outbound_ip=%s region=hetzner-helsinki", ip)
    except Exception as exc:
        LOGGER.debug("outbound_ip_check_failed error=%s", exc)


def main() -> None:
    configure_logging()

    LOGGER.info("worker_entrypoint_starting")
    _log_outbound_ip()
    settings = DeploymentSettings.from_env()
    _run_worker_for_settings(settings)


if __name__ == "__main__":
    main()
