"""Tests for the arb detection functions using mocked market data."""

from __future__ import annotations

import datetime
import logging
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


# ---------------------------------------------------------------------------
# Strategy 4: underround
# ---------------------------------------------------------------------------

def test_underround_detects_asymmetric_arb() -> None:
    # YES_ask=0.20, NO_ask=0.70 → total=0.90 < net_payout=0.98; diff=0.50 > 0.05
    from src.polymarket.underround import detect_underround

    ob = _make_ob(yes_ask=0.20, no_ask=0.70)
    opps = detect_underround([ob], min_edge_pct=1.5)

    assert len(opps) == 1
    assert opps[0].strategy == "underround"
    assert opps[0].edge_pct == pytest.approx(8.0, abs=0.1)
    assert opps[0].confidence == "high"
    assert "0.2000" in opps[0].action
    assert "0.7000" in opps[0].action


def test_underround_skips_symmetric_market() -> None:
    # YES_ask=0.45, NO_ask=0.45 → total=0.90; but abs(0.45-0.45)=0 < 0.05 → skip
    from src.polymarket.underround import detect_underround

    ob = _make_ob(yes_ask=0.45, no_ask=0.45)
    opps = detect_underround([ob], min_edge_pct=1.5)

    assert opps == []


def test_underround_skips_when_disabled() -> None:
    from src.polymarket.underround import detect_underround

    ob = _make_ob(yes_ask=0.20, no_ask=0.70)
    opps = detect_underround([ob], min_edge_pct=1.5, enabled=False)

    assert opps == []


def test_underround_skips_below_min_edge() -> None:
    # YES_ask=0.48, NO_ask=0.50 → total=0.98 == net_payout=0.98 → edge≈0 < 1.5
    from src.polymarket.underround import detect_underround

    ob = _make_ob(yes_ask=0.48, no_ask=0.50)
    opps = detect_underround([ob], min_edge_pct=1.5)

    assert opps == []


def test_underround_respects_max_hold_hours(tmp_path: "Path") -> None:
    # Market resolves in 100h; max_hold_hours=72 → skip
    from src.polymarket.underround import detect_underround

    far_date = (
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=100)
    ).isoformat()
    market = Market(
        condition_id="0xfar",
        question="Will X happen?",
        yes_token=MarketToken(token_id="t-yes", outcome="Yes"),
        no_token=MarketToken(token_id="t-no", outcome="No"),
        end_date=far_date,
    )
    ob = MarketOrderbook(
        market=market,
        yes=OrderbookSide(best_bid=0.15, best_ask=0.20),
        no=OrderbookSide(best_bid=0.65, best_ask=0.70),
    )
    opps = detect_underround([ob], min_edge_pct=1.5, max_hold_hours=72.0)

    assert opps == []


