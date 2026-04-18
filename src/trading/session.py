"""Session classification and sizing policy for intraday trading."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Literal

import pandas as pd

SessionState = Literal[
    "regular_session",
    "premarket_session",
    "afterhours_session",
    "overnight_session",
    "closed_session",
    "not_applicable",
]


@dataclass(frozen=True, slots=True)
class SessionConfig:
    """Configurable market-session boundaries and extended-hours gates."""

    regular_start: str = "09:30"
    regular_end: str = "16:00"
    premarket_start: str = "04:00"
    afterhours_end: str = "20:00"
    extended_hours_enabled: bool = False
    overnight_trading_enabled: bool = False
    broker_extended_hours_supported: bool = False


@dataclass(frozen=True, slots=True)
class SessionContext:
    """One timestamp's market-local trading session state."""

    state: SessionState
    timestamp_utc: pd.Timestamp
    timestamp_market: pd.Timestamp
    can_open_new_positions: bool
    size_multiplier: float
    reason: str | None = None

    @property
    def is_extended_hours(self) -> bool:
        """Return whether this context is outside regular hours."""
        return self.state in {
            "premarket_session",
            "afterhours_session",
            "overnight_session",
        }


def classify_trading_session(
    timestamp: pd.Timestamp | None,
    config: SessionConfig | None = None,
) -> SessionContext:
    """Classify a timestamp into regular, extended, overnight, or closed."""
    cfg = config or SessionConfig()
    ts_utc = _to_utc_timestamp(pd.Timestamp.utcnow() if timestamp is None else pd.Timestamp(timestamp))
    ts_market = ts_utc.tz_convert("America/New_York")

    if ts_market.weekday() >= 5:
        return SessionContext(
            state="closed_session",
            timestamp_utc=ts_utc,
            timestamp_market=ts_market,
            can_open_new_positions=False,
            size_multiplier=0.0,
            reason="weekend_closed",
        )

    regular_start = _parse_time(cfg.regular_start)
    regular_end = _parse_time(cfg.regular_end)
    premarket_start = _parse_time(cfg.premarket_start)
    afterhours_end = _parse_time(cfg.afterhours_end)
    current = ts_market.time()

    if regular_start <= current <= regular_end:
        return SessionContext(
            state="regular_session",
            timestamp_utc=ts_utc,
            timestamp_market=ts_market,
            can_open_new_positions=True,
            size_multiplier=1.0,
        )
    if premarket_start <= current < regular_start:
        return _extended_context(
            state="premarket_session",
            ts_utc=ts_utc,
            ts_market=ts_market,
            enabled=cfg.extended_hours_enabled,
            broker_supported=cfg.broker_extended_hours_supported,
            size_multiplier=0.5,
        )
    if regular_end < current <= afterhours_end:
        return _extended_context(
            state="afterhours_session",
            ts_utc=ts_utc,
            ts_market=ts_market,
            enabled=cfg.extended_hours_enabled,
            broker_supported=cfg.broker_extended_hours_supported,
            size_multiplier=0.5,
        )

    return _extended_context(
        state="overnight_session",
        ts_utc=ts_utc,
        ts_market=ts_market,
        enabled=cfg.extended_hours_enabled and cfg.overnight_trading_enabled,
        broker_supported=cfg.broker_extended_hours_supported,
        size_multiplier=0.25,
    )


def minutes_until_regular_session_end(
    timestamp: pd.Timestamp,
    regular_end: str = "16:00",
) -> float:
    """Return minutes from timestamp to the same-day regular-session close."""
    ts_market = _to_utc_timestamp(pd.Timestamp(timestamp)).tz_convert("America/New_York")
    end_time = _parse_time(regular_end)
    end_ts = pd.Timestamp.combine(ts_market.date(), end_time)
    end_ts = pd.Timestamp(end_ts, tz="America/New_York")
    return float((end_ts - ts_market).total_seconds() / 60.0)


def _extended_context(
    *,
    state: SessionState,
    ts_utc: pd.Timestamp,
    ts_market: pd.Timestamp,
    enabled: bool,
    broker_supported: bool,
    size_multiplier: float,
) -> SessionContext:
    if not enabled:
        return SessionContext(
            state=state,
            timestamp_utc=ts_utc,
            timestamp_market=ts_market,
            can_open_new_positions=False,
            size_multiplier=0.0,
            reason="extended_hours_disabled",
        )
    if not broker_supported:
        return SessionContext(
            state=state,
            timestamp_utc=ts_utc,
            timestamp_market=ts_market,
            can_open_new_positions=False,
            size_multiplier=0.0,
            reason="extended_hours_unsupported",
        )
    return SessionContext(
        state=state,
        timestamp_utc=ts_utc,
        timestamp_market=ts_market,
        can_open_new_positions=True,
        size_multiplier=size_multiplier,
    )


def _parse_time(value: str) -> time:
    try:
        return time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid time format '{value}', expected HH:MM") from exc


def _to_utc_timestamp(value: pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")
