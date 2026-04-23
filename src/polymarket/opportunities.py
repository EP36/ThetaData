"""Arbitrage opportunity detection across three strategies."""

from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

from src.polymarket.scanner import MarketOrderbook

LOGGER = logging.getLogger("theta.polymarket.opportunities")

# Conservative round-trip fee assumptions (applied as % of $1.00 payout)
_POLY_FEE_PCT = 0.02
_KALSHI_FEE_PCT = 0.01

# Minimum fuzzy-match ratio to consider two questions the same market
_FUZZY_MATCH_THRESHOLD = 0.60

# Extracts a USD amount like "$50k", "$100,000", "$1.5M" from a question string
_USD_THRESHOLD_RE = re.compile(
    r"\$([0-9][0-9,]*(?:\.[0-9]+)?)\s*([kKmM]?)\b"
)

# Matches range ("between $X and $Y") questions — excluded from dominance analysis
_BETWEEN_RE = re.compile(r"\bbetween\b", re.IGNORECASE)

# Matches genuine "above/over/exceed/reach/hit/cross" absolute-threshold questions
_ABOVE_RE = re.compile(
    r"\b(above|over|exceed|reach|hit|cross|surpass|break|past)\b", re.IGNORECASE
)

# Requires "bitcoin" or "btc" specifically — filters out crypto-hack and other
# non-BTC markets that passed the broader scanner filter via "crypto"
_BTC_STRICT_RE = re.compile(r"\b(bitcoin|btc)\b", re.IGNORECASE)

# Date extraction from question text.
# Tries month+day+year → month+day → month+year → year-only, in that order.
_MONTHS = (
    "january|february|march|april|may|june|july|august|"
    "september|october|november|december|"
    "jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec"
)
_DATE_MDY_RE = re.compile(
    rf"\b({_MONTHS})[\s,]+(\d{{1,2}})(?:st|nd|rd|th)?[\s,]+(202\d)\b",
    re.IGNORECASE,
)
_DATE_MD_RE = re.compile(
    rf"\b({_MONTHS})[\s,]+(\d{{1,2}})(?:st|nd|rd|th)?\b",
    re.IGNORECASE,
)
_DATE_MY_RE = re.compile(
    rf"\b({_MONTHS})[\s,]+(202\d)\b",
    re.IGNORECASE,
)
_DATE_Y_RE = re.compile(r"\b(202\d)\b")


@dataclass(frozen=True, slots=True)
class Opportunity:
    """A detected arbitrage or mispricing opportunity."""

    # --- Phase 1: scanner fields (required, no defaults) ---
    strategy: str
    market_question: str
    edge_pct: float
    action: str
    confidence: str  # "high" | "medium" | "low"
    notes: str
    # --- Phase 2: execution fields (optional, defaults allow Phase 1 callers to omit) ---
    condition_id: str = ""        # primary market condition_id
    yes_token_id: str = ""        # YES outcome token_id (BUY leg for correlated_markets)
    no_token_id: str = ""         # NO outcome token_id
    entry_price_yes: float = 0.0  # YES best_ask at scan time (buy price for correlated_markets)
    entry_price_no: float = 0.0   # NO best_ask at scan time (sell price for correlated_markets)
    volume_24h: float = 0.0       # 24-hour USDC volume at scan time
    # --- correlated_markets second-leg fields ---
    condition_id_2: str = ""      # sell-leg market condition_id (higher-threshold market)
    yes_token_id_2: str = ""      # sell-leg YES token_id (higher-threshold market)
    # --- Phase 5: signal engine fields (optional, defaults allow Phases 1-4 to omit) ---
    direction: str = ""                # "bullish" | "bearish" | "neutral" (set by signal engine)
    signal_notes: tuple[str, ...] = () # per-rule annotations from score_opportunity()
    confidence_score: float = 0.0      # signal-adjusted float confidence; 0.0 = unscored
    rank_score: float = 0.0            # confidence_score * edge_pct; used for post-signal ranking


