"""DepositAcknowledger — polls destination venues until a deposit is confirmed.

After the BridgeExecutor submits an on-chain transaction, funds take time to
arrive at the destination (L2 finality + bridge delay). The acknowledger polls
the destination venue balance and declares the deposit confirmed once the
balance increases by at least the expected amount (with a tolerance buffer).

Usage (called by the orchestrator after a successful bridge submission)::

    from src.capital.deposit_acknowledger import poll_until_confirmed
    confirmed = poll_until_confirmed(
        venue="hyperliquid",
        expected_usd=100.0,
        baseline_usd=200.0,   # balance before bridge
        timeout_sec=1800,     # 30 min max wait
    )

Configuration:
  DEPOSIT_POLL_INTERVAL_SEC  int   default=60    seconds between balance checks
  DEPOSIT_TOLERANCE_PCT      float default=0.02  allow 2% slippage on bridge fees
"""
from __future__ import annotations

import logging
import os
import time
from typing import Callable

LOGGER = logging.getLogger("theta.capital.deposit_acknowledger")


def _probe_fn(venue: str) -> Callable[[], float]:
    """Return a zero-argument callable that returns the current free_usd at venue."""
    if venue == "hyperliquid":
        from src.capital.venue_balance import probe_hyperliquid
        return lambda: probe_hyperliquid().free_usd
    elif venue == "coinbase":
        from src.capital.venue_balance import probe_coinbase
        return lambda: probe_coinbase().free_usd
    elif venue == "polymarket":
        from src.capital.venue_balance import probe_polymarket
        return lambda: probe_polymarket().free_usd
    else:
        raise ValueError(f"unknown venue: {venue}")


def poll_until_confirmed(
    venue: str,
    expected_usd: float,
    baseline_usd: float,
    timeout_sec: int = 1800,
) -> bool:
    """Block (with sleeps) until destination venue balance rises by expected_usd.

    Args:
        venue:        destination venue name
        expected_usd: amount we sent (before bridge fees)
        baseline_usd: balance at destination BEFORE the bridge was initiated
        timeout_sec:  give up after this many seconds (default 30 min)

    Returns:
        True if deposit confirmed, False if timed out.
    """
    poll_interval = int(os.getenv("DEPOSIT_POLL_INTERVAL_SEC", "60"))
    tolerance     = float(os.getenv("DEPOSIT_TOLERANCE_PCT", "0.02"))
    min_arrival   = expected_usd * (1.0 - tolerance)  # allow bridge fees

    probe = _probe_fn(venue)
    deadline = time.time() + timeout_sec
    attempt  = 0

    LOGGER.info(
        "deposit_poll_start venue=%s expected_usd=%.2f baseline_usd=%.2f "
        "min_arrival=%.2f timeout_sec=%d",
        venue, expected_usd, baseline_usd, min_arrival, timeout_sec,
    )

    while time.time() < deadline:
        attempt += 1
        try:
            current = probe()
            delta   = current - baseline_usd
            LOGGER.info(
                "deposit_poll attempt=%d venue=%s current_free=%.2f "
                "delta=%.2f min_arrival=%.2f",
                attempt, venue, current, delta, min_arrival,
            )
            if delta >= min_arrival:
                LOGGER.info(
                    "deposit_confirmed venue=%s delta=%.2f expected=%.2f attempts=%d",
                    venue, delta, expected_usd, attempt,
                )
                return True
        except Exception as exc:
            LOGGER.warning("deposit_poll_error venue=%s attempt=%d error=%s", venue, attempt, exc)

        remaining = int(deadline - time.time())
        LOGGER.debug("deposit_poll_waiting venue=%s remaining_sec=%d", venue, remaining)
        time.sleep(poll_interval)

    LOGGER.error(
        "deposit_poll_timeout venue=%s expected_usd=%.2f timeout_sec=%d attempts=%d",
        venue, expected_usd, timeout_sec, attempt,
    )
    return False
