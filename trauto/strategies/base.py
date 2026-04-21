"""Abstract base strategy for the unified trading engine."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

LOGGER = logging.getLogger("trauto.strategies.base")


class ScheduleType(str, Enum):
    ALWAYS = "always"
    INTERVAL = "interval"
    MARKET_HOURS = "market_hours"
    TIME_WINDOW = "time_window"
    CRON = "cron"
    MANUAL = "manual"


@dataclass
class StrategySchedule:
    """When a strategy is allowed to run."""
    type: ScheduleType = ScheduleType.ALWAYS
    interval_sec: float = 60.0          # used by INTERVAL
    window_start: str = "09:30"         # HH:MM ET, used by TIME_WINDOW
    window_end: str = "16:00"           # HH:MM ET, used by TIME_WINDOW
    cron_expr: str = ""                 # used by CRON (e.g. "*/5 * * * *")


@dataclass
class RiskParams:
    """Per-strategy risk controls."""
    max_position_size_pct: float = 0.25   # max notional as % of allocated capital
    max_daily_loss: float = 500.0          # $ daily loss before strategy auto-pauses
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None


@dataclass(frozen=True)
class Signal:
    """A trading signal emitted by a strategy."""
    strategy_name: str
    broker: str                  # "alpaca" | "polymarket"
    symbol: str
    action: str                  # "buy" | "sell" | "close" | "none"
    confidence: float            # 0.0–1.0
    price: float                 # reference price at signal generation
    size_usd: float = 0.0       # suggested notional (0 = let risk manager size it)
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class StrategyStatus:
    """Current state snapshot for dashboard rendering."""
    name: str
    broker: str
    enabled: bool
    dry_run: bool
    capital_allocation_pct: float
    max_positions: int
    schedule_type: str
    active_signals: int = 0
    daily_pnl: float = 0.0
    win_rate: float | None = None
    last_tick_at: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class BaseStrategy(ABC):
    """Abstract base class for all Trauto strategies.

    Lifecycle:
        engine.start() → on_start() → [on_tick() / on_bar() per schedule]
                                    → on_order_fill() / on_position_update()
        engine.stop()  → on_stop()

    Implementations must override on_start, get_signals, and get_status.
    on_tick, on_bar, on_order_fill, on_position_update are optional hooks.
    """

    # Class-level identity — subclasses must define these
    name: str = "base_strategy"
    broker: str = "alpaca"             # "alpaca" | "polymarket" | "both"

    def __init__(
        self,
        enabled: bool = True,
        dry_run: bool = True,
        capital_allocation_pct: float = 10.0,
        max_positions: int = 1,
        schedule: StrategySchedule | None = None,
        risk_params: RiskParams | None = None,
    ) -> None:
        self.enabled = enabled
        self.dry_run = dry_run
        self.capital_allocation_pct = capital_allocation_pct
        self.max_positions = max_positions
        self.schedule = schedule or StrategySchedule()
        self.risk_params = risk_params or RiskParams()
        self._signals: list[Signal] = []
        self._logger = logging.getLogger(f"trauto.strategies.{self.name}")

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------

    def on_start(self) -> None:
        """Called once when the strategy is enabled."""
        self._logger.info("strategy_started name=%s broker=%s dry_run=%s", self.name, self.broker, self.dry_run)

    def on_stop(self) -> None:
        """Called once when the strategy is disabled or engine stops."""
        self._logger.info("strategy_stopped name=%s", self.name)
        self._signals.clear()

    async def on_tick(self, market_data: dict[str, Any]) -> None:
        """Called on each engine tick for enabled strategies."""

    async def on_bar(self, bars: dict[str, Any]) -> None:
        """Called when a new bar completes for tracked symbols."""

    def on_order_fill(self, fill: dict[str, Any]) -> None:
        """Called when one of this strategy's orders fills."""

    def on_position_update(self, position: dict[str, Any]) -> None:
        """Called when P&L of a tracked position updates."""

    # ------------------------------------------------------------------
    # Signal management
    # ------------------------------------------------------------------

    def emit_signal(self, signal: Signal) -> None:
        """Record a signal for the engine to process on this tick."""
        self._signals.append(signal)
        self._logger.debug(
            "signal_emitted strategy=%s symbol=%s action=%s conf=%.3f",
            self.name,
            signal.symbol,
            signal.action,
            signal.confidence,
        )

    def get_signals(self) -> list[Signal]:
        """Return and clear pending signals from this strategy."""
        signals = list(self._signals)
        self._signals.clear()
        return signals

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    @abstractmethod
    def get_status(self) -> StrategyStatus:
        """Return current state snapshot for the dashboard."""

    def _base_status(self, **extra: Any) -> StrategyStatus:
        return StrategyStatus(
            name=self.name,
            broker=self.broker,
            enabled=self.enabled,
            dry_run=self.dry_run,
            capital_allocation_pct=self.capital_allocation_pct,
            max_positions=self.max_positions,
            schedule_type=self.schedule.type.value if hasattr(self.schedule.type, "value") else str(self.schedule.type),
            active_signals=len(self._signals),
            extra=extra,
        )