# ---------------------------------------------------------------------------
# Strategy 1: orderbook spread
# ---------------------------------------------------------------------------

def detect_orderbook_spread(
    orderbooks: list[MarketOrderbook],
    fee_pct: float = _POLY_FEE_PCT,
    min_edge_pct: float = 1.5,
) -> list[Opportunity]:
    """Flag markets where buying both YES and NO yields a riskless profit.

    Condition: YES_ask + NO_ask + fee < 1.00
    Edge = (1.00 * (1 - fee_pct)) - (YES_ask + NO_ask)
    """
    opps: list[Opportunity] = []

    for ob in orderbooks:
        total_cost = ob.yes.best_ask + ob.no.best_ask
        net_payout = 1.0 * (1.0 - fee_pct)
        edge = (net_payout - total_cost) * 100.0

        if edge >= min_edge_pct:
            opps.append(
                Opportunity(
                    strategy="orderbook_spread",
                    market_question=ob.market.question,
                    edge_pct=round(edge, 4),
                    action=(
                        f"buy YES @ {ob.yes.best_ask:.4f} "
                        f"+ buy NO @ {ob.no.best_ask:.4f}"
                    ),
                    confidence="high" if edge >= 3.0 else "medium",
                    notes=(
                        f"yes_ask={ob.yes.best_ask:.4f} no_ask={ob.no.best_ask:.4f} "
                        f"total_cost={total_cost:.4f} net_payout={net_payout:.4f} "
                        f"fee_pct={fee_pct}"
                    ),
                    condition_id=ob.market.condition_id,
                    yes_token_id=ob.market.yes_token.token_id,
                    no_token_id=ob.market.no_token.token_id,
                    entry_price_yes=ob.yes.best_ask,
                    entry_price_no=ob.no.best_ask,
                    volume_24h=ob.market.volume_24h,
                )
            )

    return opps


# ---------------------------------------------------------------------------
# Strategy 2: cross-market (Polymarket vs Kalshi)
# ---------------------------------------------------------------------------

def _fetch_kalshi_btc_markets(
    kalshi_base_url: str, timeout: float = 15.0
) -> list[dict[str, Any]]:
    """Fetch open BTC-related markets from the Kalshi public API.

    Returns an empty list immediately if KALSHI_API_KEY is not configured,
    avoiding a guaranteed 401 on every scan cycle.
    """
    import os

    if not os.getenv("KALSHI_API_KEY", "").strip():
        return []

    _btc_re = re.compile(r"\b(bitcoin|btc|crypto)\b", re.IGNORECASE)
    try:
        with httpx.Client(timeout=timeout) as http:
            resp = http.get(
                f"{kalshi_base_url}/markets",
                params={"limit": 200, "status": "open"},
            )
        resp.raise_for_status()
        raw_markets: list[dict[str, Any]] = resp.json().get("markets", [])
        return [
            m
            for m in raw_markets
            if _btc_re.search(m.get("title", "") + " " + m.get("subtitle", ""))
        ]
    except Exception as exc:
        LOGGER.warning("kalshi_fetch_failed error=%s", exc)
        return []


