"""Unified Trauto dashboard — aggregates Alpaca + Polymarket data and serves the API router."""

from src.dashboard.aggregator import (
    DashboardAggregator,
    is_poly_paused,
    normalize_alpaca_position,
    normalize_poly_position,
    pause_poly_bot,
    poly_bot_status,
    resume_poly_bot,
)

__all__ = [
    "DashboardAggregator",
    "is_poly_paused",
    "normalize_alpaca_position",
    "normalize_poly_position",
    "pause_poly_bot",
    "poly_bot_status",
    "resume_poly_bot",
]
