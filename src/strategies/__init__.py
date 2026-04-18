"""Trading strategy implementations and registry utilities."""

from src.strategies.breakout_momentum import BreakoutMomentumStrategy
from src.strategies.intraday import (
    BreakoutMomentumIntradayStrategy,
    MeanReversionScalpStrategy,
    OpeningRangeBreakoutStrategy,
    PullbackTrendContinuationStrategy,
    VWAPReclaimIntradayStrategy,
)
from src.strategies.moving_average import MovingAverageCrossStrategy
from src.strategies.moving_average_crossover import MovingAverageCrossoverStrategy
from src.strategies.registry import (
    create_strategy,
    get_strategy_class,
    list_strategies,
    register_strategy,
)
from src.strategies.rsi_mean_reversion import RSIMeanReversionStrategy
from src.strategies.vwap_mean_reversion import VWAPMeanReversionStrategy

register_strategy(MovingAverageCrossoverStrategy)
register_strategy(RSIMeanReversionStrategy)
register_strategy(BreakoutMomentumStrategy)
register_strategy(VWAPMeanReversionStrategy)
register_strategy(BreakoutMomentumIntradayStrategy)
register_strategy(OpeningRangeBreakoutStrategy)
register_strategy(VWAPReclaimIntradayStrategy)
register_strategy(PullbackTrendContinuationStrategy)
register_strategy(MeanReversionScalpStrategy)

__all__ = [
    "BreakoutMomentumStrategy",
    "BreakoutMomentumIntradayStrategy",
    "MeanReversionScalpStrategy",
    "MovingAverageCrossStrategy",
    "MovingAverageCrossoverStrategy",
    "OpeningRangeBreakoutStrategy",
    "PullbackTrendContinuationStrategy",
    "RSIMeanReversionStrategy",
    "VWAPReclaimIntradayStrategy",
    "VWAPMeanReversionStrategy",
    "create_strategy",
    "get_strategy_class",
    "list_strategies",
    "register_strategy",
]