def detect_cross_market(
    orderbooks: list[MarketOrderbook],
    kalshi_base_url: str,
    fee_pct_poly: float = _POLY_FEE_PCT,
    fee_pct_kalshi: float = _KALSHI_FEE_PCT,
    min_edge_pct: float = 1.5,
    timeout: float = 15.0,
) -> list[Opportunity]:
    """Flag price discrepancies between Polymarket and Kalshi for matched questions.

    Uses fuzzy string matching (SequenceMatcher) to pair questions across venues.
    Edge = |poly_yes_mid - kalshi_yes_mid| - (fee_poly + fee_kalshi), as %.
    """
    kalshi_markets = _fetch_kalshi_btc_markets(kalshi_base_url, timeout=timeout)
    if not kalshi_markets:
        return []

    total_fees = fee_pct_poly + fee_pct_kalshi
    opps: list[Opportunity] = []

    for ob in orderbooks:
        poly_yes_mid = (ob.yes.best_bid + ob.yes.best_ask) / 2.0
        poly_q = ob.market.question.lower()

        best_match: dict[str, Any] | None = None
        best_score = 0.0

        for km in kalshi_markets:
            kalshi_text = (km.get("title", "") + " " + km.get("subtitle", "")).lower()
            score = difflib.SequenceMatcher(None, poly_q, kalshi_text).ratio()
            if score > best_score:
                best_score = score
                best_match = km

        if best_match is None or best_score < _FUZZY_MATCH_THRESHOLD:
            continue

        kalshi_yes_bid = float(best_match.get("yes_bid", 0.0))
        kalshi_yes_ask = float(best_match.get("yes_ask", 0.0))
        kalshi_yes_mid = (kalshi_yes_bid + kalshi_yes_ask) / 2.0

        price_diff = abs(poly_yes_mid - kalshi_yes_mid)
        edge = (price_diff - total_fees) * 100.0

        if edge >= min_edge_pct:
            if poly_yes_mid < kalshi_yes_mid:
                action = (
                    f"buy YES on Polymarket @ {ob.yes.best_ask:.4f}, "
                    f"sell YES on Kalshi @ {kalshi_yes_bid:.4f}"
                )
            else:
                action = (
                    f"sell YES on Polymarket @ {ob.yes.best_bid:.4f}, "
                    f"buy YES on Kalshi @ {kalshi_yes_ask:.4f}"
                )

            opps.append(
                Opportunity(
                    strategy="cross_market",
                    market_question=ob.market.question,
                    edge_pct=round(edge, 4),
                    action=action,
                    confidence="medium" if best_score >= 0.80 else "low",
                    notes=(
                        f"poly_yes_mid={poly_yes_mid:.4f} "
                        f"kalshi_yes_mid={kalshi_yes_mid:.4f} "
                        f"match_score={best_score:.2f} "
                        f"kalshi_title={best_match.get('title', '')}"
                    ),
                )
            )

    return opps


# ---------------------------------------------------------------------------
# Strategy 3: correlated markets (dominance violation)
# ---------------------------------------------------------------------------

def _extract_question_date(question: str) -> str | None:
    """Return a normalised date string extracted from a question, or None.

    Tries most-to-least specific: Month DD YYYY → Month DD → Month YYYY → YYYY.
    The returned string is lowercase so "December 31 2026" == "december 31 2026".
    Only matches 2020-2029 years to avoid false matches on dollar amounts.
    """
    m = _DATE_MDY_RE.search(question)
    if m:
        return f"{m.group(1).lower()} {m.group(2)} {m.group(3)}"
    m = _DATE_MD_RE.search(question)
    if m:
        return f"{m.group(1).lower()} {m.group(2)}"
    m = _DATE_MY_RE.search(question)
    if m:
        return f"{m.group(1).lower()} {m.group(2)}"
    m = _DATE_Y_RE.search(question)
    if m:
        return m.group(1)
    return None


def _extract_usd_threshold(question: str) -> float | None:
    """Return the numeric USD threshold embedded in a BTC price question, or None."""
    match = _USD_THRESHOLD_RE.search(question)
    if not match:
        return None
    raw = match.group(1).replace(",", "")
    value = float(raw)
    suffix = match.group(2).lower()
    if suffix == "k":
        value *= 1_000.0
    elif suffix == "m":
        value *= 1_000_000.0
    return value


