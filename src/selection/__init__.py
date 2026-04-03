"""Selection package for regime classification and strategy allocation."""

from src.selection.regime import RegimeClassification, classify_regime
from src.selection.selector import (
    GlobalSelectionState,
    SelectionConfig,
    SelectionDecision,
    StrategyCandidate,
    StrategySelector,
    StrategyScore,
    strategy_compatible_regimes,
)

__all__ = [
    "GlobalSelectionState",
    "RegimeClassification",
    "SelectionConfig",
    "SelectionDecision",
    "StrategyCandidate",
    "StrategyScore",
    "StrategySelector",
    "classify_regime",
    "strategy_compatible_regimes",
]
