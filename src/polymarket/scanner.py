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
    source_key: str = ""
    source_keys: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Market:
    condition_id: str
    question: str
    yes_token: MarketToken
    no_token: MarketToken
    volume_24h: float = 0.0  # 24-hour USDC volume reported by the CLOB API
    market_id: str = ""
    source_keys: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OrderbookSide:
    best_bid: float
    best_ask: float


@dataclass(frozen=True, slots=True)
class MarketOrderbook:
    market: Market
    yes: OrderbookSide
    no: OrderbookSide


_TOKEN_ID_KEYS = ("token_id", "asset_id", "t")


def _as_str(value: Any) -> str:
    """Return a stripped string for logging and identifier comparisons."""
    if value is None:
        return ""
    return str(value).strip()


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _falsey(value: Any) -> bool:
    if isinstance(value, bool):
        return not value
    if isinstance(value, str):
        return value.strip().lower() in {"0", "false", "no", "off"}
    return False


def _field(raw: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in raw:
            return raw[name]
    return None


def _source_keys(raw: dict[str, Any]) -> tuple[str, ...]:
    return tuple(sorted(str(key) for key in raw.keys()))


def _market_id(raw: dict[str, Any]) -> str:
    return _as_str(raw.get("market_id") or raw.get("market") or raw.get("id"))


def _tradability_skip_reason(raw: dict[str, Any]) -> str:
    if _falsey(_field(raw, "active")):
        return "inactive_market"
    if _truthy(_field(raw, "closed")):
        return "closed_market"
    if _truthy(_field(raw, "archived")):
        return "archived_market"
    if _field(raw, "accepting_orders", "acceptingOrders") is not None and _falsey(
        _field(raw, "accepting_orders", "acceptingOrders")
    ):
        return "not_accepting_orders"
    if _field(raw, "enable_order_book", "enableOrderBook") is not None and _falsey(
        _field(raw, "enable_order_book", "enableOrderBook")
    ):
        return "orderbook_disabled"
    return ""


def _log_market_skip(
    *,
    raw: dict[str, Any],
    reason: str,
    token_id: str = "",
    token_side: str = "",
    token_source_key: str = "",
    token_source_keys: tuple[str, ...] = (),
) -> None:
    LOGGER.info(
        "polymarket_market_skip condition_id=%s market_id=%s token_id=%s "
        "token_side=%s token_source_key=%s source_keys=%s token_source_keys=%s "
        "reason=%s",
        _as_str(raw.get("condition_id")),
        _market_id(raw),
        token_id,
        token_side,
        token_source_key,
        _source_keys(raw),
        token_source_keys,
        reason,
    )


def _log_orderbook_skip(
    *,
    market: Market,
    token: MarketToken,
    reason: str,
    error: Exception | None = None,
) -> None:
    LOGGER.warning(
        "polymarket_orderbook_skip condition_id=%s market_id=%s token_id=%s "
        "token_side=%s token_source_key=%s token_source_keys=%s "
        "market_source_keys=%s reason=%s error=%s",
        market.condition_id,
        market.market_id,
        token.token_id,
        token.outcome,
        token.source_key,
        token.source_keys,
        market.source_keys,
        reason,
        error or "none",
    )


def _token_source_key(raw: dict[str, Any]) -> str:
    for key in _TOKEN_ID_KEYS:
        if _as_str(raw.get(key)):
            return key
    return ""


def _extract_token(
    raw: dict[str, Any],
    outcome: str,
    condition_id: str,
    market_id: str,
) -> MarketToken | None:
    """Extract an explicit CLOB token/asset identifier from a token payload."""
    for key in _TOKEN_ID_KEYS:
        token_id = _as_str(raw.get(key))
        if not token_id:
            continue
        if token_id == condition_id:
            return None
        if market_id and token_id == market_id:
            return None
        return MarketToken(
            token_id=token_id,
            outcome=outcome,
            source_key=key,
            source_keys=_source_keys(raw),
        )
    return None


def _parse_market(raw: dict[str, Any]) -> Market | None:
    """Parse one raw API market dict into a Market, or None if invalid."""
    question = _as_str(raw.get("question"))
    if not _BTC_RE.search(question):
        return None

    condition_id = _as_str(raw.get("condition_id"))
    if not condition_id:
        _log_market_skip(raw=raw, reason="missing_condition_id")
        return None

    skip_reason = _tradability_skip_reason(raw)
    if skip_reason:
        _log_market_skip(raw=raw, reason=skip_reason)
        return None

    raw_tokens = raw.get("tokens", [])
    tokens: list[dict[str, Any]] = raw_tokens if isinstance(raw_tokens, list) else []
    yes_raw = next(
        (t for t in tokens if _as_str(t.get("outcome")).lower() == "yes"),
        None,
    )
    no_raw = next(
        (t for t in tokens if _as_str(t.get("outcome")).lower() == "no"),
        None,
    )

    if not yes_raw or not no_raw:
        _log_market_skip(raw=raw, reason="missing_yes_or_no_token")
        return None

    market_id = _market_id(raw)
    yes_token = _extract_token(yes_raw, "Yes", condition_id, market_id)
    no_token = _extract_token(no_raw, "No", condition_id, market_id)

    if yes_token is None:
        _log_market_skip(
            raw=raw,
            reason="invalid_yes_token_id",
            token_id=_as_str(
                yes_raw.get("token_id") or yes_raw.get("asset_id") or yes_raw.get("t")
            ),
            token_side="Yes",
            token_source_key=_token_source_key(yes_raw),
            token_source_keys=_source_keys(yes_raw),
        )
        return None
    if no_token is None:
        _log_market_skip(
            raw=raw,
            reason="invalid_no_token_id",
            token_id=_as_str(
                no_raw.get("token_id") or no_raw.get("asset_id") or no_raw.get("t")
            ),
            token_side="No",
            token_source_key=_token_source_key(no_raw),
            token_source_keys=_source_keys(no_raw),
        )
        return None

    return Market(
        condition_id=condition_id,
        question=question,
        yes_token=yes_token,
        no_token=no_token,
        volume_24h=float(raw.get("volume_24hr", 0.0) or 0.0),
        market_id=market_id,
        source_keys=_source_keys(raw),
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


def _validate_market_tokens(client: ClobClient, market: Market) -> bool:
    """Resolve token IDs to their parent market before asking for orderbooks."""
    try:
        parent = client.fetch_market_by_token(market.yes_token.token_id)
    except Exception as exc:
        _log_orderbook_skip(
            market=market,
            token=market.yes_token,
            reason="token_lookup_failed",
            error=exc,
        )
        return False

    condition_id = _as_str(parent.get("condition_id"))
    primary_token_id = _as_str(parent.get("primary_token_id"))
    secondary_token_id = _as_str(parent.get("secondary_token_id"))

    if not condition_id or not primary_token_id or not secondary_token_id:
        _log_orderbook_skip(
            market=market,
            token=market.yes_token,
            reason="token_lookup_incomplete",
        )
        return False
    if condition_id and condition_id != market.condition_id:
        _log_orderbook_skip(
            market=market,
            token=market.yes_token,
            reason="token_condition_mismatch",
        )
        return False
    if primary_token_id and primary_token_id != market.yes_token.token_id:
        _log_orderbook_skip(
            market=market,
            token=market.yes_token,
            reason="yes_token_not_primary",
        )
        return False
    if secondary_token_id and secondary_token_id != market.no_token.token_id:
        _log_orderbook_skip(
            market=market,
            token=market.no_token,
            reason="no_token_not_secondary",
        )
        return False

    return True


def fetch_market_orderbooks(
    client: ClobClient, markets: list[Market]
) -> list[MarketOrderbook]:
    """Fetch YES and NO orderbooks for each market, skipping on error."""
    result: list[MarketOrderbook] = []

    for market in markets:
        if not _validate_market_tokens(client, market):
            continue

        try:
            yes_raw = client.fetch_orderbook(market.yes_token.token_id)
        except Exception as exc:
            _log_orderbook_skip(
                market=market,
                token=market.yes_token,
                reason="book_fetch_failed",
                error=exc,
            )
            continue

        try:
            no_raw = client.fetch_orderbook(market.no_token.token_id)
        except Exception as exc:
            _log_orderbook_skip(
                market=market,
                token=market.no_token,
                reason="book_fetch_failed",
                error=exc,
            )
            continue

        result.append(
            MarketOrderbook(
                market=market,
                yes=_parse_orderbook_side(yes_raw),
                no=_parse_orderbook_side(no_raw),
            )
        )

    LOGGER.info("polymarket_orderbooks_fetched count=%d", len(result))
    return result
