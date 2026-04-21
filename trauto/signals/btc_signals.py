"""BTC signal engine — re-exports from src.polymarket.alpaca_signals.

This module lifts the BTC signal engine out of the Polymarket sub-package
so it can be used by any strategy or the engine itself.

All computation lives in src.polymarket.alpaca_signals. This module is a
clean re-export layer that gives the new trauto.* namespace access without
duplicating code.
"""

from __future__ import annotations

# Re-export the full public API
from src.polymarket.alpaca_signals import (
    BtcSignals,
    fetch_btc_signals,
    get_cached_signals,
    refresh_btc_signals_if_stale,
)

__all__ = [
    "BtcSignals",
    "fetch_btc_signals",
    "get_cached_signals",
    "refresh_btc_signals_if_stale",
]
