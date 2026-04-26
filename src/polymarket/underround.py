"""Underround arbitrage: detect mutually exclusive outcome sets where sum(YES ask) < 1.0.

On a binary market the two YES tokens are mutually exclusive and exhaustive.
An underround exists when YES_ask_A + YES_ask_B < 1.0 after fees —
buying both guarantees a $1 payout for less than $1 spent.

This is essentially the same signal as orderbook_spread but expressed differently;
it is kept here as a named strategy so the executor can handle it distinctly.
"""
from __future__ import annotations

import logging

from src.polymarket.opportunities import Opportunity, _annualized_edge, _hours_to_resolution
from src.polymarket.scanner import MarketOrderbook

LOGGER = logging.getLogger("theta.polymarket.underround")

_POLY_FEE_PCT = 0.02


def detect_underround(
    orderbooks: list[MarketOrderbook],
    fee_pct: float = _POLY_FEE_PCT,
    min_edge_pct: float = 1.5,
    enabled: bool = True,
    max_hold_hours: float = float("inf"),
) -> list[Opportunity]:
    """Return opportunities where sum(YES ask + NO ask) < net_payout.

    Identical math to orderbook_spread but labelled separately.
    Skips markets already captured by orderbook_spread to avoid duplicates
    by requiring abs(yes_ask - no_ask) >= 0.05 (asymmetric markets only).
    """
    if not enabled:
        return []

    opps: list[Opportunity] = []
    net_payout = 1.0 * (1.0 - fee_pct)

    for ob in orderbooks:
        yes_ask = ob.yes.best_ask
        no_ask  = ob.no.best_ask
        # Skip if either side is missing or obviously stale
        if yes_ask <= 0 or no_ask <= 0:
            continue
        total_cost = yes_ask + no_ask
        edge = (net_payout - total_cost) * 100.0
        if edge < min_edge_pct:
            continue
        # Skip if this looks like an orderbook_spread duplicate (symmetric market)
        if abs(yes_ask - no_ask) < 0.05:
            continue

        hrs = _hours_to_resolution(ob.market.end_date)
        if max_hold_hours < float("inf") and hrs > max_hold_hours:
            continue

        LOGGER.info(
            "polymarket_underround_opportunity market=%.60s "
            "yes_ask=%.4f no_ask=%.4f total_cost=%.4f "
            "edge_pct=%.2f hours_to_resolution=%.1f",
            ob.market.question, yes_ask, no_ask, total_cost, edge,
            hrs if hrs != float("inf") else -1,
        )
        opps.append(
            Opportunity(
                strategy="underround",
                market_question=ob.market.question,
                edge_pct=round(edge, 4),
                action=(
                    f"buy YES @ {yes_ask:.4f} + buy NO @ {no_ask:.4f} "
                    f"(underround sum={total_cost:.4f})"
                ),
                confidence="high" if edge >= 3.0 else "medium",
                notes=(
                    f"yes_ask={yes_ask:.4f} no_ask={no_ask:.4f} "
                    f"total_cost={total_cost:.4f} net_payout={net_payout:.4f} "
                    f"fee_pct={fee_pct}"
                ),
                condition_id=ob.market.condition_id,
                yes_token_id=ob.market.yes_token.token_id,
                no_token_id=ob.market.no_token.token_id,
                entry_price_yes=yes_ask,
                entry_price_no=no_ask,
                volume_24h=ob.market.volume_24h,
                hours_to_resolution=hrs,
                annualized_edge_pct=round(_annualized_edge(edge, hrs), 2),
            )
        )

    return opps
