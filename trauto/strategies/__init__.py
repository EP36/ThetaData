"""Strategy registry — all strategy implementations."""

from trauto.strategies.base import (
    BaseStrategy,
    RiskParams,
    ScheduleType,
    Signal,
    StrategySchedule,
    StrategyStatus,
)

__all__ = [
    "BaseStrategy",
    "RiskParams",
    "ScheduleType",
    "Signal",
    "StrategySchedule",
    "StrategyStatus",
]


def load_all_strategies() -> dict[str, type[BaseStrategy]]:
    """Return a registry of all known strategy classes, keyed by name."""
    from trauto.strategies.alpaca.momentum import MomentumStrategy
    from trauto.strategies.alpaca.mean_revert import MeanReversionStrategy
    from trauto.strategies.polymarket.arb_scanner import ArbScannerStrategy
    from trauto.strategies.polymarket.cross_market import CrossMarketStrategy
    from trauto.strategies.polymarket.correlated import CorrelatedMarketsStrategy

    return {
        MomentumStrategy.name: MomentumStrategy,
        MeanReversionStrategy.name: MeanReversionStrategy,
        ArbScannerStrategy.name: ArbScannerStrategy,
        CrossMarketStrategy.name: CrossMarketStrategy,
        CorrelatedMarketsStrategy.name: CorrelatedMarketsStrategy,
    }
