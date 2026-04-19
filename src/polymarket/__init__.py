"""Polymarket CLOB arb scanner with gated execution and position monitoring."""

from src.polymarket.alpaca_signals import BtcSignals, fetch_btc_signals, get_cached_signals
from src.polymarket.config import PolymarketConfig
from src.polymarket.executor import ExecutionResult, execute
from src.polymarket.feedback import FeedbackRecord, load_feedback_records
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
from src.polymarket.signals import (
    classify_direction,
    get_signal_params,
    load_signal_params,
    reload_signal_params,
    score_opportunity,
)
from src.polymarket.tuner import (
    ParamChange,
    RULE_NOTE_TO_PARAM,
    TuningResult,
    apply_proposal,
    check_minimum_data,
    propose_tuning,
    read_proposal,
    reject_proposal,
    write_proposal,
)

__all__ = [
    "BtcSignals",
    "ExecutionResult",
    "FeedbackRecord",
    "Opportunity",
    "ParamChange",
    "PolymarketConfig",
    "PositionRecord",
    "PositionsLedger",
    "RULE_NOTE_TO_PARAM",
    "RiskGuard",
    "TuningResult",
    "apply_proposal",
    "check_minimum_data",
    "check_resolution",
    "classify_direction",
    "close_position",
    "close_reason",
    "compute_unrealized",
    "emit_daily_summary",
    "execute",
    "fetch_btc_signals",
    "get_cached_signals",
    "get_signal_params",
    "load_feedback_records",
    "load_signal_params",
    "make_ledger",
    "monitor_positions",
    "propose_tuning",
    "read_proposal",
    "reject_proposal",
    "reload_signal_params",
    "run_all_scanners",
    "scan",
    "scan_and_execute",
    "score_opportunity",
    "write_proposal",
]
