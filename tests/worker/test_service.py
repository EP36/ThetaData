"""Tests for worker loop safety and duplicate-cycle protections."""

from __future__ import annotations

from src.config.deployment import DeploymentSettings
from src.persistence import DatabaseStore, PersistenceRepository
from src.worker.service import TradingWorker


def build_repository(db_path) -> PersistenceRepository:
    return PersistenceRepository(
        store=DatabaseStore(database_url=f"sqlite+pysqlite:///{db_path}")
    )


def test_worker_stays_idle_when_paper_trading_disabled(tmp_path) -> None:
    db_path = tmp_path / "theta.db"
    settings = DeploymentSettings(
        database_url=f"sqlite+pysqlite:///{db_path}",
        worker_enable_trading=False,
        paper_trading_enabled=False,
        app_env="development",
        strict_env_validation=False,
    )
    repository = build_repository(db_path)
    worker = TradingWorker(settings=settings, repository=repository)

    worker.run_once()

    heartbeat = repository.get_worker_heartbeat(settings.worker_name)
    assert heartbeat is not None
    assert heartbeat["status"] == "idle"
    assert repository.recent_runs(limit=5) == []


def test_worker_duplicate_cycle_is_skipped(tmp_path) -> None:
    db_path = tmp_path / "theta.db"
    settings = DeploymentSettings(
        database_url=f"sqlite+pysqlite:///{db_path}",
        worker_enable_trading=True,
        paper_trading_enabled=True,
        worker_name="integration-worker",
        worker_timeframe="1d",
        worker_order_quantity=1.0,
        app_env="development",
        strict_env_validation=False,
    )
    repository = build_repository(db_path)
    worker = TradingWorker(settings=settings, repository=repository)

    worker.run_once()
    worker.run_once()

    runs = repository.recent_runs(limit=10)
    assert len(runs) == 1
