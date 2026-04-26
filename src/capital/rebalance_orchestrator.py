"""RebalanceOrchestrator — ties together scoring, triggering, bridging, and confirmation.

This is the single entry point for the cross-venue capital unification loop.
Call run_rebalance_cycle() from the worker thread on each scan cycle.

Full flow per cycle:
  1. probe_all()              — snapshot free/locked capital at every venue
  2. CapitalAllocator.rank()  — score live opportunities cross-venue
  3. trigger.evaluate()       — find (source, dest) pairs worth rebalancing
  4. For the highest-gap pair:
     a. bridge_executor.execute() — submit on-chain bridge tx (or dry-run)
     b. deposit_acknowledger.poll_until_confirmed() — wait for funds to land
     c. trigger.mark_rebalance_complete() — start cooldown clock
  5. Log final outcome

Safety rails:
  - REBALANCE_DRY_RUN=true (default) — no real transactions ever
  - Only ONE rebalance pair is acted on per cycle (the highest gap)
  - Positions with locked collateral are skipped (free_usd check)
  - Every step is logged with structured keys (grep: rebalance_)

Configuration keys (set in /etc/trauto/env):
  REBALANCE_DRY_RUN         bool   default=true
  REBALANCE_SCORE_GAP       float  default=0.20
  REBALANCE_MIN_USD         float  default=50.0
  REBALANCE_COOLDOWN_SEC    int    default=3600
  DEPOSIT_POLL_TIMEOUT_SEC  int    default=1800
"""
from __future__ import annotations

import logging
import os

from src.capital.allocator import CapitalAllocator, OpportunityScore
from src.capital.venue_balance import probe_all
from src.capital.rebalance_trigger import evaluate, mark_rebalance_complete
from src.capital.bridge_executor import execute as bridge_execute
from src.capital.deposit_acknowledger import poll_until_confirmed

LOGGER = logging.getLogger("theta.capital.rebalance_orchestrator")


def run_rebalance_cycle(
    opportunities: list[OpportunityScore],
    allocator: CapitalAllocator | None = None,
) -> dict:
    """Run one full rebalance evaluation cycle.

    Args:
        opportunities: raw (unscored) OpportunityScore list from all strategy adapters
        allocator:     optional pre-built CapitalAllocator; creates one if None

    Returns:
        dict with keys: triggered, dry_run, source, dest, amount_usd, confirmed, reason
    """
    if allocator is None:
        allocator = CapitalAllocator()

    # 1. Score & rank
    ranked = allocator.rank(opportunities)

    # 2. Snapshot venue balances
    snapshots = probe_all()

    # 3. Evaluate rebalance triggers
    decisions = evaluate(ranked, snapshots)

    if not decisions:
        LOGGER.info("rebalance_cycle_complete triggered=false reason=no_decision_warranted")
        return {"triggered": False, "reason": "no_decision_warranted"}

    # 4. Act on the single highest-gap decision only
    best = decisions[0]
    LOGGER.info(
        "rebalance_best_decision source=%s dest=%s gap=%.4f amount_usd=%.2f dry_run=%s",
        best.source_venue, best.dest_venue, best.score_gap, best.amount_usd, best.dry_run,
    )

    if best.dry_run:
        LOGGER.info(
            "rebalance_dry_run source=%s dest=%s amount_usd=%.2f "
            "source_score=%.4f dest_score=%.4f gap=%.4f",
            best.source_venue, best.dest_venue, best.amount_usd,
            best.source_score, best.dest_score, best.score_gap,
        )
        return {
            "triggered": True,
            "dry_run":   True,
            "source":    best.source_venue,
            "dest":      best.dest_venue,
            "amount_usd": best.amount_usd,
            "confirmed": False,
            "reason":    best.reason,
        }

    # 4a. Execute bridge
    source_snap = snapshots[best.source_venue]
    bridge_result = bridge_execute(
        source_venue=best.source_venue,
        dest_venue=best.dest_venue,
        amount_usd=best.amount_usd,
        dry_run=False,
    )

    if not bridge_result.success:
        LOGGER.error(
            "rebalance_bridge_failed source=%s dest=%s error=%s",
            best.source_venue, best.dest_venue, bridge_result.error,
        )
        return {
            "triggered": True,
            "dry_run":   False,
            "source":    best.source_venue,
            "dest":      best.dest_venue,
            "amount_usd": best.amount_usd,
            "confirmed": False,
            "reason":    f"bridge_failed: {bridge_result.error}",
        }

    LOGGER.info(
        "rebalance_bridge_submitted source=%s dest=%s tx_hashes=%s",
        best.source_venue, best.dest_venue, bridge_result.tx_hashes,
    )

    # 4b. Poll for deposit confirmation
    dest_baseline  = snapshots[best.dest_venue].free_usd
    poll_timeout   = int(os.getenv("DEPOSIT_POLL_TIMEOUT_SEC", "1800"))
    confirmed      = poll_until_confirmed(
        venue=best.dest_venue,
        expected_usd=best.amount_usd,
        baseline_usd=dest_baseline,
        timeout_sec=poll_timeout,
    )

    # 4c. Record cooldown regardless of confirmation (bridge was already submitted)
    mark_rebalance_complete(best.source_venue, best.dest_venue)

    outcome = "confirmed" if confirmed else "timed_out"
    LOGGER.info(
        "rebalance_cycle_complete triggered=true source=%s dest=%s "
        "amount_usd=%.2f bridge_tx=%s deposit=%s",
        best.source_venue, best.dest_venue, best.amount_usd,
        bridge_result.tx_hashes, outcome,
    )

    return {
        "triggered":  True,
        "dry_run":    False,
        "source":     best.source_venue,
        "dest":       best.dest_venue,
        "amount_usd": best.amount_usd,
        "confirmed":  confirmed,
        "tx_hashes":  bridge_result.tx_hashes,
        "reason":     best.reason,
    }
