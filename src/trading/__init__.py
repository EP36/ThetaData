"""Additive trading controls for gating, sizing, and entry risk."""

from src.trading.gating import StrategyGateConfig, gate_trade_intent
from src.trading.regime import MarketRegimeEvaluation, get_market_regime
from src.trading.risk_policy import RiskPolicyConfig, evaluate_risk_policy
from src.trading.sizing import PositionSizingConfig, calculate_position_size
from src.trading.types import (
    GatedTradeIntent,
    MarketRegime,
    RiskDecision,
    RiskRejectionReason,
    SizedTradeIntent,
    StrategyId,
    TradeIntent,
    TradingRiskState,
    normalize_strategy_id,
)

__all__ = [
    "calculate_position_size",
    "evaluate_risk_policy",
    "gate_trade_intent",
    "get_market_regime",
    "GatedTradeIntent",
    "MarketRegime",
    "MarketRegimeEvaluation",
    "PositionSizingConfig",
    "RiskDecision",
    "RiskPolicyConfig",
    "RiskRejectionReason",
    "SizedTradeIntent",
    "StrategyGateConfig",
    "StrategyId",
    "TradeIntent",
    "TradingRiskState",
    "normalize_strategy_id",
]
