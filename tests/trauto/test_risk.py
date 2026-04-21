"""Tests for GlobalRiskManager — all checks, circuit breaker, emergency stop."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from trauto.core.risk import CircuitBreakerState, GlobalRiskManager, RiskDecision
from trauto.strategies.base import (
    BaseStrategy,
    RiskParams,
    ScheduleType,
    Signal,
    StrategySchedule,
    StrategyStatus,
)
from trauto.core.portfolio import PortfolioState
from trauto.brokers.base import AccountSnapshot


class _EnabledStrategy(BaseStrategy):
    name = "test.enabled"
    broker = "alpaca"
    def get_status(self) -> StrategyStatus:
        return self._base_status()


def _make_signal(action: str = "buy", broker: str = "alpaca", symbol: str = "SPY") -> Signal:
    return Signal(
        strategy_name="test.enabled",
        broker=broker,
        symbol=symbol,
        action=action,
        confidence=0.8,
        price=500.0,
    )


def _make_portfolio(realized_today: float = 0.0, positions: int = 0) -> PortfolioState:
    p = PortfolioState()
    p.accounts["alpaca"] = AccountSnapshot(
        broker="alpaca",
        cash=100_000.0,
        portfolio_value=100_000.0 + realized_today,
        buying_power=100_000.0,
        unrealized_pnl=0.0,
        realized_pnl_today=realized_today,
    )
    p.positions["alpaca"] = [MagicMock(size_usd=1000.0, extra={"strategy": "other.strategy"})
                              for _ in range(positions)]
    return p


class TestGlobalRiskManager:
    def test_emergency_stop_blocks_all(self, tmp_path, monkeypatch):
        monkeypatch.setattr("trauto.core.risk._ENGINE_STATE_PATH", tmp_path / "engine_state.json")
        rm = GlobalRiskManager()
        rm.set_emergency_stop(True)
        strategy = _EnabledStrategy()
        sig = _make_signal()
        portfolio = _make_portfolio()
        decision = rm.check(sig, strategy, portfolio)
        assert not decision.approved
        assert decision.reason == "emergency_stop"

    def test_disabled_strategy_blocked(self, tmp_path, monkeypatch):
        monkeypatch.setattr("trauto.core.risk._ENGINE_STATE_PATH", tmp_path / "engine_state.json")
        rm = GlobalRiskManager()
        strategy = _EnabledStrategy(enabled=False)
        sig = _make_signal()
        portfolio = _make_portfolio()
        decision = rm.check(sig, strategy, portfolio)
        assert not decision.approved
        assert decision.reason == "strategy_disabled"

    def test_global_daily_loss_blocks(self, tmp_path, monkeypatch):
        monkeypatch.setattr("trauto.core.risk._ENGINE_STATE_PATH", tmp_path / "engine_state.json")
        rm = GlobalRiskManager(global_daily_loss_limit=500.0)
        strategy = _EnabledStrategy()
        sig = _make_signal()
        portfolio = _make_portfolio(realized_today=-600.0)
        decision = rm.check(sig, strategy, portfolio)
        assert not decision.approved
        assert decision.reason == "global_daily_loss_exceeded"

    def test_global_max_positions_blocks_buys(self, tmp_path, monkeypatch):
        monkeypatch.setattr("trauto.core.risk._ENGINE_STATE_PATH", tmp_path / "engine_state.json")
        rm = GlobalRiskManager(global_max_positions=2)
        strategy = _EnabledStrategy()
        sig = _make_signal(action="buy")
        portfolio = _make_portfolio(positions=2)
        decision = rm.check(sig, strategy, portfolio)
        assert not decision.approved
        assert decision.reason == "global_max_positions_exceeded"

    def test_dry_run_approved_with_flag(self, tmp_path, monkeypatch):
        monkeypatch.setattr("trauto.core.risk._ENGINE_STATE_PATH", tmp_path / "engine_state.json")
        rm = GlobalRiskManager()
        strategy = _EnabledStrategy(dry_run=True)
        sig = _make_signal()
        portfolio = _make_portfolio()
        decision = rm.check(sig, strategy, portfolio)
        assert decision.approved
        assert decision.dry_run is True

    def test_live_approved(self, tmp_path, monkeypatch):
        monkeypatch.setattr("trauto.core.risk._ENGINE_STATE_PATH", tmp_path / "engine_state.json")
        rm = GlobalRiskManager()
        strategy = _EnabledStrategy(dry_run=False)
        sig = _make_signal()
        portfolio = _make_portfolio()
        decision = rm.check(sig, strategy, portfolio)
        assert decision.approved
        assert decision.dry_run is False


class TestCircuitBreaker:
    def test_trips_after_threshold(self):
        cb = CircuitBreakerState(broker="test")
        for _ in range(2):
            tripped = cb.record_error(3, 60.0, 3)
            assert not tripped
            assert not cb.is_tripped
        tripped = cb.record_error(3, 60.0, 3)
        assert tripped
        assert cb.is_tripped

    def test_auto_resume_after_cooldown(self):
        cb = CircuitBreakerState(broker="test")
        cb.tripped_at = time.monotonic() - 70.0  # 70s ago
        assert cb.is_tripped
        resumed = cb.try_auto_resume(cooldown_sec=60.0)
        assert resumed
        assert not cb.is_tripped

    def test_no_auto_resume_during_cooldown(self):
        cb = CircuitBreakerState(broker="test")
        cb.tripped_at = time.monotonic()  # just tripped
        resumed = cb.try_auto_resume(cooldown_sec=60.0)
        assert not resumed
        assert cb.is_tripped

    def test_manual_resume_required_after_limit(self):
        cb = CircuitBreakerState(broker="test")
        for _ in range(3):
            cb.record_error(1, 60.0, 3)  # each call trips (threshold=1)
            cb.tripped_at = 0.0           # reset so next trip counts
        assert cb.manual_resume_required

    def test_manual_resume_clears_state(self):
        cb = CircuitBreakerState(broker="test")
        cb.tripped_at = time.monotonic()
        cb.manual_resume_required = True
        cb.manual_resume()
        assert not cb.is_tripped
        assert not cb.manual_resume_required

    def test_success_resets_consecutive_errors(self):
        cb = CircuitBreakerState(broker="test")
        cb.consecutive_errors = 2
        cb.record_success()
        assert cb.consecutive_errors == 0


class TestGlobalRiskManagerCircuitBreaker:
    def test_tripped_broker_blocked(self, tmp_path, monkeypatch):
        monkeypatch.setattr("trauto.core.risk._ENGINE_STATE_PATH", tmp_path / "engine_state.json")
        rm = GlobalRiskManager(circuit_breaker_error_threshold=1, circuit_breaker_cooldown_sec=3600)
        rm.record_broker_error("alpaca")  # trips the circuit breaker
        strategy = _EnabledStrategy(dry_run=False)
        sig = _make_signal(broker="alpaca")
        portfolio = _make_portfolio()
        decision = rm.check(sig, strategy, portfolio)
        assert not decision.approved
        assert "circuit_breaker" in decision.reason

    def test_manual_resume_clears_block(self, tmp_path, monkeypatch):
        monkeypatch.setattr("trauto.core.risk._ENGINE_STATE_PATH", tmp_path / "engine_state.json")
        rm = GlobalRiskManager(circuit_breaker_error_threshold=1, circuit_breaker_cooldown_sec=3600)
        rm.record_broker_error("alpaca")
        rm.manual_resume_circuit_breaker("alpaca")
        strategy = _EnabledStrategy(dry_run=False)
        sig = _make_signal(broker="alpaca")
        portfolio = _make_portfolio()
        decision = rm.check(sig, strategy, portfolio)
        assert decision.approved


class TestEmergencyStopPersistence:
    def test_persists_to_disk(self, tmp_path, monkeypatch):
        state_path = tmp_path / "engine_state.json"
        monkeypatch.setattr("trauto.core.risk._ENGINE_STATE_PATH", state_path)
        rm = GlobalRiskManager()
        rm.set_emergency_stop(True)
        assert state_path.exists()
        import json
        data = json.loads(state_path.read_text())
        assert data["emergency_stop"] is True

    def test_loads_from_disk_on_init(self, tmp_path, monkeypatch):
        state_path = tmp_path / "engine_state.json"
        state_path.write_text('{"emergency_stop": true}', encoding="utf-8")
        monkeypatch.setattr("trauto.core.risk._ENGINE_STATE_PATH", state_path)
        rm = GlobalRiskManager()
        assert rm.is_emergency_stop() is True

    def test_clear_persists(self, tmp_path, monkeypatch):
        state_path = tmp_path / "engine_state.json"
        monkeypatch.setattr("trauto.core.risk._ENGINE_STATE_PATH", state_path)
        rm = GlobalRiskManager()
        rm.set_emergency_stop(True)
        rm.set_emergency_stop(False)
        import json
        data = json.loads(state_path.read_text())
        assert data["emergency_stop"] is False
