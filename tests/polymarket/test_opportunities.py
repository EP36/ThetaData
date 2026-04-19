"""Tests for the three arb detection functions using mocked market data."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.polymarket.opportunities import (
    Opportunity,
    detect_correlated_markets,
    detect_cross_market,
    detect_orderbook_spread,
    run_all_scanners,
)
from src.polymarket.scanner import Market, MarketOrderbook, MarketToken, OrderbookSide


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_token(outcome: str) -> MarketToken:
    return MarketToken(token_id=f"token-{outcome.lower()}", outcome=outcome)


def _make_market(question: str = "Will BTC hit $100k?") -> Market:
    return Market(
        condition_id="0xabc",
        question=question,
        yes_token=_make_token("Yes"),
        no_token=_make_token("No"),
    )


def _make_ob(
    question: str = "Will BTC hit $100k?",
    yes_bid: float = 0.50,
    yes_ask: float = 0.55,
    no_bid: float = 0.42,
    no_ask: float = 0.47,
) -> MarketOrderbook:
    return MarketOrderbook(
        market=_make_market(question),
        yes=OrderbookSide(best_bid=yes_bid, best_ask=yes_ask),
        no=OrderbookSide(best_bid=no_bid, best_ask=no_ask),
    )


# ---------------------------------------------------------------------------
# Strategy 1: orderbook spread
# ---------------------------------------------------------------------------

def test_orderbook_spread_detects_arb_when_cost_below_net_payout() -> None:
    # YES_ask=0.40 + NO_ask=0.40 = 0.80 total cost; net_payout = 0.98 → edge = 18%
    ob = _make_ob(yes_ask=0.40, no_ask=0.40)

    opps = detect_orderbook_spread([ob], min_edge_pct=1.5)

    assert len(opps) == 1
    assert opps[0].strategy == "orderbook_spread"
    assert opps[0].edge_pct == pytest.approx(18.0, abs=0.1)
    assert opps[0].confidence == "high"
    assert "0.4000" in opps[0].action


def test_orderbook_spread_no_arb_when_cost_above_payout() -> None:
    # YES_ask=0.52 + NO_ask=0.52 = 1.04 total cost > 0.98 net payout
    ob = _make_ob(yes_ask=0.52, no_ask=0.52)

    opps = detect_orderbook_spread([ob], min_edge_pct=1.5)

    assert opps == []


def test_orderbook_spread_medium_confidence_for_small_edge() -> None:
    # Edge just above min_edge_pct but below the "high" threshold of 3%
    # net_payout=0.98, total_cost=0.96 → edge=2%
    ob = _make_ob(yes_ask=0.48, no_ask=0.48)

    opps = detect_orderbook_spread([ob], min_edge_pct=1.5)

    assert len(opps) == 1
    assert opps[0].confidence == "medium"


def test_orderbook_spread_respects_min_edge_pct() -> None:
    # Edge = (0.98 - 0.97) * 100 = 1.0% < min_edge_pct=1.5%
    ob = _make_ob(yes_ask=0.485, no_ask=0.485)

    opps = detect_orderbook_spread([ob], min_edge_pct=1.5)

    assert opps == []


def test_orderbook_spread_multiple_markets() -> None:
    ob_arb = _make_ob(question="BTC above $50k?", yes_ask=0.40, no_ask=0.40)
    ob_no_arb = _make_ob(question="BTC above $100k?", yes_ask=0.55, no_ask=0.50)

    opps = detect_orderbook_spread([ob_arb, ob_no_arb], min_edge_pct=1.5)

    assert len(opps) == 1
    assert opps[0].market_question == "BTC above $50k?"


# ---------------------------------------------------------------------------
# Strategy 2: cross-market
# ---------------------------------------------------------------------------

def _kalshi_market(title: str, yes_bid: float, yes_ask: float) -> dict:
    return {"title": title, "subtitle": "", "yes_bid": yes_bid, "yes_ask": yes_ask}


def test_cross_market_flags_price_discrepancy() -> None:
    # Polymarket YES mid = 0.55; Kalshi YES mid = 0.70 → diff = 0.15; fees = 0.03
    ob = _make_ob(question="Will Bitcoin be above 100k by year end?", yes_bid=0.53, yes_ask=0.57)
    kalshi = [_kalshi_market("Will Bitcoin be above $100k by year end?", yes_bid=0.68, yes_ask=0.72)]

    with patch("src.polymarket.opportunities._fetch_kalshi_btc_markets", return_value=kalshi):
        opps = detect_cross_market([ob], kalshi_base_url="http://mock", min_edge_pct=1.5)

    assert len(opps) == 1
    assert opps[0].strategy == "cross_market"
    assert opps[0].edge_pct > 1.5


def test_cross_market_no_opportunity_when_prices_close() -> None:
    # Polymarket YES mid = 0.55; Kalshi YES mid = 0.56 → diff = 0.01 < fees
    ob = _make_ob(question="Will Bitcoin be above 100k?", yes_bid=0.53, yes_ask=0.57)
    kalshi = [_kalshi_market("Will Bitcoin be above $100k?", yes_bid=0.54, yes_ask=0.58)]

    with patch("src.polymarket.opportunities._fetch_kalshi_btc_markets", return_value=kalshi):
        opps = detect_cross_market([ob], kalshi_base_url="http://mock", min_edge_pct=1.5)

    assert opps == []


def test_cross_market_skips_poor_question_match() -> None:
    ob = _make_ob(question="Will BTC hit $100k by end of 2025?")
    kalshi = [_kalshi_market("Will the S&P 500 reach 6000?", yes_bid=0.50, yes_ask=0.55)]

    with patch("src.polymarket.opportunities._fetch_kalshi_btc_markets", return_value=kalshi):
        opps = detect_cross_market([ob], kalshi_base_url="http://mock", min_edge_pct=1.5)

    assert opps == []


def test_cross_market_returns_empty_when_kalshi_unavailable() -> None:
    ob = _make_ob()

    with patch("src.polymarket.opportunities._fetch_kalshi_btc_markets", return_value=[]):
        opps = detect_cross_market([ob], kalshi_base_url="http://mock", min_edge_pct=1.5)

    assert opps == []


def test_cross_market_action_direction_buy_on_poly() -> None:
    # Poly is cheaper → action should say "buy YES on Polymarket"
    ob = _make_ob(question="Will Bitcoin exceed $100k?", yes_bid=0.40, yes_ask=0.45)
    kalshi = [_kalshi_market("Will Bitcoin exceed $100k?", yes_bid=0.68, yes_ask=0.72)]

    with patch("src.polymarket.opportunities._fetch_kalshi_btc_markets", return_value=kalshi):
        opps = detect_cross_market([ob], kalshi_base_url="http://mock", min_edge_pct=1.5)

    assert len(opps) == 1
    assert "buy YES on Polymarket" in opps[0].action


# ---------------------------------------------------------------------------
# Strategy 3: correlated markets
# ---------------------------------------------------------------------------

def test_correlated_markets_flags_dominance_violation() -> None:
    # P(BTC > $50k) = 0.40 < P(BTC > $100k) = 0.60 — impossible, violation
    ob_low = _make_ob(question="Will BTC be above $50k?", yes_bid=0.38, yes_ask=0.42)
    ob_high = _make_ob(question="Will BTC be above $100k?", yes_bid=0.58, yes_ask=0.62)

    opps = detect_correlated_markets([ob_low, ob_high], min_edge_pct=1.5)

    assert len(opps) == 1
    assert opps[0].strategy == "correlated_markets"
    assert opps[0].confidence == "high"
    assert "dominance_violated=true" in opps[0].notes


def test_correlated_markets_no_violation_when_monotonic() -> None:
    # P(BTC > $50k) = 0.70 > P(BTC > $100k) = 0.30 — correct ordering
    ob_low = _make_ob(question="Will BTC be above $50k?", yes_bid=0.68, yes_ask=0.72)
    ob_high = _make_ob(question="Will BTC be above $100k?", yes_bid=0.28, yes_ask=0.32)

    opps = detect_correlated_markets([ob_low, ob_high], min_edge_pct=1.5)

    assert opps == []


def test_correlated_markets_requires_two_threshold_markets() -> None:
    # Only one BTC-threshold market — can't compare
    ob = _make_ob(question="Will BTC be above $50k?", yes_bid=0.68, yes_ask=0.72)

    opps = detect_correlated_markets([ob], min_edge_pct=1.5)

    assert opps == []


def test_correlated_markets_ignores_non_threshold_questions() -> None:
    # Neither question has a USD threshold
    ob1 = _make_ob(question="Will BTC rally this year?")
    ob2 = _make_ob(question="Will Bitcoin be in a bull market?")

    opps = detect_correlated_markets([ob1, ob2], min_edge_pct=1.5)

    assert opps == []


def test_correlated_markets_handles_k_suffix() -> None:
    # "$50k" should parse as 50,000
    ob_low = _make_ob(question="Will BTC be above $50k?", yes_bid=0.38, yes_ask=0.42)
    ob_high = _make_ob(question="Will BTC be above $100k?", yes_bid=0.58, yes_ask=0.62)

    opps = detect_correlated_markets([ob_low, ob_high], min_edge_pct=1.5)

    assert len(opps) == 1
    assert "50,000" in opps[0].notes
    assert "100,000" in opps[0].notes


def test_correlated_markets_edge_below_min_not_returned() -> None:
    # Violation of only 1% < min_edge_pct=1.5%
    ob_low = _make_ob(question="Will BTC be above $50k?", yes_bid=0.488, yes_ask=0.492)
    ob_high = _make_ob(question="Will BTC be above $100k?", yes_bid=0.498, yes_ask=0.502)

    opps = detect_correlated_markets([ob_low, ob_high], min_edge_pct=1.5)

    assert opps == []


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------

def test_run_all_scanners_sorted_by_edge_descending() -> None:
    # Two arb opportunities in the orderbook spread scanner
    ob1 = _make_ob(question="BTC above $50k?", yes_ask=0.40, no_ask=0.40)   # ~18% edge
    ob2 = _make_ob(question="BTC above $60k?", yes_ask=0.47, no_ask=0.47)   # ~4% edge

    with patch("src.polymarket.opportunities._fetch_kalshi_btc_markets", return_value=[]):
        opps = run_all_scanners([ob1, ob2], kalshi_base_url="http://mock", min_edge_pct=1.5)

    assert len(opps) >= 2
    edges = [o.edge_pct for o in opps]
    assert edges == sorted(edges, reverse=True)


def test_run_all_scanners_returns_empty_on_no_opportunities() -> None:
    ob = _make_ob(yes_ask=0.52, no_ask=0.52)  # total cost > net payout

    with patch("src.polymarket.opportunities._fetch_kalshi_btc_markets", return_value=[]):
        opps = run_all_scanners([ob], kalshi_base_url="http://mock", min_edge_pct=1.5)

    assert opps == []
