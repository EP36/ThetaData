"""Strategy-specific intraday filter policy."""

from __future__ import annotations

from dataclasses import dataclass

from src.trading.session import SessionState

EXTENDED_SESSIONS = {
    "premarket_session",
    "afterhours_session",
    "overnight_session",
}


@dataclass(frozen=True, slots=True)
class StrategyFilterMetrics:
    """Market snapshot inputs for strategy-specific filters."""

    symbol: str
    strategy: str
    session_state: SessionState
    relative_volume: float
    average_volume: float
    spread_pct: float | None
    price_vs_vwap_pct: float | None
    candidate_score: float
    extended_hours_supported: bool


@dataclass(frozen=True, slots=True)
class StrategyFilterConfig:
    """Thresholds for strategy-specific filters."""

    breakout_min_relative_volume_regular: float = 1.2
    breakout_min_relative_volume_extended: float = 1.5
    opening_range_min_relative_volume: float = 1.1
    pullback_min_relative_volume: float = 0.6
    vwap_min_relative_volume: float = 0.4
    extended_hours_max_spread_pct: float = 0.01
    overnight_min_average_volume: float = 500_000.0


ALLOWED_SESSIONS_BY_STRATEGY: dict[str, set[SessionState]] = {
    "breakout_momentum": {"regular_session"},
    "moving_average_crossover": {"regular_session"},
    "rsi_mean_reversion": {"regular_session"},
    "vwap_mean_reversion": {"regular_session"},
    "breakout_momentum_intraday": {
        "regular_session",
        "premarket_session",
        "afterhours_session",
        "overnight_session",
    },
    "opening_range_breakout": {"regular_session"},
    "vwap_reclaim_intraday": {
        "regular_session",
        "premarket_session",
        "afterhours_session",
    },
    "pullback_trend_continuation": {
        "regular_session",
        "premarket_session",
        "afterhours_session",
    },
    "mean_reversion_scalp": {
        "regular_session",
        "premarket_session",
        "afterhours_session",
    },
}


def evaluate_strategy_filters(
    metrics: StrategyFilterMetrics,
    config: StrategyFilterConfig | None = None,
) -> tuple[str, ...]:
    """Return strategy-specific rejection reasons for one candidate."""
    cfg = config or StrategyFilterConfig()
    strategy = metrics.strategy.strip()
    session_state = metrics.session_state
    reasons: list[str] = []

    allowed_sessions = ALLOWED_SESSIONS_BY_STRATEGY.get(strategy, {"regular_session"})
    if session_state not in allowed_sessions:
        reasons.append("strategy_session_not_allowed")

    if session_state in EXTENDED_SESSIONS and not metrics.extended_hours_supported:
        reasons.append("extended_hours_unsupported")

    if (
        session_state in EXTENDED_SESSIONS
        and metrics.spread_pct is not None
        and metrics.spread_pct > cfg.extended_hours_max_spread_pct
    ):
        reasons.append("extended_hours_spread_too_wide")

    if (
        session_state == "overnight_session"
        and metrics.average_volume < cfg.overnight_min_average_volume
    ):
        reasons.append("overnight_liquidity_too_low")

    min_relative_volume = _strategy_min_relative_volume(
        strategy=strategy,
        session_state=session_state,
        config=cfg,
    )
    if min_relative_volume is not None and metrics.relative_volume < min_relative_volume:
        reasons.append("strategy_relative_volume_below_threshold")

    return tuple(sorted(set(reasons)))


def _strategy_min_relative_volume(
    *,
    strategy: str,
    session_state: SessionState,
    config: StrategyFilterConfig,
) -> float | None:
    if strategy in {"breakout_momentum", "breakout_momentum_intraday"}:
        if session_state in EXTENDED_SESSIONS:
            return config.breakout_min_relative_volume_extended
        return config.breakout_min_relative_volume_regular
    if strategy == "opening_range_breakout":
        return config.opening_range_min_relative_volume
    if strategy == "pullback_trend_continuation":
        return config.pullback_min_relative_volume
    if strategy in {"vwap_reclaim_intraday", "vwap_mean_reversion"}:
        return config.vwap_min_relative_volume
    return None
