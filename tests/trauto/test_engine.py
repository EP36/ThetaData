"""Tests for the trading engine tick cycle."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trauto.core.engine import TradingEngine
from trauto.core.risk import GlobalRiskManager
from trauto.strategies.base import (
    BaseStrategy,
    Signal,
    StrategySchedule,
    StrategyStatus,
)
from trauto.brokers.base import (
    AccountSnapshot,
    BrokerInterface,
    Order,
    OrderResult,
    OrderStatus,
    Position,
    Quote,
    Bar,
)


class _MockBroker(BrokerInterface):
    def __init__(self, name_: str) -> None:
        self._name = name_
        self.placed_orders: list[Order] = []

    @property
    def name(self) -> str:
        return self._name

    async def get_account(self) -> AccountSnapshot:
        return AccountSnapshot(
            broker=self._name, cash=10000.0, portfolio_value=10000.0,
            buying_power=10000.0, unrealized_pnl=0.0, realized_pnl_today=0.0,
        )

    async def get_positions(self) -> list[Position]:
        return []

    async def place_order(self, order: Order) -> OrderResult:
        self.placed_orders.append(order)
        return OrderResult(
            broker=self._name, symbol=order.symbol, side=order.side,
            quantity=order.quantity, price=order.price,
            order_id="mock_001", status="filled",
            filled_qty=order.quantity, filled_price=order.price,
        )

    async def cancel_order(self, order_id: str) -> bool:
        return True

    async def get_order_status(self, order_id: str) -> OrderStatus:
        return OrderStatus(order_id=order_id, status="filled")

    async def get_bars(self, symbol, timeframe, start, end, limit=1000) -> list[Bar]:
        return []

    async def get_quote(self, symbol: str) -> Quote:
        return Quote(symbol=symbol, bid=99.0, ask=101.0)

    async def is_market_open(self) -> bool:
        return True


class _SignalStrategy(BaseStrategy):
    name = "test.signal"
    broker = "alpaca"
    tick_count = 0

    def __init__(self, signal_on_first_tick: bool = False, **kwargs):
        super().__init__(**kwargs)
        self._emit_on_first = signal_on_first_tick
        self._first = True

    async def on_tick(self, market_data) -> None:
        self.tick_count += 1
        if self._emit_on_first and self._first:
            self._first = False
            self.emit_signal(Signal(
                strategy_name=self.name,
                broker="alpaca",
                symbol="SPY",
                action="buy",
                confidence=0.9,
                price=500.0,
                size_usd=1000.0,
            ))

    def get_status(self) -> StrategyStatus:
        return self._base_status()


class TestEngineRegistration:
    def test_register_broker(self, tmp_path, monkeypatch):
        monkeypatch.setattr("trauto.core.risk._ENGINE_STATE_PATH", tmp_path / "engine_state.json")
        monkeypatch.setattr("trauto.core.engine._STRATEGY_CONFIG_PATH", tmp_path / "strategy_config.json")
        engine = TradingEngine()
        broker = _MockBroker("alpaca")
        engine.register_broker(broker)
        assert "alpaca" in engine.executor.brokers

    def test_register_strategy(self, tmp_path, monkeypatch):
        monkeypatch.setattr("trauto.core.risk._ENGINE_STATE_PATH", tmp_path / "engine_state.json")
        monkeypatch.setattr("trauto.core.engine._STRATEGY_CONFIG_PATH", tmp_path / "strategy_config.json")
        engine = TradingEngine()
        strategy = _SignalStrategy()
        engine.register_strategy(strategy)
        assert "test.signal" in engine._strategies


class TestEngineGetStats:
    def test_stats_shape(self, tmp_path, monkeypatch):
        monkeypatch.setattr("trauto.core.risk._ENGINE_STATE_PATH", tmp_path / "engine_state.json")
        monkeypatch.setattr("trauto.core.engine._STRATEGY_CONFIG_PATH", tmp_path / "strategy_config.json")
        engine = TradingEngine()
        stats = engine.get_stats()
        assert stats.strategies_loaded == 0
        assert stats.tick_count == 0
        assert stats.emergency_stop is False

    def test_stats_after_strategy(self, tmp_path, monkeypatch):
        monkeypatch.setattr("trauto.core.risk._ENGINE_STATE_PATH", tmp_path / "engine_state.json")
        monkeypatch.setattr("trauto.core.engine._STRATEGY_CONFIG_PATH", tmp_path / "strategy_config.json")
        engine = TradingEngine()
        engine.register_strategy(_SignalStrategy())
        stats = engine.get_stats()
        assert stats.strategies_loaded == 1
        assert stats.strategies_enabled == 1


class TestEngineEmergencyStop:
    def test_emergency_stop_persists(self, tmp_path, monkeypatch):
        state_path = tmp_path / "engine_state.json"
        monkeypatch.setattr("trauto.core.risk._ENGINE_STATE_PATH", state_path)
        monkeypatch.setattr("trauto.core.engine._STRATEGY_CONFIG_PATH", tmp_path / "strategy_config.json")
        engine = TradingEngine()
        asyncio.get_event_loop().run_until_complete(engine.stop(emergency=True))
        assert state_path.exists()
        data = json.loads(state_path.read_text())
        assert data["emergency_stop"] is True
        stats = engine.get_stats()
        assert stats.emergency_stop is True

    def test_resume_clears_stop(self, tmp_path, monkeypatch):
        state_path = tmp_path / "engine_state.json"
        monkeypatch.setattr("trauto.core.risk._ENGINE_STATE_PATH", state_path)
        monkeypatch.setattr("trauto.core.engine._STRATEGY_CONFIG_PATH", tmp_path / "strategy_config.json")
        engine = TradingEngine()
        asyncio.get_event_loop().run_until_complete(engine.stop(emergency=True))
        asyncio.get_event_loop().run_until_complete(engine.resume())
        stats = engine.get_stats()
        assert stats.emergency_stop is False


class TestEngineStrategyConfig:
    def test_update_strategy(self, tmp_path, monkeypatch):
        monkeypatch.setattr("trauto.core.risk._ENGINE_STATE_PATH", tmp_path / "engine_state.json")
        config_path = tmp_path / "strategy_config.json"
        monkeypatch.setattr("trauto.core.engine._STRATEGY_CONFIG_PATH", config_path)
        engine = TradingEngine()
        strategy = _SignalStrategy()
        engine.register_strategy(strategy)
        engine.update_strategy("test.signal", {"enabled": False, "dry_run": False})
        assert strategy.enabled is False
        assert strategy.dry_run is False
        # Check persisted
        data = json.loads(config_path.read_text())
        assert data["strategies"]["test.signal"]["enabled"] is False

    def test_update_unknown_strategy_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr("trauto.core.risk._ENGINE_STATE_PATH", tmp_path / "engine_state.json")
        monkeypatch.setattr("trauto.core.engine._STRATEGY_CONFIG_PATH", tmp_path / "strategy_config.json")
        engine = TradingEngine()
        with pytest.raises(KeyError):
            engine.update_strategy("nonexistent.strategy", {"enabled": False})

    def test_persisted_config_applied_on_register(self, tmp_path, monkeypatch):
        state_path = tmp_path / "engine_state.json"
        config_path = tmp_path / "strategy_config.json"
        monkeypatch.setattr("trauto.core.risk._ENGINE_STATE_PATH", state_path)
        monkeypatch.setattr("trauto.core.engine._STRATEGY_CONFIG_PATH", config_path)

        config_path.write_text(json.dumps({
            "strategies": {
                "test.signal": {
                    "enabled": False,
                    "dry_run": False,
                    "capital_allocation_pct": 25.0,
                    "max_positions": 3,
                }
            }
        }), encoding="utf-8")

        engine = TradingEngine()
        strategy = _SignalStrategy()
        engine.register_strategy(strategy)
        assert strategy.enabled is False
        assert strategy.capital_allocation_pct == 25.0
        assert strategy.max_positions == 3


class TestEngineTickSignalCollection:
    def test_signals_collected_from_strategy(self, tmp_path, monkeypatch):
        monkeypatch.setattr("trauto.core.risk._ENGINE_STATE_PATH", tmp_path / "engine_state.json")
        monkeypatch.setattr("trauto.core.engine._STRATEGY_CONFIG_PATH", tmp_path / "strategy_config.json")
        engine = TradingEngine()
        broker = _MockBroker("alpaca")
        engine.register_broker(broker)

        strategy = _SignalStrategy(signal_on_first_tick=True, dry_run=True)
        engine.register_strategy(strategy)

        # Run one tick manually
        asyncio.get_event_loop().run_until_complete(engine._tick())
        assert strategy.tick_count == 1
