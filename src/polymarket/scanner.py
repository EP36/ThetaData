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

# Maps internal skip-reason strings to summary stat keys.
_SKIP_TO_STAT: dict[str, str] = {
    "inactive_market": "skipped_closed",
    "closed_market": "skipped_closed",
    "archived_market": "skipped_archived",
    "not_accepting_orders": "skipped_no_orderbook",
    "orderbook_disabled": "skipped_no_orderbook",
    "missing_yes_or_no_token": "skipped_no_tokens",
    "invalid_yes_token_id": "skipped_no_tokens",
    "invalid_no_token_id": "skipped_no_tokens",
    "missing_condition_id": "skipped_no_tokens",
}


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


def _parse_market(raw: dict[str, Any]) -> tuple[Market | None, str]:
    """Parse one raw API market dict into a Market, or None with a skip reason.

    Returns ("", "") on non-BTC markets (caller ignores them for stats).
    Logs WARNING only for active markets that pass tradability checks but fail
    token extraction — these indicate unexpected API payload shapes.
    """
    question = _as_str(raw.get("question"))
    if not _BTC_RE.search(question):
        return None, "not_btc"

    condition_id = _as_str(raw.get("condition_id"))
    if not condition_id:
        LOGGER.warning(
            "polymarket_market_malformed reason=missing_condition_id source_keys=%s",
            _source_keys(raw),
        )
        return None, "missing_condition_id"

    skip_reason = _tradability_skip_reason(raw)
    if skip_reason:
        # Routine closed/archived/no-orderbook markets — counted in summary only.
        return None, skip_reason

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
        # Active market missing expected token fields — log for investigation.
        LOGGER.warning(
            "polymarket_active_market_no_tokens condition_id=%s source_keys=%s",
            condition_id,
            _source_keys(raw),
        )
        return None, "missing_yes_or_no_token"

    market_id = _market_id(raw)
    yes_token = _extract_token(yes_raw, "Yes", condition_id, market_id)
    no_token = _extract_token(no_raw, "No", condition_id, market_id)

    if yes_token is None:
        # Malformed token payload — log for investigation.
        LOGGER.warning(
            "polymarket_invalid_token_id condition_id=%s side=Yes "
            "token_id=%s token_source_key=%s token_source_keys=%s source_keys=%s",
            condition_id,
            _as_str(yes_raw.get("token_id") or yes_raw.get("asset_id") or yes_raw.get("t")),
            _token_source_key(yes_raw),
            _source_keys(yes_raw),
            _source_keys(raw),
        )
        return None, "invalid_yes_token_id"

    if no_token is None:
        LOGGER.warning(
            "polymarket_invalid_token_id condition_id=%s side=No "
            "token_id=%s token_source_key=%s token_source_keys=%s source_keys=%s",
            condition_id,
            _as_str(no_raw.get("token_id") or no_raw.get("asset_id") or no_raw.get("t")),
            _token_source_key(no_raw),
            _source_keys(no_raw),
            _source_keys(raw),
        )
        return None, "invalid_no_token_id"

    return Market(
        condition_id=condition_id,
        question=question,
        yes_token=yes_token,
        no_token=no_token,
        volume_24h=float(raw.get("volume_24hr", 0.0) or 0.0),
        market_id=market_id,
        source_keys=_source_keys(raw),
    ), ""


def fetch_btc_markets(client: ClobClient) -> list[Market]:
    """Fetch all active BTC/crypto markets, handling pagination."""
    markets: list[Market] = []
    stats: dict[str, int] = {
        "total": 0,
        "skipped_closed": 0,
        "skipped_archived": 0,
        "skipped_no_orderbook": 0,
        "skipped_no_tokens": 0,
        "candidates_retained": 0,
    }
    cursor = ""

    while True:
        response = client.fetch_markets(next_cursor=cursor)
        for raw in response.get("data", []):
            stats["total"] += 1
            market, reason = _parse_market(raw)
            if market is not None:
                markets.append(market)
                stats["candidates_retained"] += 1
            elif reason and reason != "not_btc":
                stat_key = _SKIP_TO_STAT.get(reason)
                if stat_key:
                    stats[stat_key] += 1

        cursor = response.get("next_cursor", "")
        if not cursor or cursor == _CURSOR_END:
            break

    LOGGER.info(
        "polymarket_scan_summary total=%d skipped_closed=%d skipped_archived=%d "
        "skipped_no_orderbook=%d skipped_no_tokens=%d candidates_retained=%d",
        stats["total"],
        stats["skipped_closed"],
        stats["skipped_archived"],
        stats["skipped_no_orderbook"],
        stats["skipped_no_tokens"],
        stats["candidates_retained"],
    )
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
