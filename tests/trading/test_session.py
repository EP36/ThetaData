"""Tests for session-aware trading context classification."""

from __future__ import annotations

import pandas as pd

from src.trading.session import (
    SessionConfig,
    classify_trading_session,
    minutes_until_regular_session_end,
)


def test_regular_session_allows_full_size() -> None:
    context = classify_trading_session(pd.Timestamp("2026-04-16T15:00:00Z"))

    assert context.state == "regular_session"
    assert context.can_open_new_positions is True
    assert context.size_multiplier == 1.0


def test_premarket_fails_closed_when_extended_hours_disabled() -> None:
    context = classify_trading_session(pd.Timestamp("2026-04-16T12:00:00Z"))

    assert context.state == "premarket_session"
    assert context.can_open_new_positions is False
    assert context.size_multiplier == 0.0
    assert context.reason == "extended_hours_disabled"


def test_extended_hours_requires_broker_support() -> None:
    unsupported = classify_trading_session(
        pd.Timestamp("2026-04-16T12:00:00Z"),
        SessionConfig(extended_hours_enabled=True),
    )
    supported = classify_trading_session(
        pd.Timestamp("2026-04-16T12:00:00Z"),
        SessionConfig(
            extended_hours_enabled=True,
            broker_extended_hours_supported=True,
        ),
    )

    assert unsupported.reason == "extended_hours_unsupported"
    assert unsupported.can_open_new_positions is False
    assert supported.state == "premarket_session"
    assert supported.can_open_new_positions is True
    assert supported.size_multiplier == 0.5


def test_overnight_uses_reduced_size_when_enabled() -> None:
    context = classify_trading_session(
        pd.Timestamp("2026-04-16T06:00:00Z"),
        SessionConfig(
            extended_hours_enabled=True,
            overnight_trading_enabled=True,
            broker_extended_hours_supported=True,
        ),
    )

    assert context.state == "overnight_session"
    assert context.can_open_new_positions is True
    assert context.size_multiplier == 0.25


def test_weekend_is_closed() -> None:
    context = classify_trading_session(
        pd.Timestamp("2026-04-18T15:00:00Z"),
        SessionConfig(
            extended_hours_enabled=True,
            broker_extended_hours_supported=True,
        ),
    )

    assert context.state == "closed_session"
    assert context.can_open_new_positions is False
    assert context.reason == "weekend_closed"


def test_minutes_until_regular_session_end_uses_market_time() -> None:
    minutes_left = minutes_until_regular_session_end(
        pd.Timestamp("2026-04-16T19:50:00Z")
    )

    assert minutes_left == 10.0
