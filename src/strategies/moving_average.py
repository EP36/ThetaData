"""Backward-compatible import shim for moving average strategy."""

from src.strategies.moving_average_crossover import MovingAverageCrossoverStrategy

# Backward compatibility alias used by earlier scaffold/tests.
MovingAverageCrossStrategy = MovingAverageCrossoverStrategy

__all__ = ["MovingAverageCrossoverStrategy", "MovingAverageCrossStrategy"]
