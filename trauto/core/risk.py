"""Global risk manager — the single gatekeeper for all order execution.

No signal reaches a broker without passing through GlobalRiskManager.check().

Hierarchy of checks:
  1. Emergency stop  → block everything
  2. Global daily loss exceeded → block everything
  3. Global max positions exceeded → block new-position buys
  4. Circuit breaker tripped for this broker → block that broker's signals
  5. Per-strategy: enabled, dry_run, capital allocation, strategy risk params
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from trauto.core.portfolio import PortfolioState
    from trauto.strategies.base import BaseStrategy, Signal

LOGGER = logging.getLogger("trauto.core.risk")

_ENGINE_STATE_PATH = Path("data/engine_state.json")


@dataclass
class CircuitBreakerState:
    """Per-broker circuit breaker tracking."""
    broker: str
    consecutive_errors: int = 0
    tripped_at: float = 0.0          # monotonic time when last tripped
    trip_count_this_hour: int = 0
    hour_window_start: float = 0.0
    manual_resume_required: bool = False

    @property
    def is_tripped(self) -> bool:
        return self.tripped_at != 0.0

    def record_error(self, error_threshold: int, cooldown_sec: float, hourly_limit: int) -> bool:
        """Record a broker error. Return True if circuit just tripped."""
        self.consecutive_errors += 1
        if self.consecutive_errors >= error_threshold and not self.is_tripped:
            self.tripped_at = time.monotonic()
            now = time.monotonic()
            if now - self.hour_window_start > 3600:
                self.hour_window_start = now
                self.trip_count_this_hour = 0
            self.trip_count_this_hour += 1
            if self.trip_count_this_hour >= hourly_limit:
                self.manual_resume_required = True
                LOGGER.error(
                    "circuit_breaker_manual_resume_required broker=%s trips_this_hour=%d",
                    self.broker,
                    self.trip_count_this_hour,
                )
            LOGGER.error(
                "circuit_breaker_tripped broker=%s consecutive_errors=%d",
                self.broker,
                self.consecutive_errors,
            )
            return True
        return False

    def record_success(self) -> None:
        self.consecutive_errors = 0

    def try_auto_resume(self, cooldown_sec: float) -> bool:
        """Return True if auto-resume is possible and executed."""
        if not self.is_tripped:
            return True
        if self.manual_resume_required:
            return False
        if time.monotonic() - self.tripped_at >= cooldown_sec:
            LOGGER.info("circuit_breaker_auto_resumed broker=%s", self.broker)
            self.tripped_at = 0.0
            self.consecutive_errors = 0
            return True
        return False

    def manual_resume(self) -> None:
        LOGGER.warning("circuit_breaker_manual_resumed broker=%s", self.broker)
        self.tripped_at = 0.0
        self.consecutive_errors = 0
        self.manual_resume_required = False


@dataclass
class RiskDecision:
    """Result of a risk check for one signal."""
    approved: bool
    reason: str = ""        # rejection reason when approved=False
    dry_run: bool = False   # True → log intent but don't execute


@dataclass
class GlobalRiskManager:
    """Unified risk gatekeeper for all broker + strategy combinations."""

    global_daily_loss_limit: float = 500.0
    global_max_positions: int = 20
    circuit_breaker_error_threshold: int = 3
    circuit_breaker_cooldown_sec: float = 60.0
    circuit_breaker_hourly_trip_limit: int = 3

    _emergency_stop: bool = field(default=False, init=False)
    _circuit_breakers: dict[str, CircuitBreakerState] = field(default_factory=dict, init=False)
    _alerts: list[dict[str, Any]] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self._load_engine_state()

    # ------------------------------------------------------------------
    # Emergency stop
    # ------------------------------------------------------------------

    def is_emergency_stop(self) -> bool:
        return self._emergency_stop

    def set_emergency_stop(self, enabled: bool) -> None:
        self._emergency_stop = enabled
        self._persist_engine_state()
        if enabled:
            LOGGER.error("emergency_stop_activated")
            self._add_alert("critical", "engine", "Emergency stop activated — all execution halted")
        else:
            LOGGER.warning("emergency_stop_cleared")
            self._remove_alert_by_source("engine")

    # ------------------------------------------------------------------
    # Main check
    # ------------------------------------------------------------------

    def check(
        self,
        signal: "Signal",
        strategy: "BaseStrategy",
        portfolio: "PortfolioState",
    ) -> RiskDecision:
        """Validate a signal. Returns RiskDecision(approved=True/False)."""

        # 1. Emergency stop
        if self._emergency_stop:
            return RiskDecision(approved=False, reason="emergency_stop")

        # 2. Strategy not enabled
        if not strategy.enabled:
            return RiskDecision(approved=False, reason="strategy_disabled")

        # 3. Global daily loss
        total_daily_loss = -portfolio.combined_realized_today if portfolio.combined_realized_today < 0 else 0.0
        if total_daily_loss >= self.global_daily_loss_limit:
            return RiskDecision(approved=False, reason="global_daily_loss_exceeded")

        # 4. Global max positions (only block buys)
        if signal.action in ("buy",) and portfolio.total_open_positions >= self.global_max_positions:
            return RiskDecision(approved=False, reason="global_max_positions_exceeded")

        # 5. Circuit breaker for this broker
        cb = self._get_or_create_circuit_breaker(signal.broker)
        if cb.is_tripped:
            if not cb.try_auto_resume(self.circuit_breaker_cooldown_sec):
                return RiskDecision(approved=False, reason=f"circuit_breaker_{signal.broker}")

        # 6. Strategy dry_run
        if strategy.dry_run:
            return RiskDecision(approved=True, dry_run=True)

        # 7. Per-strategy capital allocation guard
        broker_account = portfolio.accounts.get(signal.broker)
        if broker_account:
            max_allocated = broker_account.portfolio_value * strategy.capital_allocation_pct / 100.0
            broker_positions = portfolio.positions.get(signal.broker, [])
            strategy_deployed = sum(
                p.size_usd for p in broker_positions
                if p.extra.get("strategy") == strategy.name
            )
            if signal.action == "buy" and strategy_deployed >= max_allocated and max_allocated > 0:
                return RiskDecision(approved=False, reason="capital_allocation_exhausted")

        return RiskDecision(approved=True, dry_run=False)

    # ------------------------------------------------------------------
    # Circuit breaker management
    # ------------------------------------------------------------------

    def record_broker_error(self, broker: str) -> None:
        cb = self._get_or_create_circuit_breaker(broker)
        tripped = cb.record_error(
            self.circuit_breaker_error_threshold,
            self.circuit_breaker_cooldown_sec,
            self.circuit_breaker_hourly_trip_limit,
        )
        if tripped:
            self._add_alert(
                "error",
                broker,
                f"{broker} circuit breaker tripped — {cb.trip_count_this_hour} trip(s) this hour"
                + (" — MANUAL RESUME REQUIRED" if cb.manual_resume_required else ""),
            )

    def record_broker_success(self, broker: str) -> None:
        cb = self._get_or_create_circuit_breaker(broker)
        cb.record_success()

    def manual_resume_circuit_breaker(self, broker: str) -> None:
        cb = self._get_or_create_circuit_breaker(broker)
        cb.manual_resume()
        self._remove_alert_by_source(broker)

    def circuit_breaker_status(self) -> dict[str, Any]:
        return {
            broker: {
                "is_tripped": cb.is_tripped,
                "consecutive_errors": cb.consecutive_errors,
                "manual_resume_required": cb.manual_resume_required,
                "trip_count_this_hour": cb.trip_count_this_hour,
            }
            for broker, cb in self._circuit_breakers.items()
        }

    def get_alerts(self) -> list[dict[str, Any]]:
        return list(self._alerts)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_engine_state(self) -> None:
        try:
            _ENGINE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            _ENGINE_STATE_PATH.write_text(
                json.dumps({"emergency_stop": self._emergency_stop}, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            LOGGER.error("engine_state_persist_failed error=%s", exc)

    def _load_engine_state(self) -> None:
        if not _ENGINE_STATE_PATH.exists():
            return
        try:
            data = json.loads(_ENGINE_STATE_PATH.read_text(encoding="utf-8"))
            self._emergency_stop = bool(data.get("emergency_stop", False))
            if self._emergency_stop:
                LOGGER.warning("engine_state_loaded emergency_stop=True")
        except Exception as exc:
            LOGGER.warning("engine_state_load_failed error=%s", exc)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_or_create_circuit_breaker(self, broker: str) -> CircuitBreakerState:
        if broker not in self._circuit_breakers:
            self._circuit_breakers[broker] = CircuitBreakerState(broker=broker)
        return self._circuit_breakers[broker]

    def _add_alert(self, level: str, source: str, message: str) -> None:
        self._alerts.append({"level": level, "source": source, "message": message})

    def _remove_alert_by_source(self, source: str) -> None:
        self._alerts = [a for a in self._alerts if a.get("source") != source]
