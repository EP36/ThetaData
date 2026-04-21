"""Dashboard aggregator — re-exports src.dashboard.aggregator.

The trauto.dashboard.aggregator namespace provides the unified data
aggregation layer. The implementation lives in src.dashboard.aggregator
and is re-exported here for cleaner imports in new code.
"""

from src.dashboard.aggregator import (
    POLY_PAUSE_FLAG,
    DashboardAggregator,
    is_poly_paused,
    normalize_alpaca_position,
    normalize_poly_position,
    pause_poly_bot,
    poly_bot_status,
    resume_poly_bot,
)

__all__ = [
    "POLY_PAUSE_FLAG",
    "DashboardAggregator",
    "is_poly_paused",
    "normalize_alpaca_position",
    "normalize_poly_position",
    "pause_poly_bot",
    "poly_bot_status",
    "resume_poly_bot",
]