def test_underround_logs_opportunity(caplog: pytest.LogCaptureFixture) -> None:
    from src.polymarket.underround import detect_underround

    ob = _make_ob(yes_ask=0.20, no_ask=0.70)
    with caplog.at_level(logging.INFO, logger="theta.polymarket.underround"):
        detect_underround([ob], min_edge_pct=1.5)

    assert any("polymarket_underround_opportunity" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Strategy 5: resolution carry
# ---------------------------------------------------------------------------

def _make_ob_with_end_date(
    hours_ahead: float,
    yes_ask: float = 0.96,
    yes_bid: float = 0.95,
    no_ask: float = 0.05,
    no_bid: float = 0.03,
) -> MarketOrderbook:
    end_date = (
        datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(hours=hours_ahead)
    ).isoformat()
    market = Market(
        condition_id="0xres",
        question="Will X resolve YES?",
        yes_token=MarketToken(token_id="t-yes-res", outcome="Yes"),
        no_token=MarketToken(token_id="t-no-res", outcome="No"),
        end_date=end_date,
    )
    return MarketOrderbook(
        market=market,
        yes=OrderbookSide(best_bid=yes_bid, best_ask=yes_ask),
        no=OrderbookSide(best_bid=no_bid, best_ask=no_ask),
    )


def test_res_carry_detects_near_maturity_opportunity() -> None:
    # YES_ask=0.96, resolves in 4h → edge=(0.98-0.96)*100=2%, ann=2*(8760/4)=4380%
    from src.polymarket.resolution_carry import detect_resolution_carry

    ob = _make_ob_with_end_date(hours_ahead=4.0, yes_ask=0.96)
    opps = detect_resolution_carry([ob], min_price=0.95, max_hold_hours=48.0, min_annualized_edge_pct=50.0)

    assert len(opps) == 1
    assert opps[0].strategy == "resolution_carry"
    assert opps[0].annualized_edge_pct >= 50.0
    assert opps[0].hours_to_resolution == pytest.approx(4.0, abs=0.1)


def test_res_carry_skips_market_too_far_from_resolution() -> None:
    # Resolves in 100h, max_hold_hours=48 → skip
    from src.polymarket.resolution_carry import detect_resolution_carry

    ob = _make_ob_with_end_date(hours_ahead=100.0, yes_ask=0.96)
    opps = detect_resolution_carry([ob], min_price=0.95, max_hold_hours=48.0, min_annualized_edge_pct=50.0)

    assert opps == []


def test_res_carry_skips_price_below_min() -> None:
    # YES_ask=0.85 < min_price=0.95 → skip
    from src.polymarket.resolution_carry import detect_resolution_carry

    ob = _make_ob_with_end_date(hours_ahead=4.0, yes_ask=0.85, yes_bid=0.84)
    opps = detect_resolution_carry([ob], min_price=0.95, max_hold_hours=48.0, min_annualized_edge_pct=50.0)

    assert opps == []


def test_res_carry_skips_when_annualized_edge_too_low() -> None:
    # YES_ask=0.97, resolves in 2000h → ann_edge very low
    from src.polymarket.resolution_carry import detect_resolution_carry

    ob = _make_ob_with_end_date(hours_ahead=2000.0, yes_ask=0.97)
    opps = detect_resolution_carry([ob], min_price=0.95, max_hold_hours=5000.0, min_annualized_edge_pct=500.0)

    assert opps == []


def test_res_carry_skips_when_disabled() -> None:
    from src.polymarket.resolution_carry import detect_resolution_carry

    ob = _make_ob_with_end_date(hours_ahead=4.0, yes_ask=0.96)
    opps = detect_resolution_carry([ob], min_price=0.95, max_hold_hours=48.0, min_annualized_edge_pct=50.0, enabled=False)

    assert opps == []


def test_res_carry_high_confidence_at_or_above_0_97() -> None:
    # yes_ask=0.97 → edge=(0.98-0.97)*100=1%; 0.97>=0.97 → high confidence
    from src.polymarket.resolution_carry import detect_resolution_carry

    ob = _make_ob_with_end_date(hours_ahead=2.0, yes_ask=0.97, yes_bid=0.96)
    opps = detect_resolution_carry([ob], min_price=0.95, max_hold_hours=48.0, min_annualized_edge_pct=1.0)

    assert len(opps) == 1
    assert opps[0].confidence == "high"


def test_res_carry_logs_opportunity(caplog: pytest.LogCaptureFixture) -> None:
    from src.polymarket.resolution_carry import detect_resolution_carry

    ob = _make_ob_with_end_date(hours_ahead=4.0, yes_ask=0.96)
    with caplog.at_level(logging.INFO, logger="theta.polymarket.resolution_carry"):
        detect_resolution_carry([ob], min_price=0.95, max_hold_hours=48.0, min_annualized_edge_pct=50.0)

    assert any("polymarket_res_carry_opportunity" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Task A: correlated_markets rejection logging
# ---------------------------------------------------------------------------

def test_correlated_markets_buy_price_invalid_logs_rejected_event(
    tmp_path: "Path", caplog: pytest.LogCaptureFixture
) -> None:
    """buy_price=1.0 must log both the invalid event and polymarket_opportunity_rejected."""
    from pathlib import Path
    from unittest.mock import patch

    from src.polymarket.config import PolymarketConfig
    from src.polymarket.executor import _execute_correlated_markets
    from src.polymarket.positions import PositionsLedger

    config = PolymarketConfig(
        api_key="k", api_secret="s", passphrase="p", private_key="pk",
        scan_interval_sec=30, min_edge_pct=1.5,
        clob_base_url="https://clob.polymarket.com",
        kalshi_base_url="https://trading-api.kalshi.com/trade-api/v2",
        max_retries=3, timeout_seconds=15.0,
        max_trade_usdc=200.0, max_positions=5, daily_loss_limit=200.0,
        dry_run=True, min_volume_24h=0.0,
    )
    ledger = PositionsLedger(path=Path(tmp_path) / "positions.json")

    opp = Opportunity(
        strategy="correlated_markets",
        market_question="Will BTC hit $80k? vs Will BTC hit $100k?",
        edge_pct=5.0,
        action="test",
        confidence="high",
        notes="",
        condition_id="0xlow",
        yes_token_id="t-low",
        yes_token_id_2="t-high",
        condition_id_2="0xhigh",
        entry_price_yes=1.0,   # buy_price = 1.0, will be rejected
        entry_price_no=0.60,
        hours_to_resolution=24.0,
    )

    with patch("src.polymarket.executor._check_pol_gas", return_value=True):
        with caplog.at_level(logging.INFO, logger="theta.polymarket.executor"):
            result = _execute_correlated_markets(opp, config, ledger)

    assert result.success is False
    assert result.error == "buy_price_out_of_valid_range"
    msgs = [r.message for r in caplog.records]
    assert any("correlated_markets_buy_price_invalid" in m for m in msgs)
    assert any("polymarket_opportunity_rejected" in m for m in msgs)
    # Verify key fields appear in the rejected log
    rejected = next(m for m in msgs if "polymarket_opportunity_rejected" in m)
    assert "buy_price_out_of_valid_range" in rejected
    assert "edge_pct" in rejected
