"""Tests for persistence repository behavior and idempotency safeguards."""

from __future__ import annotations

import pandas as pd

from src.execution.models import Fill, Order
from src.persistence import DatabaseStore, PersistenceRepository


def test_global_kill_switch_and_strategy_config_persistence(tmp_path) -> None:
    db_path = tmp_path / "theta.db"
    repository = PersistenceRepository(
        store=DatabaseStore(database_url=f"sqlite+pysqlite:///{db_path}")
    )
    repository.initialize(starting_cash=50_000.0)

    assert repository.get_global_kill_switch() is False
    repository.set_global_kill_switch(True, reason="test")
    assert repository.get_global_kill_switch() is True

    repository.upsert_strategy_config(
        name="moving_average_crossover",
        status="enabled",
        parameters={"short_window": 10, "long_window": 30},
    )
    loaded = repository.load_strategy_configs()
    assert loaded["moving_average_crossover"]["status"] == "enabled"
    assert loaded["moving_average_crossover"]["parameters"]["short_window"] == 10


def test_run_and_order_idempotency(tmp_path) -> None:
    db_path = tmp_path / "theta.db"
    repository = PersistenceRepository(
        store=DatabaseStore(database_url=f"sqlite+pysqlite:///{db_path}")
    )
    repository.initialize(starting_cash=50_000.0)

    started = repository.start_run(
        run_id="run-1",
        service="worker:test",
        cycle_key="SPY:1d:2026-01-01",
    )
    duplicate = repository.start_run(
        run_id="run-2",
        service="worker:test",
        cycle_key="SPY:1d:2026-01-01",
    )
    assert started is True
    assert duplicate is False

    order = Order(
        symbol="SPY",
        side="BUY",
        quantity=1.0,
        price=100.0,
        timestamp=pd.Timestamp("2026-01-01T10:00:00Z"),
    )
    dedupe_key = repository.compute_order_dedupe_key("SPY:1d:2026-01-01", order)
    first_insert = repository.record_order(
        order=order,
        source="worker",
        run_id="run-1",
        dedupe_key=dedupe_key,
    )
    second_insert = repository.record_order(
        order=order,
        source="worker",
        run_id="run-1",
        dedupe_key=dedupe_key,
    )
    assert first_insert is True
    assert second_insert is False


def test_recent_fills_returns_only_persisted_fill_rows(tmp_path) -> None:
    db_path = tmp_path / "theta.db"
    repository = PersistenceRepository(
        store=DatabaseStore(database_url=f"sqlite+pysqlite:///{db_path}")
    )
    repository.initialize(starting_cash=50_000.0)

    assert repository.recent_fills() == []

    repository.start_run(
        run_id="run-fill-1",
        service="worker:test",
        strategy="moving_average_crossover",
    )
    repository.record_fill(
        Fill(
            order_id="order-1",
            symbol="SPY",
            side="BUY",
            quantity=2.0,
            price=500.0,
            timestamp=pd.Timestamp("2026-01-01T10:00:00Z"),
            notional=1_000.0,
        ),
        run_id="run-fill-1",
    )

    rows = repository.recent_fills(limit=10)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "SPY"
    assert rows[0]["strategy"] == "moving_average_crossover"
