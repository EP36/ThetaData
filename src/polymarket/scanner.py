"""Fetch BTC prediction markets and their orderbooks from Polymarket."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from src.polymarket.client import ClobClient

LOGGER = logging.getLogger("theta.polymarket.scanner")

_BTC_RE = re.compile(r"\b(bitcoin|btc|crypto)\b", re.IGNORECASE)
_CURSOR_END = "LTE="  # Polymarket's sentinel for the last page


@dataclass(frozen=True, slots=True)
class MarketToken:
    token_id: str
    outcome: str


@dataclass(frozen=True, slots=True)
class Market:
    condition_id: str
    question: str
    yes_token: MarketToken
    no_token: MarketToken
    volume_24h: float = 0.0  # 24-hour USDC volume reported by the CLOB API


@dataclass(frozen=True, slots=True)
class OrderbookSide:
    best_bid: float
    best_ask: float


@dataclass(frozen=True, slots=True)
class MarketOrderbook:
    market: Market
    yes: OrderbookSide
    no: OrderbookSide


def _parse_market(raw: dict[str, Any]) -> Market | None:
    """Parse one raw API market dict into a Market, or None if invalid."""
    question = raw.get("question", "")
    if not _BTC_RE.search(question):
        return None

    tokens: list[dict[str, Any]] = raw.get("tokens", [])
    yes_raw = next((t for t in tokens if t.get("outcome", "").lower() == "yes"), None)
    no_raw = next((t for t in tokens if t.get("outcome", "").lower() == "no"), None)

    if not yes_raw or not no_raw:
        return None

    return Market(
        condition_id=raw.get("condition_id", ""),
        question=question,
        yes_token=MarketToken(token_id=yes_raw["token_id"], outcome="Yes"),
        no_token=MarketToken(token_id=no_raw["token_id"], outcome="No"),
        volume_24h=float(raw.get("volume_24hr", 0.0) or 0.0),
    )


def fetch_btc_markets(client: ClobClient) -> list[Market]:
    """Fetch all active BTC/crypto markets, handling pagination."""
    markets: list[Market] = []
    cursor = ""

    while True:
        response = client.fetch_markets(next_cursor=cursor)
        for raw in response.get("data", []):
            market = _parse_market(raw)
            if market:
                markets.append(market)

        cursor = response.get("next_cursor", "")
        if not cursor or cursor == _CURSOR_END:
            break

    LOGGER.info("polymarket_btc_markets_fetched count=%d", len(markets))
    return markets


def _parse_orderbook_side(raw: dict[str, Any]) -> OrderbookSide:
    """Extract best bid and ask from a raw orderbook response."""
    bids: list[dict[str, Any]] = raw.get("bids", [])
    asks: list[dict[str, Any]] = raw.get("asks", [])
    best_bid = max((float(b["price"]) for b in bids), default=0.0)
    best_ask = min((float(a["price"]) for a in asks), default=1.0)
    return OrderbookSide(best_bid=best_bid, best_ask=best_ask)


def fetch_market_orderbooks(
    client: ClobClient, markets: list[Market]
) -> list[MarketOrderbook]:
    """Fetch YES and NO orderbooks for each market, skipping on error."""
    result: list[MarketOrderbook] = []

    for market in markets:
        try:
            yes_raw = client.fetch_orderbook(market.yes_token.token_id)
            no_raw = client.fetch_orderbook(market.no_token.token_id)
            result.append(
                MarketOrderbook(
                    market=market,
                    yes=_parse_orderbook_side(yes_raw),
                    no=_parse_orderbook_side(no_raw),
                )
            )
        except Exception as exc:
            LOGGER.warning(
                "polymarket_orderbook_skip condition_id=%s error=%s",
                market.condition_id,
                exc,
            )

    LOGGER.info("polymarket_orderbooks_fetched count=%d", len(result))
    return result
