"""Integration-style tests for additive worker trade controls."""

from __future__ import annotations

import pandas as pd

from src.config.deployment import DeploymentSettings
from src.persistence import DatabaseStore, PersistenceRepository
from src.selection.selector import SelectionConfig, StrategySelector
from src.worker.service import TradingWorker


class _LoaderStub:
    """Deterministic loader stub for worker integration tests."""

    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame

    def load(self, symbol: str, timeframe: str, force_refresh: bool = False) -> pd.DataFrame:
        return self._frame


def _build_repository(db_path) -> PersistenceRepository:
    repository = PersistenceRepository(
        store=DatabaseStore(database_url=f"sqlite+pysqlite:///{db_path}")
    )
    repository.initialize(starting_cash=100_000.0)
    return repository


def _configure_strategy_rows(repository: PersistenceRepository) -> None:
    repository.upsert_strategy_config(
        name="moving_average_crossover",
        status="disabled",
        parameters={"short_window": 2, "long_window": 4},
    )
    repository.upsert_strategy_config(
        name="breakout_momentum",
        status="disabled",
        parameters={},
    )
    repository.upsert_strategy_config(
        name="breakout_momentum_intraday",
        status="enabled",
        parameters={
            "lookback_period": 2,
            "breakout_threshold": 1.0005,
            "volume_multiplier": 1.0,
            "stop_loss_pct": 0.02,
            "trailing_stop_pct": 0.02,
        },
    )
    repository.upsert_strategy_config(
        name="rsi_mean_reversion",
        status="disabled",
        parameters={},
    )
    repository.upsert_strategy_config(
        name="vwap_mean_reversion",
        status="disabled",
        parameters={},
    )
    for name in (
        "opening_range_breakout",
        "vwap_reclaim_intraday",
        "pullback_trend_continuation",
        "mean_reversion_scalp",
    ):
        repository.upsert_strategy_config(name=name, status="disabled", parameters={})


def _settings(db_path) -> DeploymentSettings:
    return DeploymentSettings(
        database_url=f"sqlite+pysqlite:///{db_path}",
        worker_enable_trading=True,
        paper_trading_enabled=True,
        worker_dry_run=False,
        worker_name="trade-controls-worker",
        worker_symbols=("SPY",),
        worker_timeframe="1h",
        worker_order_quantity=1.0,
        allow_after_hours=True,
        selection_min_recent_trades=0,
        worker_startup_warmup_cycles=0,
        enable_strategy_gating=True,
        enable_position_sizing=True,
        enable_risk_caps=True,
        risk_per_trade_pct=0.005,
        max_concurrent_positions=3,
        max_portfolio_exposure_pct=0.30,
        daily_drawdown_limit_pct=0.02,
        app_env="development",
        strict_env_validation=False,
    )


def _approved_breakout_data() -> pd.DataFrame:
    end = pd.Timestamp.utcnow().floor("h")
    index = pd.date_range(end=end, periods=5, freq="1h")
    return pd.DataFrame(
        {
            "open": [96.0, 97.0, 98.0, 99.0, 100.0],
            "high": [96.0, 97.0, 98.0, 99.0, 100.0],
            "low": [95.0, 96.0, 97.0, 98.0, 99.0],
            "close": [96.0, 97.0, 98.0, 99.0, 100.0],
            "volume": [200_000.0, 200_000.0, 200_000.0, 200_000.0, 500_000.0],
        },
        index=index,
    )


def _sideways_breakout_data() -> pd.DataFrame:
    end = pd.Timestamp.utcnow().floor("h")
    index = pd.date_range(end=end, periods=5, freq="1h")
    return pd.DataFrame(
        {
            "open": [100.0, 100.0, 100.0, 100.0, 100.1],
            "high": [100.0, 100.0, 100.0, 100.0, 100.1],
            "low": [99.9, 99.9, 99.9, 99.9, 100.0],
            "close": [100.0, 100.0, 100.0, 100.0, 100.1],
            "volume": [200_000.0, 200_000.0, 200_000.0, 200_000.0, 500_000.0],
        },
        index=index,
    )


def test_worker_executes_sized_trade_when_gate_and_risk_allow(
    tmp_path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "trauto.db"
    repository = _build_repository(db_path)
    _configure_strategy_rows(repository)
    worker = TradingWorker(settings=_settings(db_path), repository=repository)
    regular_context = worker._session_context(pd.Timestamp("2026-04-16T15:00:00Z"))
    monkeypatch.setattr(
        TradingWorker,
        "_session_context",
        lambda self, _: regular_context,
    )
    worker.selector = StrategySelector(
        SelectionConfig(min_recent_trades=0, min_score_threshold=-1.0)
    )
    worker.loader = _LoaderStub(_approved_breakout_data())
    worker.universe_scanner.loader = worker.loader

    worker.run_once()

    fills = repository.recent_fills(limit=5, run_service_prefix="worker:")
    assert len(fills) == 1
    assert fills[0]["strategy"] == "breakout_momentum_intraday"
    assert fills[0]["quantity"] == 250.0

    sized_events = repository.recent_log_events(limit=5, event="trade_intent_sized")
    assert sized_events
    payload = dict(sized_events[0].get("payload") or {})
    assert payload.get("quantity") == 250


def test_worker_blocks_trade_before_execution_when_regime_gate_rejects(
    tmp_path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "trauto.db"
    repository = _build_repository(db_path)
    _configure_strategy_rows(repository)
    worker = TradingWorker(settings=_settings(db_path), repository=repository)
    regular_context = worker._session_context(pd.Timestamp("2026-04-16T15:00:00Z"))
    monkeypatch.setattr(
        TradingWorker,
        "_session_context",
        lambda self, _: regular_context,
    )
    worker.selector = StrategySelector(
        SelectionConfig(min_recent_trades=0, min_score_threshold=-1.0)
    )
    worker.loader = _LoaderStub(_sideways_breakout_data())
    worker.universe_scanner.loader = worker.loader

    worker.run_once()

    fills = repository.recent_fills(limit=5, run_service_prefix="worker:")
    assert fills == []

    rejection_events = repository.recent_log_events(limit=10, event="trade_intent_rejected")
    assert rejection_events
    payload = dict(rejection_events[0].get("payload") or {})
    assert payload.get("stage") == "strategy_gate"
    assert payload.get("reasons") == ["breakout_blocked_in_sideways_regime"]

    runs = repository.recent_runs(limit=5)
    assert runs
    details = dict(runs[0].get("details") or {})
    assert details.get("action") == "no_order"
