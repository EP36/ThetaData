"""Parameter tuner — re-exports from src.polymarket.tuner.

Lifts the tuner out of the Polymarket sub-package so the dashboard API
and any strategy can access it via trauto.signals.tuner.
"""

from __future__ import annotations

from src.polymarket.tuner import (
    RULE_NOTE_TO_PARAM,
    ParamChange,
    TuningResult,
    apply_proposal,
    check_minimum_data,
    propose_tuning,
    read_proposal,
    reject_proposal,
    write_proposal,
)
from src.polymarket.signals import (
    get_signal_params,
    load_signal_params,
    reload_signal_params,
)
from src.polymarket.feedback import FeedbackRecord, load_feedback_records

__all__ = [
    "RULE_NOTE_TO_PARAM",
    "FeedbackRecord",
    "ParamChange",
    "TuningResult",
    "apply_proposal",
    "check_minimum_data",
    "get_signal_params",
    "load_feedback_records",
    "load_signal_params",
    "propose_tuning",
    "read_proposal",
    "reject_proposal",
    "reload_signal_params",
    "write_proposal",
]
