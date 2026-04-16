"""Tests for worker loop safety and duplicate-cycle protections."""

from __future__ import annotations

import pandas as pd

from src.config.deployment import DeploymentSettings
from src.execution.models import Position
from src.persistence import DatabaseStore, PersistenceRepository
from src.persistence.repository import PortfolioSnapshot
from src.worker.service import TradingWorker


def build_repository(db_path) -> PersistenceRepository:
    return PersistenceRepository(
        store=DatabaseStore(database_url=f"sqlite+pysqlite:///{db_path}")
    )


class LoaderStub:
    """Minimal loader stub returning preconfigured frames by symbol."""

    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self.frames = frames

    def load(
        self,
        symbol: str,
        timeframe: str,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        return self.frames[symbol].copy()


def make_frame(
    close_values: list[float],
    volume_values: list[float],
) -> pd.DataFrame:
    """Create deterministic OHLCV frames for worker observability tests."""
    index = pd.date_range("2026-01-01", periods=len(close_values), freq="D")
    close = pd.Series(close_values, index=index, dtype=float)
    return pd.DataFrame(
        {
            "open": close * 0.995,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": pd.Series(volume_values, index=index, dtype=float),
        },
        index=index,
    )


def test_worker_stays_idle_when_paper_trading_disabled(tmp_path) -> None:
    db_path = tmp_path / "trauto.db"
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


def test_worker_duplicate_cycle_is_skipped(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "trauto.db"
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

    monkeypatch.setattr(
        TradingWorker,
        "_heartbeat_cycle_key",
        lambda self, _: "1d:2026-01-01T09:30:00Z",
    )

    worker.run_once()
    worker.run_once()

    runs = repository.recent_runs(limit=10)
    worker_runs = [row for row in runs if str(row.get("service") or "").startswith("worker:")]
    assert len(worker_runs) == 1

    duplicate_events = repository.recent_log_events(
        limit=20,
        event="worker_universe_cycle_duplicate_detected",
    )
    assert duplicate_events
    payload = dict(duplicate_events[0].get("payload") or {})
    assert payload.get("duplicate_validity") == "valid"


def test_worker_symbol_cycle_key_varies_by_poll_bucket(tmp_path) -> None:
    db_path = tmp_path / "trauto.db"
    settings = DeploymentSettings(
        database_url=f"sqlite+pysqlite:///{db_path}",
        worker_enable_trading=True,
        paper_trading_enabled=True,
        worker_name="cycle-key-worker",
        worker_timeframe="1d",
        worker_poll_seconds=60,
        app_env="development",
        strict_env_validation=False,
    )
    repository = build_repository(db_path)
    worker = TradingWorker(settings=settings, repository=repository)

    first_timestamp = pd.Timestamp("2026-01-01T10:00:00Z")
    second_timestamp = pd.Timestamp("2026-01-01T10:01:00Z")

    heartbeat_one = worker._heartbeat_cycle_key(first_timestamp)
    heartbeat_two = worker._heartbeat_cycle_key(second_timestamp)
    assert heartbeat_one != heartbeat_two

    cycle_key_one = worker._cycle_key("NFLX", heartbeat_one)
    cycle_key_two = worker._cycle_key("NFLX", heartbeat_two)
    assert cycle_key_one != cycle_key_two


def test_worker_processes_configured_universe_symbols(tmp_path) -> None:
    db_path = tmp_path / "trauto.db"
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
    db_path = tmp_path / "trauto.db"
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


def test_worker_logs_scan_rejection_summary_when_no_shortlist(tmp_path) -> None:
    db_path = tmp_path / "trauto.db"
    settings = DeploymentSettings(
        database_url=f"sqlite+pysqlite:///{db_path}",
        worker_enable_trading=True,
        paper_trading_enabled=True,
        worker_name="no-shortlist-worker",
        worker_symbols=("AAA", "BBB"),
        worker_universe_mode="static",
        worker_timeframe="1d",
        worker_order_quantity=1.0,
        min_price=5.0,
        min_avg_volume=1_000.0,
        app_env="development",
        strict_env_validation=False,
    )
    repository = build_repository(db_path)
    worker = TradingWorker(settings=settings, repository=repository)
    stub = LoaderStub(
        {
            "AAA": make_frame([1.0, 1.1, 1.2], [100_000, 100_000, 100_000]),
            "BBB": make_frame([10.0, 10.1, 10.2], [100.0, 120.0, 140.0]),
        }
    )
    worker.loader = stub
    worker.universe_scanner.loader = stub

    worker.run_once()

    filtered_events = repository.recent_log_events(limit=10, event="worker_symbol_filtered")
    filtered_by_symbol = {
        str(event.get("payload", {}).get("symbol")): dict(event.get("payload") or {})
        for event in filtered_events
    }
    assert filtered_by_symbol["AAA"]["reasons"] == ["below_min_price"]
    assert filtered_by_symbol["AAA"]["rejection_reasons"] == ["below_min_price"]
    assert filtered_by_symbol["AAA"]["reason_groups"] == ["risk_blocked"]
    assert filtered_by_symbol["AAA"]["latest_bar_timestamp"] is not None
    assert filtered_by_symbol["AAA"]["now_timestamp"] is not None
    assert filtered_by_symbol["AAA"]["latest_bar_age_minutes"] is None
    assert filtered_by_symbol["AAA"]["stale_threshold_minutes"] is None
    assert filtered_by_symbol["AAA"]["min_avg_volume_threshold"] == 1_000.0
    assert filtered_by_symbol["AAA"]["actual_avg_volume"] == 100_000.0
    assert filtered_by_symbol["AAA"]["min_relative_volume_threshold"] == 0.0
    assert filtered_by_symbol["AAA"]["actual_relative_volume"] == 1.0
    assert filtered_by_symbol["AAA"]["market_session_state"] == "not_applicable"
    assert filtered_by_symbol["BBB"]["reasons"] == ["below_min_avg_volume"]
    assert filtered_by_symbol["BBB"]["reason_groups"] == ["insufficient_volume_confirmation"]

    summary_events = repository.recent_log_events(
        limit=5,
        event="worker_universe_rejection_summary",
    )
    assert summary_events
    summary_payload = dict(summary_events[0].get("payload") or {})
    assert summary_payload["rejection_reason_counts"] == {
        "below_min_avg_volume": 1,
        "below_min_price": 1,
    }
    assert summary_payload["rejection_reason_group_counts"] == {
        "insufficient_volume_confirmation": 1,
        "risk_blocked": 1,
    }

    no_shortlist_events = repository.recent_log_events(limit=5, event="worker_no_shortlist")
    assert no_shortlist_events
    no_shortlist_payload = dict(no_shortlist_events[0].get("payload") or {})
    assert no_shortlist_payload["filtered_out_reason_counts"] == {
        "below_min_avg_volume": 1,
        "below_min_price": 1,
    }


def test_worker_enforces_symbol_strategy_lock_reason(tmp_path) -> None:
    db_path = tmp_path / "trauto.db"
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
    db_path = tmp_path / "trauto.db"
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
    selection = dict(details.get("selection") or {})
    candidate_rows = selection.get("candidates", [])
    assert all(
        "paper_trading_disabled" not in (candidate.get("reasons", []) if isinstance(candidate, dict) else [])
        for candidate in candidate_rows
    )

    fills = repository.recent_fills(limit=20, run_service_prefix="worker:")
    assert fills == []


def test_worker_startup_warmup_bypasses_min_recent_trade_gate(tmp_path) -> None:
    db_path = tmp_path / "trauto.db"
    settings = DeploymentSettings(
        database_url=f"sqlite+pysqlite:///{db_path}",
        worker_enable_trading=True,
        paper_trading_enabled=False,
        worker_dry_run=True,
        worker_name="warmup-worker",
        worker_symbols=("SPY",),
        worker_timeframe="1d",
        selection_min_recent_trades=10,
        worker_startup_warmup_cycles=5,
        app_env="development",
        strict_env_validation=False,
    )
    repository = build_repository(db_path)
    worker = TradingWorker(settings=settings, repository=repository)

    worker.run_once()

    runs = repository.recent_runs(limit=5)
    assert runs
    details = dict(runs[0].get("details") or {})
    selection = dict(details.get("selection") or {})
    candidates = selection.get("candidates", [])
    assert all(
        "insufficient_recent_trades" not in (candidate.get("reasons", []) if isinstance(candidate, dict) else [])
        for candidate in candidates
    )


def test_worker_without_warmup_enforces_min_recent_trade_gate(tmp_path) -> None:
    db_path = tmp_path / "trauto.db"
    settings = DeploymentSettings(
        database_url=f"sqlite+pysqlite:///{db_path}",
        worker_enable_trading=True,
        paper_trading_enabled=False,
        worker_dry_run=True,
        worker_name="no-warmup-worker",
        worker_symbols=("SPY",),
        worker_timeframe="1d",
        selection_min_recent_trades=10,
        worker_startup_warmup_cycles=0,
        app_env="development",
        strict_env_validation=False,
    )
    repository = build_repository(db_path)
    worker = TradingWorker(settings=settings, repository=repository)

    worker.run_once()

    runs = repository.recent_runs(limit=5)
    assert runs
    details = dict(runs[0].get("details") or {})
    selection = dict(details.get("selection") or {})
    candidates = selection.get("candidates", [])
    assert any(
        "insufficient_recent_trades" in (candidate.get("reasons", []) if isinstance(candidate, dict) else [])
        for candidate in candidates
    )
