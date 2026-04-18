"""Tests for strategy-specific intraday filters."""

from __future__ import annotations

from src.trading.strategy_filters import (
    StrategyFilterConfig,
    StrategyFilterMetrics,
    evaluate_strategy_filters,
)


def _metrics(**overrides: object) -> StrategyFilterMetrics:
    base = {
        "symbol": "SPY",
        "strategy": "breakout_momentum_intraday",
        "session_state": "regular_session",
        "relative_volume": 2.0,
        "average_volume": 1_000_000.0,
        "spread_pct": 0.001,
        "price_vs_vwap_pct": 0.002,
        "candidate_score": 0.75,
        "extended_hours_supported": True,
    }
    base.update(overrides)
    return StrategyFilterMetrics(**base)  # type: ignore[arg-type]


def test_breakout_requires_higher_relative_volume() -> None:
    reasons = evaluate_strategy_filters(
        _metrics(strategy="breakout_momentum_intraday", relative_volume=0.9)
    )

    assert "strategy_relative_volume_below_threshold" in reasons


def test_mean_reversion_scalp_can_ignore_relative_volume() -> None:
    reasons = evaluate_strategy_filters(
        _metrics(strategy="mean_reversion_scalp", relative_volume=0.1)
    )

    assert reasons == ()


def test_vwap_reclaim_uses_lower_relative_volume_threshold() -> None:
    rejected = evaluate_strategy_filters(
        _metrics(strategy="vwap_reclaim_intraday", relative_volume=0.3)
    )
    approved = evaluate_strategy_filters(
        _metrics(strategy="vwap_reclaim_intraday", relative_volume=0.5)
    )

    assert "strategy_relative_volume_below_threshold" in rejected
    assert approved == ()


def test_extended_hours_blocks_unsupported_or_wide_spread() -> None:
    unsupported = evaluate_strategy_filters(
        _metrics(
            session_state="premarket_session",
            extended_hours_supported=False,
        )
    )
    wide_spread = evaluate_strategy_filters(
        _metrics(
            session_state="premarket_session",
            spread_pct=0.025,
        ),
        StrategyFilterConfig(extended_hours_max_spread_pct=0.01),
    )

    assert "extended_hours_unsupported" in unsupported
    assert "extended_hours_spread_too_wide" in wide_spread


def test_overnight_requires_stronger_liquidity() -> None:
    reasons = evaluate_strategy_filters(
        _metrics(
            session_state="overnight_session",
            average_volume=100_000.0,
        )
    )

    assert "overnight_liquidity_too_low" in reasons
