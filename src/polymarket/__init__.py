"""Polymarket CLOB arb scanner with gated execution and position monitoring."""

from src.polymarket.config import PolymarketConfig
from src.polymarket.executor import ExecutionResult, execute
from src.polymarket.monitor import (
    check_resolution,
    close_position,
    close_reason,
    compute_unrealized,
    emit_daily_summary,
    monitor_positions,
)
from src.polymarket.opportunities import Opportunity, run_all_scanners
from src.polymarket.positions import PositionRecord, PositionsLedger, make_ledger
from src.polymarket.risk import RiskGuard
from src.polymarket.runner import scan, scan_and_execute

__all__ = [
    "ExecutionResult",
    "Opportunity",
    "PolymarketConfig",
    "PositionRecord",
    "PositionsLedger",
    "RiskGuard",
    "check_resolution",
    "close_position",
    "close_reason",
    "compute_unrealized",
    "emit_daily_summary",
    "execute",
    "make_ledger",
    "monitor_positions",
    "run_all_scanners",
    "scan",
    "scan_and_execute",
]
