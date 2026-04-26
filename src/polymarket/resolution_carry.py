"""Resolution carry: buy near-certain YES outcomes close to market resolution.

Strategy: when a market has price >= min_price AND resolves within max_hold_hours,
buying YES yields a high annualized return on a near-riskless position.

Example: YES ask = 0.97, resolves in 4 hours → edge = 1% raw,
         annualized = 1% × (8760/4) = 2190% annualized.
"""
from __future__ import annotations

import logging

from src.polymarket.opportunities import Opportunity, _annualized_edge, _hours_to_resolution
from src.polymarket.scanner import MarketOrderbook

LOGGER = logging.getLogger("theta.polymarket.resolution_carry")

_POLY_FEE_PCT = 0.02


def detect_resolution_carry(
    orderbooks: list[MarketOrderbook],
    min_price: float = 0.95,
    max_hold_hours: float = 48.0,
    min_annualized_edge_pct: float = 50.0,
    fee_pct: float = _POLY_FEE_PCT,
    enabled: bool = True,
) -> list[Opportunity]:
    """Return near-certain YES outcomes close to resolution with high annualized edge.

    Filters:
        price  >= min_price                (default 0.95)
        hours  <= max_hold_hours           (default 48)
        ann_%  >= min_annualized_edge_pct  (default 50%)

    Edge is computed as (net_payout - yes_ask) * 100.
    Annualized edge uses hours_to_resolution as the lockup period.
    """
    if not enabled:
        return []

    net_payout = 1.0 - fee_pct
    opps: list[Opportunity] = []

    for ob in orderbooks:
        hrs = _hours_to_resolution(ob.market.end_date)
        if hrs <= 0 or hrs > max_hold_hours:
            continue

        yes_ask = ob.yes.best_ask
        if yes_ask <= 0 or yes_ask < min_price or yes_ask >= 1.0:
            continue

        edge_pct = (net_payout - yes_ask) * 100.0
        if edge_pct <= 0:
            continue

        ann_edge = _annualized_edge(edge_pct, hrs)
        if ann_edge < min_annualized_edge_pct:
            continue

        LOGGER.info(
            "polymarket_res_carry_opportunity market=%.60s "
            "yes_ask=%.4f edge_pct=%.2f annualized_edge_pct=%.1f "
            "hours_to_resolution=%.1f",
            ob.market.question, yes_ask, edge_pct, ann_edge, hrs,
        )
        opps.append(
            Opportunity(
                strategy="resolution_carry",
                market_question=ob.market.question,
                edge_pct=round(edge_pct, 4),
                action=f"buy YES @ {yes_ask:.4f} (resolves in {hrs:.1f}h)",
                confidence="high" if yes_ask >= 0.97 else "medium",
                notes=(
                    f"yes_ask={yes_ask:.4f} hours_to_resolution={hrs:.1f} "
                    f"edge_pct={edge_pct:.4f} annualized_edge_pct={ann_edge:.1f} "
                    f"fee_pct={fee_pct}"
                ),
                condition_id=ob.market.condition_id,
                yes_token_id=ob.market.yes_token.token_id,
                no_token_id=ob.market.no_token.token_id,
                entry_price_yes=yes_ask,
                entry_price_no=0.0,
                volume_24h=ob.market.volume_24h,
                hours_to_resolution=hrs,
                annualized_edge_pct=round(ann_edge, 2),
            )
        )

    return opps
