"""Scan cycle functions — importable by the orchestrator or called from __main__."""

from __future__ import annotations

import logging
import os
from collections import Counter

from src.polymarket.alpaca_signals import get_cached_signals, refresh_btc_signals_if_stale
from src.polymarket.client import ClobClient
from src.polymarket.config import PolymarketConfig
from src.polymarket.executor import ExecutionResult, execute
from src.polymarket.opportunities import Opportunity, run_all_scanners
from src.polymarket.positions import PositionsLedger, make_ledger
from src.polymarket.risk import RiskGuard
from src.polymarket.scanner import fetch_markets_gamma, fetch_market_orderbooks
from src.polymarket.signals import score_opportunity

LOGGER = logging.getLogger("theta.polymarket.runner")

_SIGNAL_INTERVAL_SEC = float(os.getenv("POLY_SIGNAL_INTERVAL_SEC", "300"))


def scan(config: PolymarketConfig) -> list[Opportunity]:
    """Run one full scan cycle and return opportunities found.

    Safe to call from Trauto's main orchestrator without side effects.
    Does not execute any trades.
    """
    client = ClobClient(config=config)

    LOGGER.info("polymarket_scan_start")
    markets = fetch_markets_gamma(timeout_seconds=config.timeout_seconds)

    if not markets:
        LOGGER.info("polymarket_scan_no_markets")
        return []

    orderbooks = fetch_market_orderbooks(client, markets, validate_tokens=False)
    opps = run_all_scanners(
        orderbooks,
        kalshi_base_url=config.kalshi_base_url,
        min_edge_pct=config.min_edge_pct,
        timeout=config.timeout_seconds,
    )

    # Score and re-rank by signal engine
    signals = refresh_btc_signals_if_stale(_SIGNAL_INTERVAL_SEC)
    if signals.data_available:
        opps = [score_opportunity(opp, signals) for opp in opps]
        opps.sort(key=lambda o: o.rank_score, reverse=True)
    # else: order stays by edge_pct (from run_all_scanners)

    # Per-strategy breakdown
    strategy_counts = Counter(o.strategy for o in opps)
    executable_count = strategy_counts.get("orderbook_spread", 0)
    non_executable_count = sum(v for k, v in strategy_counts.items() if k != "orderbook_spread")

    LOGGER.info(
        "polymarket_scan_complete markets=%d opportunities=%d "
        "orderbook_spread=%d non_executable=%d "
        "min_edge_pct=%.2f signals_available=%s",
        len(markets),
        len(opps),
        executable_count,
        non_executable_count,
        config.min_edge_pct,
        signals.data_available,
    )

    if non_executable_count > 0:
        LOGGER.info(
            "polymarket_scan_non_executable_breakdown %s",
            dict(strategy_counts),
        )

    for i, opp in enumerate(opps[:3]):
        LOGGER.info(
            "polymarket_opportunity rank=%d strategy=%s edge_pct=%.4f "
            "confidence=%s rank_score=%.4f direction=%s signal_notes=%s "
            "market=%s action=%s",
            i + 1,
            opp.strategy,
            opp.edge_pct,
            opp.confidence,
            opp.rank_score,
            opp.direction or "unscored",
            " | ".join(opp.signal_notes) or "none",
            opp.market_question[:80],
            opp.action,
        )
    if len(opps) > 3:
        LOGGER.info("polymarket_opportunity_additional count=%d (not shown)", len(opps) - 3)

    return opps


def scan_and_execute(config: PolymarketConfig) -> tuple[list[Opportunity], ExecutionResult | None]:
    """Scan for opportunities, then attempt to execute the top one.

    Returns (opportunities, execution_result). execution_result is None
    if no opportunities were found.
    """
    opps = scan(config)
    if not opps:
        LOGGER.info(
            "polymarket_no_candidates dry_run=%s min_edge_pct=%.2f "
            "— no opportunities passed filters this cycle",
            config.dry_run,
            config.min_edge_pct,
        )
        return opps, None

    ledger: PositionsLedger = make_ledger(config.positions_path)
    risk_guard = RiskGuard(config=config, ledger=ledger)
    top = opps[0]

    LOGGER.info(
        "polymarket_attempting_execution strategy=%s edge_pct=%.4f "
        "confidence=%s dry_run=%s",
        top.strategy,
        top.edge_pct,
        top.confidence,
        config.dry_run,
    )

    result = execute(top, config=config, risk_guard=risk_guard, ledger=ledger)
    LOGGER.info(
        "polymarket_execute_result strategy=%s success=%s size_usdc=%.2f error=%s",
        top.strategy,
        result.success,
        result.size_usdc,
        result.error or "none",
    )
    if result.success:
        ledger.record_fill(
            strategy=top.strategy,
            market=top.market_question,
            side=top.direction or "BUY",
            size_usdc=result.size_usdc,
            edge_pct=top.edge_pct,
        )
    return opps, result
