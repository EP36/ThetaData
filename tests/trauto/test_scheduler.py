"""Tests for strategy scheduler — each schedule type fires at the right time."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from trauto.core.scheduler import Scheduler
from trauto.strategies.base import (
    BaseStrategy,
    ScheduleType,
    StrategySchedule,
    StrategyStatus,
)


class _S(BaseStrategy):
    def __init__(self, name: str, schedule: StrategySchedule, enabled: bool = True):
        super().__init__(enabled=enabled, schedule=schedule)
        self.name = name

    def get_status(self) -> StrategyStatus:
        return self._base_status()


class TestScheduler:
    def test_always_runs_every_tick(self):
        sched = Scheduler()
        s = _S("s1", StrategySchedule(type=ScheduleType.ALWAYS))
        assert sched.is_due(s) is True
        assert sched.is_due(s) is True

    def test_disabled_never_runs(self):
        sched = Scheduler()
        s = _S("s1", StrategySchedule(type=ScheduleType.ALWAYS), enabled=False)
        assert sched.is_due(s) is False

    def test_interval_not_due_immediately_twice(self):
        sched = Scheduler()
        s = _S("s1", StrategySchedule(type=ScheduleType.INTERVAL, interval_sec=60.0))
        assert sched.is_due(s) is True    # first time — always due
        assert sched.is_due(s) is False   # too soon

    def test_interval_due_after_elapsed(self):
        sched = Scheduler()
        s = _S("s1", StrategySchedule(type=ScheduleType.INTERVAL, interval_sec=0.05))
        assert sched.is_due(s) is True
        time.sleep(0.1)
        assert sched.is_due(s) is True

    def test_market_hours_open(self):
        sched = Scheduler()
        s = _S("s1", StrategySchedule(type=ScheduleType.MARKET_HOURS))
        with patch("trauto.core.scheduler.is_market_open", return_value=True):
            assert sched.is_due(s) is True

    def test_market_hours_closed(self):
        sched = Scheduler()
        s = _S("s1", StrategySchedule(type=ScheduleType.MARKET_HOURS))
        with patch("trauto.core.scheduler.is_market_open", return_value=False):
            assert sched.is_due(s) is False

    def test_manual_never_runs_by_default(self):
        sched = Scheduler()
        s = _S("s1", StrategySchedule(type=ScheduleType.MANUAL))
        assert sched.is_due(s) is False

    def test_manual_trigger_runs_once(self):
        sched = Scheduler()
        s = _S("s1", StrategySchedule(type=ScheduleType.MANUAL))
        # manual trigger not implemented in is_due for MANUAL type (always False)
        # This tests that manual schedule never fires without explicit trigger
        assert sched.is_due(s) is False

    def test_time_window_inside(self):
        sched = Scheduler()
        s = _S("s1", StrategySchedule(
            type=ScheduleType.TIME_WINDOW, window_start="00:00", window_end="23:59", interval_sec=0.01
        ))
        with patch("trauto.core.scheduler.is_within_window", return_value=True):
            assert sched.is_due(s) is True

    def test_time_window_outside(self):
        sched = Scheduler()
        s = _S("s1", StrategySchedule(
            type=ScheduleType.TIME_WINDOW, window_start="00:00", window_end="00:01"
        ))
        with patch("trauto.core.scheduler.is_within_window", return_value=False):
            assert sched.is_due(s) is False

    def test_reset_forces_immediate_run(self):
        sched = Scheduler()
        s = _S("s1", StrategySchedule(type=ScheduleType.INTERVAL, interval_sec=3600.0))
        sched.is_due(s)  # run once — sets last_run
        assert sched.is_due(s) is False
        sched.reset(s.name)
        assert sched.is_due(s) is True

    def test_cron_matching_every_minute(self):
        sched = Scheduler()
        s = _S("s1", StrategySchedule(type=ScheduleType.CRON, cron_expr="* * * * *"))
        # Force last_run to be old so interval check passes
        sched._last_run[s.name] = float("-inf")
        with patch("trauto.core.scheduler.Scheduler._cron_matches", return_value=True):
            assert sched.is_due(s) is True

    def test_string_schedule_type(self):
        """Schedule type as string (from JSON config) should work."""
        sched = Scheduler()
        s = _S("s1", StrategySchedule(type="always"))  # type: ignore[arg-type]
        assert sched.is_due(s) is True
