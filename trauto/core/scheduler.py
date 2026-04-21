"""Strategy scheduler — determines which strategies run on each engine tick."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from trauto.core.clock import is_market_open, is_within_window
from trauto.strategies.base import ScheduleType, StrategySchedule

if TYPE_CHECKING:
    from trauto.strategies.base import BaseStrategy

LOGGER = logging.getLogger("trauto.core.scheduler")


@dataclass
class Scheduler:
    """Tracks last-run times and decides whether each strategy is due to run."""

    _last_run: dict[str, float] = field(default_factory=dict)

    def is_due(self, strategy: "BaseStrategy") -> bool:
        """Return True if this strategy should run on the current tick."""
        if not strategy.enabled:
            return False

        schedule = strategy.schedule
        now = time.monotonic()
        last = self._last_run.get(strategy.name, float("-inf"))

        stype = schedule.type
        if isinstance(stype, str):
            try:
                stype = ScheduleType(stype)
            except ValueError:
                stype = ScheduleType.ALWAYS

        if stype == ScheduleType.ALWAYS:
            self._last_run[strategy.name] = now
            return True

        if stype == ScheduleType.INTERVAL:
            if now - last >= schedule.interval_sec:
                self._last_run[strategy.name] = now
                return True
            return False

        if stype == ScheduleType.MARKET_HOURS:
            if not is_market_open():
                return False
            self._last_run[strategy.name] = now
            return True

        if stype == ScheduleType.TIME_WINDOW:
            if not is_within_window(schedule.window_start, schedule.window_end):
                return False
            if now - last >= max(schedule.interval_sec, 1.0):
                self._last_run[strategy.name] = now
                return True
            return False

        if stype == ScheduleType.CRON:
            # Basic cron: check every minute
            if now - last >= 60.0:
                if self._cron_matches(schedule.cron_expr):
                    self._last_run[strategy.name] = now
                    return True
            return False

        if stype == ScheduleType.MANUAL:
            return False

        return False

    def trigger_manual(self, strategy_name: str) -> None:
        """Force a manual-schedule strategy to run on the next tick check."""
        self._last_run[strategy_name] = 0.0

    def reset(self, strategy_name: str) -> None:
        """Reset last-run time so strategy runs immediately on next check."""
        self._last_run.pop(strategy_name, None)

    @staticmethod
    def _cron_matches(expr: str) -> bool:
        """Minimal cron matcher for common patterns (minute-level granularity)."""
        import datetime
        if not expr.strip():
            return False
        now = datetime.datetime.now()
        parts = expr.strip().split()
        if len(parts) != 5:
            return False
        minute, hour, dom, month, dow = parts
        def _field_match(field: str, value: int) -> bool:
            if field == "*":
                return True
            if field.startswith("*/"):
                step = int(field[2:])
                return value % step == 0
            return str(value) == field
        return (
            _field_match(minute, now.minute)
            and _field_match(hour, now.hour)
            and _field_match(dom, now.day)
            and _field_match(month, now.month)
            and _field_match(dow, now.weekday())
        )
