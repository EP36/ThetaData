"""Strategy-regime gating rules for new long entries."""

from __future__ import annotations

from dataclasses import dataclass

from src.trading.types import GatedTradeIntent, RiskDecision, TradeIntent


@dataclass(frozen=True, slots=True)
class StrategyGateConfig:
    """Configuration for deterministic strategy gating."""

    allow_rsi_in_bullish: bool = False
    allow_bearish_mean_reversion: bool = False
    bullish_regime_size_multiplier: float = 1.0
    sideways_regime_size_multiplier: float = 0.5
    bearish_regime_size_multiplier: float = 0.0


def gate_trade_intent(
    intent: TradeIntent,
    *,
    config: StrategyGateConfig,
) -> tuple[GatedTradeIntent | None, RiskDecision]:
    """Approve or reject a trade intent based on regime-specific rules."""
    if intent.regime == "unknown":
        return None, RiskDecision.reject("regime_unknown")
    if intent.strategy_id == "moving_average_crossover":
        return None, RiskDecision.reject("strategy_reserved_for_regime_filter")

    if intent.regime == "bullish":
        if intent.strategy_id == "rsi_mean_reversion" and not config.allow_rsi_in_bullish:
            return None, RiskDecision.reject("rsi_blocked_in_bullish_regime")
        if intent.strategy_id not in {
            "breakout_momentum",
            "vwap_mean_reversion",
            "breakout_momentum_intraday",
            "opening_range_breakout",
            "vwap_reclaim_intraday",
            "pullback_trend_continuation",
            "mean_reversion_scalp",
        } and not (
            intent.strategy_id == "rsi_mean_reversion" and config.allow_rsi_in_bullish
        ):
            return None, RiskDecision.reject("strategy_blocked_by_regime")
        multiplier = config.bullish_regime_size_multiplier
    elif intent.regime == "sideways":
        if intent.strategy_id in {"breakout_momentum", "breakout_momentum_intraday", "opening_range_breakout"}:
            return None, RiskDecision.reject("breakout_blocked_in_sideways_regime")
        if intent.strategy_id not in {
            "rsi_mean_reversion",
            "vwap_mean_reversion",
            "vwap_reclaim_intraday",
            "mean_reversion_scalp",
        }:
            return None, RiskDecision.reject("strategy_blocked_by_regime")
        multiplier = config.sideways_regime_size_multiplier
    else:
        if not config.allow_bearish_mean_reversion:
            return None, RiskDecision.reject("long_entries_blocked_in_bearish_regime")
        if intent.strategy_id not in {
            "rsi_mean_reversion",
            "vwap_mean_reversion",
            "mean_reversion_scalp",
        }:
            return None, RiskDecision.reject("mean_reversion_blocked_in_bearish_regime")
        multiplier = config.bearish_regime_size_multiplier

    return (
        GatedTradeIntent(
            symbol=intent.symbol,
            strategy_id=intent.strategy_id,
            side=intent.side,
            entry_price=float(intent.entry_price),
            timestamp=intent.timestamp,
            signal=float(intent.signal),
            regime=intent.regime,
            stop_price=intent.stop_price,
            stop_loss_pct=intent.stop_loss_pct,
            trailing_stop_pct=intent.trailing_stop_pct,
            regime_size_multiplier=float(multiplier),
        ),
        RiskDecision.allow(),
    )
