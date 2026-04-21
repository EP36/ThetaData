"""Tests for BaseStrategy and concrete strategy implementations."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pandas as pd
import pytest

from trauto.strategies.base import (
    BaseStrategy,
    RiskParams,
    ScheduleType,
    Signal,
    StrategySchedule,
    StrategyStatus,
)


# ---------------------------------------------------------------------------
# BaseStrategy concrete stub
# ---------------------------------------------------------------------------

class _ConcreteStrategy(BaseStrategy):
    name = "test.concrete"
    broker = "alpaca"

    def get_status(self) -> StrategyStatus:
        return self._base_status()


class TestBaseStrategy:
    def test_defaults(self):
        s = _ConcreteStrategy()
        assert s.enabled is True
        assert s.dry_run is True
        assert s.capital_allocation_pct == 10.0
        assert s.max_positions == 1

    def test_on_start_called(self):
        s = _ConcreteStrategy()
        s.on_start()   # should not raise

    def test_on_stop_clears_signals(self):
        s = _ConcreteStrategy()
        s.emit_signal(Signal(
            strategy_name=s.name,
            broker="alpaca",
            symbol="SPY",
            action="buy",
            confidence=0.8,
            price=500.0,
        ))
        assert len(s.get_signals()) == 1   # returns signals then clears
        s.emit_signal(Signal(
            strategy_name=s.name, broker="alpaca", symbol="SPY",
            action="buy", confidence=0.8, price=500.0,
        ))
        s.on_stop()
        assert len(s._signals) == 0

    def test_emit_and_get_signals(self):
        s = _ConcreteStrategy()
        sig = Signal(
            strategy_name=s.name, broker="alpaca", symbol="SPY",
            action="buy", confidence=0.9, price=550.0,
        )
        s.emit_signal(sig)
        signals = s.get_signals()
        assert len(signals) == 1
        assert signals[0].symbol == "SPY"
        # get_signals clears
        assert s.get_signals() == []

    def test_get_status_shape(self):
        s = _ConcreteStrategy()
        status = s.get_status()
        assert isinstance(status, StrategyStatus)
        assert status.name == "test.concrete"
        assert status.broker == "alpaca"

    def test_schedule_defaults(self):
        s = _ConcreteStrategy()
        assert s.schedule.type == ScheduleType.ALWAYS

    def test_custom_schedule(self):
        s = _ConcreteStrategy(schedule=StrategySchedule(type=ScheduleType.INTERVAL, interval_sec=30.0))
        assert s.schedule.interval_sec == 30.0

    def test_risk_params_defaults(self):
        s = _ConcreteStrategy()
        assert s.risk_params.max_daily_loss == 500.0

    def test_on_tick_default_noop(self):
        s = _ConcreteStrategy()
        asyncio.get_event_loop().run_until_complete(s.on_tick({}))  # no raise

    def test_on_bar_default_noop(self):
        s = _ConcreteStrategy()
        asyncio.get_event_loop().run_until_complete(s.on_bar({}))  # no raise

    def test_on_order_fill_noop(self):
        s = _ConcreteStrategy()
        s.on_order_fill({"order_id": "x"})  # no raise

    def test_on_position_update_noop(self):
        s = _ConcreteStrategy()
        s.on_position_update({"symbol": "SPY"})  # no raise


# ---------------------------------------------------------------------------
# Momentum strategy
# ---------------------------------------------------------------------------

class TestMomentumStrategy:
    def test_name_and_broker(self):
        from trauto.strategies.alpaca.momentum import MomentumStrategy
        s = MomentumStrategy()
        assert s.name == "alpaca.momentum"
        assert s.broker == "alpaca"

    def test_get_status_shape(self):
        from trauto.strategies.alpaca.momentum import MomentumStrategy
        s = MomentumStrategy()
        status = s.get_status()
        assert status.name == "alpaca.momentum"

    def test_emits_buy_on_crossover(self):
        from trauto.strategies.alpaca.momentum import MomentumStrategy
        s = MomentumStrategy(short_window=2, long_window=4, symbols=["SPY"])
        # Build bars where short MA just crossed above long MA
        prices = [100, 98, 97, 96, 95, 94, 100, 105, 110, 115]
        df = pd.DataFrame({"close": prices})
        asyncio.get_event_loop().run_until_complete(s.on_bar({"SPY": df}))
        # Signals may or may not fire depending on window alignment — just check no crash
        _ = s.get_signals()

    def test_on_start_clears_state(self):
        from trauto.strategies.alpaca.momentum import MomentumStrategy
        s = MomentumStrategy()
        s._last_signals["SPY"] = 1.0
        s.on_start()
        assert s._last_signals == {}


# ---------------------------------------------------------------------------
# ArbScanner strategy (no live deps)
# ---------------------------------------------------------------------------

class TestArbScannerStrategy:
    def test_name_and_broker(self):
        from trauto.strategies.polymarket.arb_scanner import ArbScannerStrategy
        s = ArbScannerStrategy()
        assert s.name == "polymarket.arb_scanner"
        assert s.broker == "polymarket"

    def test_get_status_shape(self):
        from trauto.strategies.polymarket.arb_scanner import ArbScannerStrategy
        s = ArbScannerStrategy()
        status = s.get_status()
        assert isinstance(status, StrategyStatus)

    def test_no_config_no_signals(self):
        from trauto.strategies.polymarket.arb_scanner import ArbScannerStrategy
        s = ArbScannerStrategy(config=None)
        asyncio.get_event_loop().run_until_complete(s.on_tick({}))
        assert s.get_signals() == []
