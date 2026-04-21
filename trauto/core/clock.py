"""Market hours and trading calendar helpers."""

from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

_REGULAR_OPEN  = time(9, 30)
_REGULAR_CLOSE = time(16, 0)
_EXTENDED_OPEN = time(4, 0)
_EXTENDED_CLOSE = time(20, 0)


def now_et() -> datetime:
    """Return current datetime in US/Eastern."""
    return datetime.now(tz=ET)


def is_market_open(extended: bool = False) -> bool:
    """Return True if US equity markets are currently open.

    Args:
        extended: if True, include pre/after market hours (4:00–20:00 ET).
    """
    now = now_et()
    if now.weekday() >= 5:
        return False
    t = now.time().replace(tzinfo=None)
    if extended:
        return _EXTENDED_OPEN <= t < _EXTENDED_CLOSE
    return _REGULAR_OPEN <= t < _REGULAR_CLOSE


def is_within_window(start_hhmm: str, end_hhmm: str) -> bool:
    """Return True if current ET time is within [start_hhmm, end_hhmm)."""
    now_t = now_et().time().replace(tzinfo=None)
    start = time.fromisoformat(start_hhmm)
    end = time.fromisoformat(end_hhmm)
    return start <= now_t < end


def minutes_to_close() -> float:
    """Return minutes until the next regular session close, or 0 if after hours."""
    now = now_et()
    close_today = now.replace(hour=16, minute=0, second=0, microsecond=0, tzinfo=ET)
    if not is_market_open():
        return 0.0
    delta = close_today - now
    return max(0.0, delta.total_seconds() / 60.0)
