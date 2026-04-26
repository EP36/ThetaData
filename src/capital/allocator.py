"""Capital allocator: composite scoring across polymarket and funding_arb strategies.

Composite score = 0.40 * annualized_edge + 0.30 * exec_confidence
               + 0.20 * capital_efficiency + 0.10 * (1 - lockup_penalty)

Usage:
    from src.capital.allocator import CapitalAllocator, OpportunityScore
    scores = [adapter.opportunity_to_score(o) for o in opps]
    ranked = CapitalAllocator().rank(scores)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

LOGGER = logging.getLogger("theta.capital.allocator")

_ANNUALIZED_CAP   = 500.0   # % — normalize annualized_edge_pct to 0-1 at this cap
_LOCKUP_CAP_HOURS = 720.0   # 30 days — normalize lockup to 0-1 at this cap

_W_ANNUALIZED   = 0.40
_W_CONFIDENCE   = 0.30
_W_EFFICIENCY   = 0.20
_W_LOCKUP       = 0.10


@dataclass
class OpportunityScore:
    source: str             # "polymarket" | "funding_arb"
    strategy: str           # e.g. "orderbook_spread", "correlated_markets", "funding_arb"
    label: str              # human-readable label for logging
    annualized_edge_pct: float   # expected annualised return %
    exec_confidence: float       # 0.0–1.0 probability of successful execution
    capital_efficiency: float    # 0.0–1.0 fraction of deployed capital actively working
    lockup_hours: float          # hours capital is locked (inf = unknown/very long)
    raw_edge_pct: float          # raw edge_pct before annualisation
    composite_score: float = 0.0 # filled by CapitalAllocator.score()
    metadata: dict[str, Any] = field(default_factory=dict)


class CapitalAllocator:
    def score(self, opp: OpportunityScore) -> float:
        ann_norm    = min(opp.annualized_edge_pct / _ANNUALIZED_CAP, 1.0)
        conf_norm   = max(0.0, min(1.0, opp.exec_confidence))
        eff_norm    = max(0.0, min(1.0, opp.capital_efficiency))
        lockup      = opp.lockup_hours if opp.lockup_hours != float("inf") else _LOCKUP_CAP_HOURS
        lockup_norm = min(lockup / _LOCKUP_CAP_HOURS, 1.0)  # higher = longer lockup = worse

        composite = (
            _W_ANNUALIZED * ann_norm
            + _W_CONFIDENCE * conf_norm
            + _W_EFFICIENCY * eff_norm
            + _W_LOCKUP * (1.0 - lockup_norm)
        )
        return round(composite, 6)

    def rank(self, opps: list[OpportunityScore]) -> list[OpportunityScore]:
        scored = []
        for opp in opps:
            import dataclasses
            s = dataclasses.replace(opp, composite_score=self.score(opp))
            scored.append(s)
        scored.sort(key=lambda o: o.composite_score, reverse=True)
        for i, o in enumerate(scored[:5]):
            LOGGER.info(
                "capital_rank rank=%d source=%s strategy=%s label=%.50s "
                "composite=%.4f ann_edge=%.1f%% exec_conf=%.2f lockup_hrs=%.1f",
                i + 1, o.source, o.strategy, o.label,
                o.composite_score, o.annualized_edge_pct, o.exec_confidence,
                o.lockup_hours if o.lockup_hours != float("inf") else -1,
            )
        return scored