def detect_correlated_markets(
    orderbooks: list[MarketOrderbook],
    min_edge_pct: float = 1.5,
) -> list[Opportunity]:
    """Flag genuine dominance violations among same-date BTC absolute-threshold markets.

    Three guards against false positives, applied at candidate selection:
    1. BTC-only: both questions must contain "bitcoin" or "btc" (not just "crypto").
       Eliminates crypto-hack markets that passed the broader scanner filter.
    2. Absolute-threshold format: no "between $X and $Y" range markets; question
       must contain an "above/hit/reach/exceed" keyword.
    3. Same question-date: date is extracted from the question text itself (not from
       Gamma's endDateIso, which is a max-expiry ceiling shared across unrelated
       markets). Pairs where either question has no extractable date are skipped.
    """
    from collections import defaultdict

    # --- Candidate selection: all three guards applied per market ---
    candidates: list[tuple[float, str, MarketOrderbook]] = []
    for ob in orderbooks:
        q = ob.market.question
        if not _BTC_STRICT_RE.search(q):
            continue  # non-BTC market (crypto-hack etc.) — skip
        if _BETWEEN_RE.search(q):
            continue  # range market — dominance rule doesn't apply
        if not _ABOVE_RE.search(q):
            continue  # no absolute-threshold keyword — skip ambiguous phrasing
        threshold = _extract_usd_threshold(q)
        if threshold is None:
            continue
        date_key = _extract_question_date(q)
        if date_key is None:
            continue  # no date in question — can't verify same-date
        candidates.append((threshold, date_key, ob))

    # --- Group by question-extracted date: only same-date pairs are comparable ---
    by_date: dict[str, list[tuple[float, MarketOrderbook]]] = defaultdict(list)
    for thresh, date_key, ob in candidates:
        by_date[date_key].append((thresh, ob))

    opps: list[Opportunity] = []

    for date_key, group in by_date.items():
        if len(group) < 2:
            continue
        group.sort(key=lambda x: x[0])

        for i in range(len(group) - 1):
            lower_thresh, lower_ob = group[i]
            higher_thresh, higher_ob = group[i + 1]

            lower_yes_mid = (lower_ob.yes.best_bid + lower_ob.yes.best_ask) / 2.0
            higher_yes_mid = (higher_ob.yes.best_bid + higher_ob.yes.best_ask) / 2.0

            if higher_yes_mid > lower_yes_mid:
                edge = (higher_yes_mid - lower_yes_mid) * 100.0
                if edge >= min_edge_pct:
                    opps.append(
                        Opportunity(
                            strategy="correlated_markets",
                            market_question=(
                                f"{lower_ob.market.question} vs {higher_ob.market.question}"
                            ),
                            edge_pct=round(edge, 4),
                            action=(
                                f"sell YES on higher market @ {higher_ob.yes.best_bid:.4f}, "
                                f"buy YES on lower market @ {lower_ob.yes.best_ask:.4f}"
                            ),
                            confidence="high",
                            notes=(
                                f"date={date_key} "
                                f"lower_thresh=${lower_thresh:,.0f} p={lower_yes_mid:.4f} "
                                f"higher_thresh=${higher_thresh:,.0f} p={higher_yes_mid:.4f} "
                                "dominance_violated=true"
                            ),
                            # Execution fields
                            condition_id=lower_ob.market.condition_id,
                            yes_token_id=lower_ob.market.yes_token.token_id,
                            entry_price_yes=lower_ob.yes.best_ask,   # BUY at ask
                            condition_id_2=higher_ob.market.condition_id,
                            yes_token_id_2=higher_ob.market.yes_token.token_id,
                            entry_price_no=higher_ob.yes.best_bid,   # SELL at bid
                        )
                    )

    return opps


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------

def run_all_scanners(
    orderbooks: list[MarketOrderbook],
    kalshi_base_url: str,
    min_edge_pct: float = 1.5,
    timeout: float = 15.0,
) -> list[Opportunity]:
    """Run all three arb scanners and return results sorted by edge_pct descending."""
    opps: list[Opportunity] = []
    opps.extend(detect_orderbook_spread(orderbooks, min_edge_pct=min_edge_pct))
    opps.extend(
        detect_cross_market(
            orderbooks,
            kalshi_base_url=kalshi_base_url,
            min_edge_pct=min_edge_pct,
            timeout=timeout,
        )
    )
    opps.extend(detect_correlated_markets(orderbooks, min_edge_pct=min_edge_pct))
    opps.sort(key=lambda o: o.edge_pct, reverse=True)
    return opps
