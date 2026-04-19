"""Scan cycle functions — importable by the orchestrator or called from __main__."""

from __future__ import annotations

import logging

from src.polymarket.client import ClobClient
from src.polymarket.config import PolymarketConfig
from src.polymarket.executor import ExecutionResult, execute
from src.polymarket.opportunities import Opportunity, run_all_scanners
from src.polymarket.positions import PositionsLedger, make_ledger
from src.polymarket.risk import RiskGuard
from src.polymarket.scanner import fetch_btc_markets, fetch_market_orderbooks

LOGGER = logging.getLogger("theta.polymarket.runner")


def scan(config: PolymarketConfig) -> list[Opportunity]:
    """Run one full scan cycle and return opportunities found.

    Safe to call from Trauto's main orchestrator without side effects.
    Does not execute any trades.
    """
    client = ClobClient(config=config)

    LOGGER.info("polymarket_scan_start")
    markets = fetch_btc_markets(client)

    if not markets:
        LOGGER.info("polymarket_scan_no_markets")
        return []

    orderbooks = fetch_market_orderbooks(client, markets)
    opps = run_all_scanners(
        orderbooks,
        kalshi_base_url=config.kalshi_base_url,
        min_edge_pct=config.min_edge_pct,
        timeout=config.timeout_seconds,
    )

    LOGGER.info(
        "polymarket_scan_complete markets=%d opportunities=%d",
        len(markets),
        len(opps),
    )

    for opp in opps:
        LOGGER.info(
            "polymarket_opportunity strategy=%s edge_pct=%.4f confidence=%s "
            "market=%s action=%s notes=%s",
            opp.strategy,
            opp.edge_pct,
            opp.confidence,
            opp.market_question[:80],
            opp.action,
            opp.notes,
        )

    return opps


def scan_and_execute(config: PolymarketConfig) -> tuple[list[Opportunity], ExecutionResult | None]:
    """Scan for opportunities, then attempt to execute the top one.

    Returns (opportunities, execution_result). execution_result is None
    if no opportunities were found.
    """
    opps = scan(config)
    if not opps:
        return opps, None

    ledger: PositionsLedger = make_ledger(config.positions_path)
    risk_guard = RiskGuard(config=config, ledger=ledger)
    top = opps[0]

    result = execute(top, config=config, risk_guard=risk_guard, ledger=ledger)
    LOGGER.info(
        "polymarket_execute_result strategy=%s success=%s size_usdc=%.2f error=%s",
        top.strategy,
        result.success,
        result.size_usdc,
        result.error or "none",
    )
    return opps, result
