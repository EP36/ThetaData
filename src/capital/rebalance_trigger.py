"""RebalanceTrigger — decides whether to rebalance capital across venues.

A rebalance is triggered when:
  1. The score gap between the best venue's opportunity and the current
     venue's best opportunity exceeds REBALANCE_SCORE_GAP_THRESHOLD.
  2. The source venue has free capital >= REBALANCE_MIN_USD to move.
  3. No rebalance for this pair has completed within the cooldown window.

This module is read-only (no side-effects). It produces a RebalanceDecision
that the orchestrator acts on.

Configuration (all via env / /etc/trauto/env):
  REBALANCE_SCORE_GAP    float  default=0.20   composite score gap to trigger
  REBALANCE_MIN_USD      float  default=50.0   minimum free USD to bother moving
  REBALANCE_COOLDOWN_SEC int    default=3600   seconds before same pair can retrigger
  REBALANCE_DRY_RUN      bool   default=true   if true, log only — never execute
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

from src.capital.allocator import OpportunityScore
from src.capital.venue_balance import VenueSnapshot

LOGGER = logging.getLogger("theta.capital.rebalance_trigger")

# Cooldown registry: maps (source_venue, dest_venue) -> last_rebalance_epoch
_LAST_REBALANCE: dict[tuple[str, str], float] = {}


@dataclass
class RebalanceDecision:
    should_rebalance: bool
    source_venue: str
    dest_venue: str
    amount_usd: float                       # how much to move
    source_score: float
    dest_score: float
    score_gap: float
    reason: str
    dry_run: bool = True
    metadata: dict = field(default_factory=dict)


def _cfg_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def _cfg_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def _cfg_bool(key: str, default: bool) -> bool:
    return os.getenv(key, str(default)).lower() not in ("false", "0", "no")


def _best_score_for_venue(
    venue: str,
    ranked: list[OpportunityScore],
) -> tuple[float, Optional[OpportunityScore]]:
    """Return (best_composite_score, best_opportunity) for a given venue."""
    venue_opps = [o for o in ranked if o.source == venue]
    if not venue_opps:
        return 0.0, None
    best = max(venue_opps, key=lambda o: o.composite_score)
    return best.composite_score, best


def evaluate(
    ranked_opportunities: list[OpportunityScore],
    venue_snapshots: dict[str, VenueSnapshot],
) -> list[RebalanceDecision]:
    """Evaluate all venue pairs and return a list of triggered RebalanceDecisions.

    Compares every (source, dest) pair where source has free capital and
    dest scores materially better.

    Args:
        ranked_opportunities: output of CapitalAllocator.rank()
        venue_snapshots:      output of venue_balance.probe_all()

    Returns:
        List of RebalanceDecision (may be empty if no rebalance warranted).
    """
    gap_threshold = _cfg_float("REBALANCE_SCORE_GAP", 0.20)
    min_usd       = _cfg_float("REBALANCE_MIN_USD", 50.0)
    cooldown_sec  = _cfg_int("REBALANCE_COOLDOWN_SEC", 3600)
    dry_run       = _cfg_bool("REBALANCE_DRY_RUN", True)
    now           = time.time()

    venues = list(venue_snapshots.keys())
    decisions: list[RebalanceDecision] = []

    for source in venues:
        source_snap = venue_snapshots[source]
        if source_snap.free_usd < min_usd:
            LOGGER.debug(
                "rebalance_skip source=%s reason=insufficient_free_capital "
                "free=%.2f min=%.2f",
                source, source_snap.free_usd, min_usd,
            )
            continue

        src_score, src_opp = _best_score_for_venue(source, ranked_opportunities)

        for dest in venues:
            if dest == source:
                continue

            # Cooldown check
            last = _LAST_REBALANCE.get((source, dest), 0.0)
            if now - last < cooldown_sec:
                remaining = int(cooldown_sec - (now - last))
                LOGGER.debug(
                    "rebalance_skip source=%s dest=%s reason=cooldown remaining_sec=%d",
                    source, dest, remaining,
                )
                continue

            dest_score, dest_opp = _best_score_for_venue(dest, ranked_opportunities)
            gap = dest_score - src_score

            if gap < gap_threshold:
                LOGGER.debug(
                    "rebalance_skip source=%s dest=%s gap=%.4f threshold=%.4f",
                    source, dest, gap, gap_threshold,
                )
                continue

            # How much to move: move enough to roughly equalise opportunity sizes,
            # capped at 80% of source free capital to avoid over-draining.
            move_usd = round(min(source_snap.free_usd * 0.80, source_snap.free_usd), 2)

            reason = (
                f"dest={dest} scores {dest_score:.3f} vs source={source} {src_score:.3f} "
                f"gap={gap:.3f} >= threshold={gap_threshold:.3f}; "
                f"free_usd={source_snap.free_usd:.2f} move_usd={move_usd:.2f}"
            )

            LOGGER.info(
                "rebalance_triggered source=%s dest=%s gap=%.4f "
                "source_score=%.4f dest_score=%.4f move_usd=%.2f dry_run=%s",
                source, dest, gap, src_score, dest_score, move_usd, dry_run,
            )

            decisions.append(RebalanceDecision(
                should_rebalance=True,
                source_venue=source,
                dest_venue=dest,
                amount_usd=move_usd,
                source_score=src_score,
                dest_score=dest_score,
                score_gap=round(gap, 6),
                reason=reason,
                dry_run=dry_run,
                metadata={
                    "source_opp": src_opp.label if src_opp else "none",
                    "dest_opp":   dest_opp.label if dest_opp else "none",
                },
            ))

    # Sort by gap descending — execute the most valuable rebalance first
    decisions.sort(key=lambda d: d.score_gap, reverse=True)
    return decisions


def mark_rebalance_complete(source_venue: str, dest_venue: str) -> None:
    """Record that a rebalance completed so the cooldown clock starts."""
    _LAST_REBALANCE[(source_venue, dest_venue)] = time.time()
    LOGGER.info(
        "rebalance_cooldown_started source=%s dest=%s cooldown_sec=%d",
        source_venue, dest_venue,
        _cfg_int("REBALANCE_COOLDOWN_SEC", 3600),
    )
