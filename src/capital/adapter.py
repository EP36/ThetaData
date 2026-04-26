"""Adapters that convert domain objects to OpportunityScore for the CapitalAllocator."""
from __future__ import annotations

from src.capital.allocator import OpportunityScore

_EXEC_CONF = {"high": 0.90, "medium": 0.60, "low": 0.30}
_CAP_EFF   = {
    "orderbook_spread":  1.00,  # both legs resolve at $1; full capital works
    "correlated_markets": 0.80,  # spread trade; partial exposure
    "cross_market":      0.50,  # cross-venue; execution risk higher
}


def opportunity_to_score(opp: object) -> OpportunityScore:
    """Convert a polymarket Opportunity to an OpportunityScore."""
    ann = getattr(opp, "annualized_edge_pct", 0.0) or getattr(opp, "edge_pct", 0.0)
    return OpportunityScore(
        source="polymarket",
        strategy=opp.strategy,
        label=opp.market_question[:60],
        annualized_edge_pct=ann,
        exec_confidence=_EXEC_CONF.get(opp.confidence, 0.50),
        capital_efficiency=_CAP_EFF.get(opp.strategy, 0.50),
        lockup_hours=getattr(opp, "hours_to_resolution", float("inf")),
        raw_edge_pct=opp.edge_pct,
        metadata={"condition_id": getattr(opp, "condition_id", "")},
    )


def funding_rate_to_score(asset: str, rate: float) -> OpportunityScore:
    """Convert a Hyperliquid funding rate to an OpportunityScore.

    rate is the per-hour funding rate (e.g. 0.0015 for 0.15%/hr).
    """
    annualized = rate * 24.0 * 365.0 * 100.0  # convert to annual %
    return OpportunityScore(
        source="funding_arb",
        strategy="funding_arb",
        label=f"HL {asset} funding arb",
        annualized_edge_pct=annualized,
        exec_confidence=0.85,   # HL execution is reliable
        capital_efficiency=0.90,  # delta-neutral, capital fully working
        lockup_hours=1.0,          # funding paid hourly; can exit any time
        raw_edge_pct=rate * 100.0,
        metadata={"asset": asset},
    )
