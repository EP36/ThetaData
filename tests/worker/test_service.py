"""Tests for worker loop safety and duplicate-cycle protections."""

from __future__ import annotations

from src.config.deployment import DeploymentSettings
from src.execution.models import Position
from src.persistence import DatabaseStore, PersistenceRepository
from src.persistence.repository import PortfolioSnapshot
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


def test_worker_processes_configured_universe_symbols(tmp_path) -> None:
    db_path = tmp_path / "theta.db"
    settings = DeploymentSettings(
        database_url=f"sqlite+pysqlite:///{db_path}",
        worker_enable_trading=True,
        paper_trading_enabled=True,
        worker_name="integration-worker",
        worker_symbols=("SPY", "QQQ"),
        worker_timeframe="1d",
        worker_order_quantity=1.0,
        app_env="development",
        strict_env_validation=False,
    )
    repository = build_repository(db_path)
    worker = TradingWorker(settings=settings, repository=repository)

    worker.run_once()

    runs = repository.recent_runs(limit=10)
    symbols = {str(run.get("symbol")) for run in runs}
    assert "SPY" in symbols
    assert "QQQ" in symbols


def test_worker_evaluates_only_shortlisted_symbols(tmp_path) -> None:
    db_path = tmp_path / "theta.db"
    settings = DeploymentSettings(
        database_url=f"sqlite+pysqlite:///{db_path}",
        worker_enable_trading=True,
        paper_trading_enabled=True,
        worker_name="shortlist-worker",
        worker_symbols=("SPY", "QQQ", "AAPL"),
        worker_universe_mode="static",
        worker_max_candidates=1,
        worker_timeframe="1d",
        worker_order_quantity=1.0,
        app_env="development",
        strict_env_validation=False,
    )
    repository = build_repository(db_path)
    worker = TradingWorker(settings=settings, repository=repository)

    worker.run_once()

    runs = repository.recent_runs(limit=10)
    worker_runs = [row for row in runs if str(row.get("service") or "").startswith("worker:")]
    assert len(worker_runs) == 1


def test_worker_enforces_symbol_strategy_lock_reason(tmp_path) -> None:
    db_path = tmp_path / "theta.db"
    settings = DeploymentSettings(
        database_url=f"sqlite+pysqlite:///{db_path}",
        worker_enable_trading=True,
        paper_trading_enabled=True,
        worker_name="lock-worker",
        worker_symbols=("SPY",),
        worker_timeframe="1d",
        worker_order_quantity=1.0,
        app_env="development",
        strict_env_validation=False,
    )
    repository = build_repository(db_path)
    worker = TradingWorker(settings=settings, repository=repository)

    repository.save_portfolio_snapshot(
        PortfolioSnapshot(
            cash=100_000.0,
            day_start_equity=100_000.0,
            peak_equity=100_000.0,
            positions={
                "SPY": Position(
                    symbol="SPY",
                    quantity=1.0,
                    avg_price=100.0,
                    realized_pnl=0.0,
                    unrealized_pnl=0.0,
                )
            },
        )
    )
    repository.upsert_symbol_strategy_lock(
        symbol="SPY",
        strategy="moving_average_crossover",
        run_id="bootstrap-run",
        reason="test_lock",
    )

    worker.run_once()

    runs = repository.recent_runs(limit=5)
    assert runs
    details = dict(runs[0].get("details") or {})
    selection = dict(details.get("selection") or {})
    candidates = selection.get("candidates", [])
    lock_reason = "symbol_locked_by_active_strategy:moving_average_crossover"
    assert any(
        isinstance(candidate, dict)
        and candidate.get("strategy") != "moving_average_crossover"
        and lock_reason in candidate.get("reasons", [])
        for candidate in candidates
    )


def test_worker_dry_run_evaluates_without_submitting_orders(tmp_path) -> None:
    db_path = tmp_path / "theta.db"
    settings = DeploymentSettings(
        database_url=f"sqlite+pysqlite:///{db_path}",
        worker_enable_trading=True,
        paper_trading_enabled=False,
        worker_dry_run=True,
        worker_name="dry-run-worker",
        worker_symbols=("SPY",),
        worker_timeframe="1d",
        worker_order_quantity=1.0,
        app_env="development",
        strict_env_validation=False,
    )
    repository = build_repository(db_path)
    worker = TradingWorker(settings=settings, repository=repository)

    worker.run_once()

    runs = repository.recent_runs(limit=10)
    worker_runs = [row for row in runs if str(row.get("service") or "").startswith("worker:")]
    assert worker_runs
    details = dict(worker_runs[0].get("details") or {})
    assert details.get("action") in {"no_order", "dry_run_order_skipped", "duplicate_order_skipped"}

    fills = repository.recent_fills(limit=20, run_service_prefix="worker:")
    assert fills == []
