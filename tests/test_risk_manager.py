"""Tests for risk manager."""

from __future__ import annotations

import pandas as pd

from src.risk.manager import RiskManager


def test_risk_manager_clips_position_and_activates_kill_switch() -> None:
    manager = RiskManager(max_position_size=0.5, max_daily_loss=100.0)
    ts = pd.Timestamp("2025-01-01")

    allowed = manager.enforce(
        timestamp=ts,
        target_position=1.0,
        day_start_equity=10_000.0,
        current_equity=9_950.0,
    )
    assert allowed == 0.5

    killed = manager.enforce(
        timestamp=ts,
        target_position=0.5,
        day_start_equity=10_000.0,
        current_equity=9_880.0,
    )
    assert killed == 0.0
    assert manager.kill_switch_enabled is True
    assert manager.kill_switch_triggered_at == ts

    after_kill = manager.enforce(
        timestamp=ts,
        target_position=0.5,
        day_start_equity=10_000.0,
        current_equity=10_100.0,
    )
    assert after_kill == 0.0

    manager.reset_kill_switch()
    assert manager.kill_switch_triggered_at is None
