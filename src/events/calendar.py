"""Event calendar for dynamic scan intensity.

Calculates a scan interval multiplier based on proximity to high-impact events.
The multiplier is applied to config.scan_interval_sec in the main loop.

Multiplier range: 0.25 (scan 4x faster) to 1.0 (normal rate).

Usage:
    from src.events.calendar import get_scan_multiplier
    sleep_sec = max(30, int(config.scan_interval_sec * get_scan_multiplier()))
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

LOGGER = logging.getLogger("theta.events.calendar")

# Known recurring high-impact macro events (approximate windows, UTC).
# Format: (hour_start, hour_end, weekday_set or None for every day, label)
# weekday: 0=Mon, 4=Fri
_RECURRING_WINDOWS: list[tuple[int, int, set[int] | None, str]] = [
    (12, 15, None,     "US_market_open"),       # 8–11am ET daily
    (18, 22, None,     "US_market_close"),       # 2–6pm ET daily
    (13, 15, {1},      "FOMC_typical_release"),  # Tuesdays 9-11am ET (approx)
    (12, 14, {2},      "CPI_release_window"),    # Wednesdays 8-10am ET (approx)
    (12, 14, {4},      "NFP_release_window"),    # Fridays 8-10am ET (monthly)
]

# One-off events loaded from POLY_EVENTS env var or a JSON file.
# Format: ISO datetime strings. Scan runs at 4x speed within 2h of each event.
_EVENT_LEAD_HOURS = 2.0      # scan faster this many hours before event
_EVENT_DECAY_HOURS = 0.5     # return to normal this many hours after event


@dataclass
class ScheduledEvent:
    name: str
    event_time: datetime  # timezone-aware UTC
    category: str         # "macro" | "crypto" | "election" | "other"


def _load_scheduled_events() -> list[ScheduledEvent]:
    """Load one-off events from POLY_EVENTS_JSON env var (JSON list of ISO strings)."""
    import json
    import os
    raw = (os.getenv("POLY_EVENTS_JSON") or "").strip()
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except Exception as exc:
        LOGGER.warning("events_json_parse_failed error=%s raw=%.40r", exc, raw)
        return []
    events = []
    for item in items:
        try:
            if isinstance(item, str):
                dt = datetime.fromisoformat(item.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                events.append(ScheduledEvent(name="custom", event_time=dt, category="other"))
            elif isinstance(item, dict):
                dt = datetime.fromisoformat(item["time"].replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                events.append(ScheduledEvent(
                    name=item.get("name", "custom"),
                    event_time=dt,
                    category=item.get("category", "other"),
                ))
        except Exception as exc:
            LOGGER.warning("events_item_parse_failed item=%r error=%s", item, exc)
    return events


def _recurring_intensity(now: datetime) -> float:
    """Return intensity boost [0.0, 1.0] from recurring windows. 1.0 = full boost."""
    hour = now.hour
    weekday = now.weekday()
    for h_start, h_end, days, label in _RECURRING_WINDOWS:
        if days is not None and weekday not in days:
            continue
        if h_start <= hour < h_end:
            LOGGER.debug("events_recurring_window label=%s", label)
            return 0.5  # 2x scan speed during market windows
    return 0.0


def _scheduled_intensity(now: datetime, events: list[ScheduledEvent]) -> float:
    """Return intensity boost from one-off events. 1.0 = maximum boost."""
    best = 0.0
    now_ts = now.timestamp()
    for ev in events:
        ev_ts = ev.event_time.timestamp()
        delta_hours = (ev_ts - now_ts) / 3600.0
        if -_EVENT_DECAY_HOURS <= delta_hours <= _EVENT_LEAD_HOURS:
            # Linear ramp: full intensity at event time, fades after decay window
            frac = 1.0 - max(0.0, delta_hours / _EVENT_LEAD_HOURS)
            if frac > best:
                LOGGER.info("events_scheduled_event name=%s delta_hours=%.2f intensity=%.2f",
                            ev.name, delta_hours, frac)
                best = frac
    return best


def calculate_scan_intensity(events: list[ScheduledEvent] | None = None) -> float:
    """Return scan multiplier: lower = scan faster.

    1.0  → normal rate (no events)
    0.5  → 2x scan speed (market window)
    0.25 → 4x scan speed (imminent scheduled event)
    """
    if events is None:
        events = _load_scheduled_events()
    now = datetime.now(timezone.utc)
    recurring = _recurring_intensity(now)
    scheduled = _scheduled_intensity(now, events)
    # Combine: scheduled event overrides recurring window
    intensity = max(recurring, scheduled)
    # Map intensity [0, 1] → multiplier [1.0, 0.25]
    multiplier = 1.0 - (intensity * 0.75)
    return round(max(0.25, min(1.0, multiplier)), 2)


def get_scan_multiplier() -> float:
    """Top-level convenience — returns scan interval multiplier."""
    return calculate_scan_intensity()
