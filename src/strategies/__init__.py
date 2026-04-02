"""Trading strategy implementations and registry utilities."""

from src.strategies.moving_average import MovingAverageCrossStrategy
from src.strategies.moving_average_crossover import MovingAverageCrossoverStrategy
from src.strategies.registry import (
    create_strategy,
    get_strategy_class,
    list_strategies,
    register_strategy,
)
from src.strategies.rsi_mean_reversion import RSIMeanReversionStrategy

register_strategy(MovingAverageCrossoverStrategy)
register_strategy(RSIMeanReversionStrategy)

__all__ = [
    "MovingAverageCrossStrategy",
    "MovingAverageCrossoverStrategy",
    "RSIMeanReversionStrategy",
    "create_strategy",
    "get_strategy_class",
    "list_strategies",
    "register_strategy",
]
