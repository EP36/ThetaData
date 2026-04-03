"""Trading strategy implementations and registry utilities."""

from src.strategies.breakout_momentum import BreakoutMomentumStrategy
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

__all__ = [
    "BreakoutMomentumStrategy",
    "MovingAverageCrossStrategy",
    "MovingAverageCrossoverStrategy",
    "RSIMeanReversionStrategy",
    "VWAPMeanReversionStrategy",
    "create_strategy",
    "get_strategy_class",
    "list_strategies",
    "register_strategy",
]
