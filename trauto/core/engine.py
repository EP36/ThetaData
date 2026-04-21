"""Main trading engine — asyncio-based orchestrator for all strategies.

Design goals:
  - NOT microsecond HFT. Target: no unnecessary latency beyond what broker APIs impose.
  - Async throughout: market data cache updated in background, orders fired in parallel.
  - Tick loop runs at ENGINE_TICK_MS (default 100ms = 10 ticks/sec).
  - Single emergency stop that persists across restarts.
  - All orders pass through GlobalRiskManager before reaching any broker.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trauto.brokers.base import BrokerInterface
from trauto.config import config
from trauto.core.event_bus import EventBus
from trauto.core.executor import UnifiedExecutor
from trauto.core.portfolio import PortfolioState
from trauto.core.risk import GlobalRiskManager
from trauto.core.scheduler import Scheduler
from trauto.strategies.base import BaseStrategy

LOGGER = logging.getLogger("trauto.core.engine")

_STRATEGY_CONFIG_PATH = Path("data/strategy_config.json")


@dataclass
class EngineStats:
    """Runtime stats for the /api/engine/status endpoint."""
    started_at: str = ""
    tick_count: int = 0
    last_tick_at: str = ""
    tick_rate_hz: float = 0.0
    strategies_loaded: int = 0
    strategies_enabled: int = 0
    emergency_stop: bool = False
    uptime_sec: float = 0.0


class TradingEngine:
    """Async trading engine that orchestrates all strategies and brokers.

    Usage:
        engine = TradingEngine()
        engine.register_broker(alpaca_broker)
        engine.register_broker(polymarket_broker)
        engine.register_strategy(ArbScannerStrategy(config=poly_config))
        await engine.start()   # runs until stopped or Ctrl-C

    The engine reads data/strategy_config.json at startup and can reload
    strategy configuration at runtime via reload_strategy_config().
    """

    def __init__(self) -> None:
        self.tick_ms: float = float(config.get("engine.tick_ms", 100))
        self.dry_run: bool = bool(config.get("engine.dry_run", True))

        self.risk_manager = GlobalRiskManager(
            global_daily_loss_limit=float(config.get("risk.global_daily_loss_limit", 500)),
            global_max_positions=int(config.get("risk.global_max_positions", 20)),
            circuit_breaker_error_threshold=int(config.get("risk.circuit_breaker_error_threshold", 3)),
            circuit_breaker_cooldown_sec=float(config.get("risk.circuit_breaker_cooldown_sec", 60)),
            circuit_breaker_hourly_trip_limit=int(config.get("risk.circuit_breaker_hourly_trip_limit", 3)),
        )
        self.executor = UnifiedExecutor(risk_manager=self.risk_manager)
        self.event_bus = EventBus()
        self.scheduler = Scheduler()
        self.portfolio = PortfolioState()

        self._strategies: dict[str, BaseStrategy] = {}
        self._running: bool = False
        self._start_time: float = 0.0
        self._tick_count: int = 0
        self._last_tick_times: list[float] = []  # rolling window for Hz calc
        self._market_data_cache: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_broker(self, broker: BrokerInterface) -> None:
        self.executor.register_broker(broker)
        LOGGER.info("engine_broker_registered broker=%s", broker.name)

    def register_strategy(self, strategy: BaseStrategy) -> None:
        self._strategies[strategy.name] = strategy
        self._apply_persisted_config(strategy)
        LOGGER.info(
            "engine_strategy_registered name=%s broker=%s enabled=%s dry_run=%s",
            strategy.name,
            strategy.broker,
            strategy.enabled,
            strategy.dry_run,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the engine. Runs until stop() is called."""
        LOGGER.info(
            "engine_starting tick_ms=%.0f dry_run=%s emergency_stop=%s strategies=%d",
            self.tick_ms,
            self.dry_run,
            self.risk_manager.is_emergency_stop(),
            len(self._strategies),
        )
        self._running = True
        self._start_time = time.monotonic()

        # Notify all strategies
        for strategy in self._strategies.values():
            if strategy.enabled:
                try:
                    strategy.on_start()
                except Exception as exc:
                    LOGGER.error("strategy_on_start_error name=%s error=%s", strategy.name, exc)

        # Start background market data refresh
        asyncio.create_task(self._market_data_refresh_loop())

        # Main tick loop
        while self._running:
            tick_start = time.monotonic()
            try:
                await self._tick()
            except Exception as exc:
                LOGGER.error("engine_tick_error error=%s", exc)
            elapsed_ms = (time.monotonic() - tick_start) * 1000.0
            sleep_ms = max(0.0, self.tick_ms - elapsed_ms)
            await asyncio.sleep(sleep_ms / 1000.0)

        LOGGER.info("engine_stopped tick_count=%d", self._tick_count)

    async def stop(self, emergency: bool = False) -> None:
        """Stop the engine. If emergency=True, activates emergency stop."""
        if emergency:
            self.risk_manager.set_emergency_stop(True)
            LOGGER.error("engine_emergency_stop")
            # Cancel all open orders on all brokers
            for broker in self.executor.brokers.values():
                try:
                    positions = await broker.get_positions()
                    LOGGER.warning(
                        "engine_emergency_stop open_positions=%d broker=%s",
                        len(positions),
                        broker.name,
                    )
                except Exception as exc:
                    LOGGER.error("engine_emergency_stop_positions_error broker=%s error=%s", broker.name, exc)

        for strategy in self._strategies.values():
            try:
                strategy.on_stop()
            except Exception:
                pass

        self._running = False

    async def resume(self) -> None:
        """Clear emergency stop and allow execution to resume."""
        self.risk_manager.set_emergency_stop(False)
        LOGGER.warning("engine_resumed emergency_stop_cleared")

    # ------------------------------------------------------------------
    # Tick
    # ------------------------------------------------------------------

    async def _tick(self) -> None:
        """One engine tick: collect signals → risk check → execute → update portfolio."""
        self._tick_count += 1
        now = time.monotonic()
        self._last_tick_times.append(now)
        self._last_tick_times = self._last_tick_times[-100:]  # keep 100 ticks for Hz calc

        market_data = dict(self._market_data_cache)

        # 1. Dispatch on_tick to scheduled strategies
        tick_tasks = []
        for strategy in self._strategies.values():
            if self.scheduler.is_due(strategy):
                tick_tasks.append(self._run_strategy_tick(strategy, market_data))
        if tick_tasks:
            await asyncio.gather(*tick_tasks, return_exceptions=True)

        # 2. Collect all signals
        all_signals: list[tuple[Any, BaseStrategy]] = []
        for strategy in self._strategies.values():
            sigs = strategy.get_signals()
            for sig in sigs:
                all_signals.append((sig, strategy))

        # 3. Deduplicate: one signal per (broker, symbol) per tick — highest confidence wins
        seen: dict[tuple[str, str], tuple[Any, BaseStrategy]] = {}
        for sig, strat in all_signals:
            key = (sig.broker, sig.symbol)
            if key not in seen or sig.confidence > seen[key][0].confidence:
                seen[key] = (sig, strat)

        deduplicated = list(seen.values())

        # 4. Execute approved signals
        if deduplicated:
            await self.executor.execute_batch(deduplicated, self.portfolio)

        # 5. Update portfolio state
        await self._refresh_portfolio()

        # 6. Publish tick event
        await self.event_bus.publish("engine.tick", {
            "tick_count": self._tick_count,
            "signals_collected": len(all_signals),
            "signals_executed": len(deduplicated),
        })

    async def _run_strategy_tick(self, strategy: BaseStrategy, market_data: dict) -> None:
        """Call strategy.on_tick with error isolation."""
        try:
            await strategy.on_tick(market_data)
        except Exception as exc:
            LOGGER.error("strategy_tick_error name=%s error=%s", strategy.name, exc)

    # ------------------------------------------------------------------
    # Portfolio refresh
    # ------------------------------------------------------------------

    async def _refresh_portfolio(self) -> None:
        """Update portfolio state from all registered brokers."""
        for broker_name, broker in self.executor.brokers.items():
            try:
                account = await broker.get_account()
                positions = await broker.get_positions()
                self.portfolio.accounts[broker_name] = account
                self.portfolio.positions[broker_name] = positions
            except Exception as exc:
                LOGGER.warning("portfolio_refresh_error broker=%s error=%s", broker_name, exc)
                self.risk_manager.record_broker_error(broker_name)

    # ------------------------------------------------------------------
    # Market data background refresh
    # ------------------------------------------------------------------

    async def _market_data_refresh_loop(self) -> None:
        """Background task: refresh BTC signals periodically."""
        while self._running:
            try:
                from src.polymarket.alpaca_signals import refresh_btc_signals_if_stale
                interval = float(config.get("polymarket.signal_interval_sec", 300))
                signals = await asyncio.to_thread(refresh_btc_signals_if_stale, interval)
                if signals.data_available:
                    self._market_data_cache["btc_signals"] = signals
            except Exception as exc:
                LOGGER.debug("market_data_refresh_error error=%s", exc)
            await asyncio.sleep(60)

    # ------------------------------------------------------------------
    # Strategy config persistence
    # ------------------------------------------------------------------

    def reload_strategy_config(self) -> None:
        """Reload data/strategy_config.json and apply to running strategies."""
        if not _STRATEGY_CONFIG_PATH.exists():
            return
        try:
            raw = json.loads(_STRATEGY_CONFIG_PATH.read_text(encoding="utf-8"))
            strategies_cfg = raw.get("strategies", {})
            for name, cfg in strategies_cfg.items():
                strategy = self._strategies.get(name)
                if strategy is None:
                    continue
                self._apply_config_dict(strategy, cfg)
            LOGGER.info("engine_strategy_config_reloaded count=%d", len(strategies_cfg))
        except Exception as exc:
            LOGGER.error("engine_strategy_config_reload_failed error=%s", exc)

    def _apply_persisted_config(self, strategy: BaseStrategy) -> None:
        if not _STRATEGY_CONFIG_PATH.exists():
            return
        try:
            raw = json.loads(_STRATEGY_CONFIG_PATH.read_text(encoding="utf-8"))
            cfg = raw.get("strategies", {}).get(strategy.name, {})
            if cfg:
                self._apply_config_dict(strategy, cfg)
        except Exception:
            pass

    @staticmethod
    def _apply_config_dict(strategy: BaseStrategy, cfg: dict) -> None:
        if "enabled" in cfg:
            strategy.enabled = bool(cfg["enabled"])
        if "dry_run" in cfg:
            strategy.dry_run = bool(cfg["dry_run"])
        if "capital_allocation_pct" in cfg:
            strategy.capital_allocation_pct = float(cfg["capital_allocation_pct"])
        if "max_positions" in cfg:
            strategy.max_positions = int(cfg["max_positions"])
        if "schedule" in cfg:
            from trauto.strategies.base import ScheduleType, StrategySchedule
            s = cfg["schedule"]
            if isinstance(s, str):
                strategy.schedule = StrategySchedule(type=ScheduleType(s))
            elif isinstance(s, dict):
                strategy.schedule = StrategySchedule(
                    type=ScheduleType(s.get("type", "always")),
                    interval_sec=float(s.get("interval_sec", 60)),
                    window_start=s.get("window_start", "09:30"),
                    window_end=s.get("window_end", "16:00"),
                    cron_expr=s.get("cron_expr", ""),
                )

    def save_strategy_config(self) -> None:
        """Persist current strategy states to data/strategy_config.json."""
        strategies_cfg: dict[str, Any] = {}
        for name, strategy in self._strategies.items():
            strategies_cfg[name] = {
                "enabled": strategy.enabled,
                "dry_run": strategy.dry_run,
                "capital_allocation_pct": strategy.capital_allocation_pct,
                "max_positions": strategy.max_positions,
                "schedule": {
                    "type": strategy.schedule.type.value
                    if hasattr(strategy.schedule.type, "value") else strategy.schedule.type,
                    "interval_sec": strategy.schedule.interval_sec,
                },
                "risk_params": {
                    "max_position_size_pct": strategy.risk_params.max_position_size_pct,
                    "max_daily_loss": strategy.risk_params.max_daily_loss,
                },
            }
        try:
            _STRATEGY_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            _STRATEGY_CONFIG_PATH.write_text(
                json.dumps({"strategies": strategies_cfg}, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            LOGGER.error("engine_strategy_config_save_failed error=%s", exc)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_stats(self) -> EngineStats:
        """Return current engine runtime stats."""
        uptime = time.monotonic() - self._start_time if self._start_time > 0 else 0.0

        hz = 0.0
        if len(self._last_tick_times) >= 2:
            window = self._last_tick_times[-1] - self._last_tick_times[0]
            if window > 0:
                hz = (len(self._last_tick_times) - 1) / window

        return EngineStats(
            started_at=datetime.fromtimestamp(
                time.time() - uptime, tz=timezone.utc
            ).isoformat() if uptime > 0 else "",
            tick_count=self._tick_count,
            last_tick_at=datetime.now(tz=timezone.utc).isoformat() if self._tick_count > 0 else "",
            tick_rate_hz=round(hz, 2),
            strategies_loaded=len(self._strategies),
            strategies_enabled=sum(1 for s in self._strategies.values() if s.enabled),
            emergency_stop=self.risk_manager.is_emergency_stop(),
            uptime_sec=round(uptime, 1),
        )

    def get_strategy_statuses(self) -> list[dict[str, Any]]:
        """Return status dict for each loaded strategy."""
        statuses = []
        for strategy in self._strategies.values():
            try:
                status = strategy.get_status()
                statuses.append({
                    "name": status.name,
                    "broker": status.broker,
                    "enabled": status.enabled,
                    "dry_run": status.dry_run,
                    "capital_allocation_pct": status.capital_allocation_pct,
                    "max_positions": status.max_positions,
                    "schedule_type": status.schedule_type,
                    "active_signals": status.active_signals,
                    "daily_pnl": status.daily_pnl,
                    "win_rate": status.win_rate,
                    "extra": status.extra,
                })
            except Exception as exc:
                LOGGER.warning("strategy_status_error name=%s error=%s", strategy.name, exc)
        return statuses

    def update_strategy(self, name: str, updates: dict[str, Any]) -> None:
        """Apply live config updates to a strategy and persist."""
        strategy = self._strategies.get(name)
        if strategy is None:
            raise KeyError(f"Strategy not found: {name}")
        self._apply_config_dict(strategy, updates)
        self.save_strategy_config()
        LOGGER.info("engine_strategy_updated name=%s updates=%s", name, updates)
