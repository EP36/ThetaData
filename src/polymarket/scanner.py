"""Fetch BTC prediction markets and their orderbooks from Polymarket."""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from src.polymarket.client import ClobClient

LOGGER = logging.getLogger("theta.polymarket.scanner")

_BTC_RE = re.compile(r"\b(bitcoin|btc|crypto)\b", re.IGNORECASE)
_CURSOR_END = "LTE="  # Polymarket's sentinel for the last page

_GAMMA_BASE_URL = "https://gamma-api.polymarket.com"
_GAMMA_PAGE_SIZE = 1000  # server max; ~280ms/page, ~51 pages for 50k markets

_BOOK_CONCURRENCY = 20   # max simultaneous /book requests
_BOOK_TIMEOUT_SEC = 3.0  # per-request timeout; timed-out markets are skipped

# Maps internal skip-reason strings to summary stat keys.
_SKIP_TO_STAT: dict[str, str] = {
    "inactive_market": "skipped_closed",
    "closed_market": "skipped_closed",
    "archived_market": "skipped_archived",
    "not_accepting_orders": "skipped_no_orderbook",
    "orderbook_disabled": "skipped_no_orderbook",
    "missing_yes_or_no_token": "skipped_missing_tokens",
    "wrong_token_format": "skipped_wrong_token_format",
    "invalid_yes_token_id": "skipped_wrong_token_format",
    "invalid_no_token_id": "skipped_wrong_token_format",
    "missing_condition_id": "skipped_malformed",
}

# Candidate outcome label sets for flexible YES/NO matching.
_YES_LABELS = {"yes", "true", "1"}
_NO_LABELS = {"no", "false", "0"}
# Token dict keys tried in order when looking for an outcome label.
_OUTCOME_KEYS = ("outcome", "name", "title", "side")


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


def _outcome_label(token: dict[str, Any]) -> str:
    """Return the first non-empty outcome-like label found in a token dict."""
    for key in _OUTCOME_KEYS:
        val = _as_str(token.get(key))
        if val:
            return val.lower()
    return ""


def _match_yes_no_tokens(
    tokens: list[dict[str, Any]],
    condition_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return (yes_token, no_token) from a list of raw token dicts.

    Tries exact label matching first (yes/no/true/false/1/0), then falls back
    to positional assignment: the first two tokens with distinct string values
    are treated as YES and NO respectively.
    """
    yes_raw: dict[str, Any] | None = None
    no_raw: dict[str, Any] | None = None

    for t in tokens:
        label = _outcome_label(t)
        if label in _YES_LABELS and yes_raw is None:
            yes_raw = t
        elif label in _NO_LABELS and no_raw is None:
            no_raw = t
        if yes_raw and no_raw:
            return yes_raw, no_raw

    if yes_raw and no_raw:
        return yes_raw, no_raw

    # Fallback: positional — first two tokens with distinct non-empty labels
    seen: list[tuple[str, dict[str, Any]]] = []
    for t in tokens:
        label = _outcome_label(t) or repr(t)[:40]
        if not any(label == s for s, _ in seen):
            seen.append((label, t))
        if len(seen) == 2:
            LOGGER.debug(
                "polymarket_token_positional_fallback condition_id=%s "
                "assigned yes=%r no=%r",
                condition_id,
                seen[0][0],
                seen[1][0],
            )
            return seen[0][1], seen[1][1]

    return yes_raw, no_raw


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

    if not tokens:
        LOGGER.warning(
            "polymarket_active_market_no_tokens condition_id=%s "
            "tokens_field_present=%s source_keys=%s",
            condition_id,
            "tokens" in raw,
            _source_keys(raw),
        )
        return None, "missing_yes_or_no_token"

    yes_raw, no_raw = _match_yes_no_tokens(tokens, condition_id)

    if not yes_raw or not no_raw:
        # tokens present but outcome labels don't match expected patterns —
        # log raw structure for the first few occurrences so we can diagnose.
        LOGGER.warning(
            "polymarket_active_market_no_tokens condition_id=%s "
            "tokens_field_present=True token_count=%d source_keys=%s",
            condition_id,
            len(tokens),
            _source_keys(raw),
        )
        LOGGER.debug(
            "polymarket_token_structure_sample condition_id=%s tokens=%s",
            condition_id,
            repr(raw_tokens)[:500],
        )
        return None, "wrong_token_format"

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


def _parse_gamma_market(raw: dict[str, Any]) -> tuple[Market | None, str]:
    """Convert one Gamma API market dict to a Market, or None with a skip reason.

    Gamma field differences from CLOB:
      conditionId   (camelCase, not condition_id)
      clobTokenIds  JSON-serialised array of two token ID strings [yes, no]
      outcomes      JSON-serialised array ["Yes", "No"] — same order as clobTokenIds
      acceptingOrders / enableOrderBook  (camelCase — handled by _tradability_skip_reason)
      volume24hr    (not volume_24hr)
    """
    question = _as_str(raw.get("question"))
    if not _BTC_RE.search(question):
        return None, "not_btc"

    condition_id = _as_str(raw.get("conditionId"))
    if not condition_id:
        LOGGER.warning(
            "polymarket_gamma_market_malformed reason=missing_condition_id "
            "source_keys=%s",
            _source_keys(raw),
        )
        return None, "missing_condition_id"

    skip_reason = _tradability_skip_reason(raw)
    if skip_reason:
        return None, skip_reason

    # clobTokenIds is a JSON-serialised string: '["yes_id", "no_id"]'
    try:
        token_ids: list[str] = json.loads(raw.get("clobTokenIds") or "[]")
    except (json.JSONDecodeError, TypeError):
        token_ids = []

    try:
        outcome_labels: list[str] = json.loads(raw.get("outcomes") or '["Yes","No"]')
    except (json.JSONDecodeError, TypeError):
        outcome_labels = ["Yes", "No"]

    if len(token_ids) < 2:
        LOGGER.warning(
            "polymarket_gamma_no_tokens condition_id=%s token_count=%d",
            condition_id,
            len(token_ids),
        )
        return None, "missing_yes_or_no_token"

    # Map outcome labels to YES/NO indices
    yes_idx: int | None = None
    no_idx: int | None = None
    for i, label in enumerate(outcome_labels):
        lo = str(label).strip().lower()
        if lo in _YES_LABELS and yes_idx is None:
            yes_idx = i
        elif lo in _NO_LABELS and no_idx is None:
            no_idx = i

    # Positional fallback: first token = YES, second = NO
    if yes_idx is None:
        yes_idx = 0
    if no_idx is None:
        no_idx = 1 if len(token_ids) > 1 else 0

    yes_tid = _as_str(token_ids[yes_idx]) if yes_idx < len(token_ids) else ""
    no_tid = _as_str(token_ids[no_idx]) if no_idx < len(token_ids) else ""

    if not yes_tid or not no_tid:
        LOGGER.warning(
            "polymarket_gamma_empty_token_id condition_id=%s yes_idx=%s no_idx=%s",
            condition_id,
            yes_idx,
            no_idx,
        )
        return None, "invalid_yes_token_id"

    yes_token = MarketToken(token_id=yes_tid, outcome="Yes", source_key="clobTokenIds")
    no_token = MarketToken(token_id=no_tid, outcome="No", source_key="clobTokenIds")

    return Market(
        condition_id=condition_id,
        question=question,
        yes_token=yes_token,
        no_token=no_token,
        volume_24h=float(raw.get("volume24hr") or 0.0),
        market_id=_as_str(raw.get("id")),
        source_keys=_source_keys(raw),
    ), ""


def fetch_btc_markets_gamma(timeout_seconds: float = 15.0) -> list[Market]:
    """Fetch active BTC/crypto markets from the Gamma API.

    The Gamma API supports server-side active/closed filters and returns only
    open markets, completing in <1s vs the 5-minute CLOB full-catalog scan.
    Uses offset-based pagination; stops when a page returns fewer than the
    page size.
    """
    markets: list[Market] = []
    stats: dict[str, int] = {
        "total_fetched": 0,
        "skipped_not_btc": 0,
        "skipped_closed": 0,
        "skipped_archived": 0,
        "skipped_no_orderbook": 0,
        "skipped_missing_tokens": 0,
        "skipped_wrong_token_format": 0,
        "skipped_malformed": 0,
        "candidates_retained": 0,
    }
    t0 = time.monotonic()
    offset = 0
    sample_logged = False

    while True:
        from urllib.parse import urlencode
        params = {
            "active": "true",
            "closed": "false",
            "limit": _GAMMA_PAGE_SIZE,
            "offset": offset,
        }
        url = f"{_GAMMA_BASE_URL}/markets?{urlencode(params)}"
        req = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "Trauto/1.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                page: list[dict[str, Any]] = json.loads(resp.read())
        except Exception as exc:
            LOGGER.error("polymarket_gamma_fetch_failed offset=%d error=%s", offset, exc)
            break

        if not isinstance(page, list) or not page:
            break

        stats["total_fetched"] += len(page)

        if not sample_logged and page:
            LOGGER.debug(
                "polymarket_gamma_sample offset=%d raw=%s",
                offset,
                repr(page[0])[:500],
            )
            sample_logged = True

        for raw in page:
            market, reason = _parse_gamma_market(raw)
            if market is not None:
                markets.append(market)
                stats["candidates_retained"] += 1
            elif reason == "not_btc":
                stats["skipped_not_btc"] += 1
            elif reason in ("inactive_market", "closed_market"):
                stats["skipped_closed"] += 1
            elif reason == "archived_market":
                stats["skipped_archived"] += 1
            elif reason in ("not_accepting_orders", "orderbook_disabled"):
                stats["skipped_no_orderbook"] += 1
            elif reason in ("missing_yes_or_no_token",):
                stats["skipped_missing_tokens"] += 1
            elif reason in ("wrong_token_format", "invalid_yes_token_id", "invalid_no_token_id"):
                stats["skipped_wrong_token_format"] += 1
            elif reason in ("missing_condition_id",):
                stats["skipped_malformed"] += 1

        if len(page) < _GAMMA_PAGE_SIZE:
            break

        offset += _GAMMA_PAGE_SIZE

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    LOGGER.info(
        "polymarket_gamma_scan_summary "
        "total_fetched=%d elapsed_ms=%d "
        "skipped_closed=%d skipped_archived=%d skipped_no_orderbook=%d "
        "skipped_missing_tokens=%d skipped_wrong_token_format=%d skipped_malformed=%d "
        "skipped_not_btc=%d candidates_retained=%d",
        stats["total_fetched"],
        elapsed_ms,
        stats["skipped_closed"],
        stats["skipped_archived"],
        stats["skipped_no_orderbook"],
        stats["skipped_missing_tokens"],
        stats["skipped_wrong_token_format"],
        stats["skipped_malformed"],
        stats["skipped_not_btc"],
        stats["candidates_retained"],
    )
    return markets


def fetch_btc_markets(client: ClobClient) -> list[Market]:
    """Fetch all active BTC/crypto markets, handling pagination."""
    markets: list[Market] = []
    stats: dict[str, int] = {
        "total": 0,
        "skipped_closed": 0,
        "skipped_archived": 0,
        "skipped_no_orderbook": 0,
        "skipped_missing_tokens": 0,
        "skipped_wrong_token_format": 0,
        "skipped_malformed": 0,
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
        "polymarket_scan_summary total=%d "
        "skipped_closed=%d skipped_archived=%d skipped_no_orderbook=%d "
        "skipped_missing_tokens=%d skipped_wrong_token_format=%d skipped_malformed=%d "
        "candidates_retained=%d",
        stats["total"],
        stats["skipped_closed"],
        stats["skipped_archived"],
        stats["skipped_no_orderbook"],
        stats["skipped_missing_tokens"],
        stats["skipped_wrong_token_format"],
        stats["skipped_malformed"],
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
    client: ClobClient,
    markets: list[Market],
    validate_tokens: bool = True,
) -> list[MarketOrderbook]:
    """Fetch YES and NO orderbooks for each market in parallel.

    Uses a thread pool (max _BOOK_CONCURRENCY workers) to fire all /book
    requests concurrently.  Each request has a hard _BOOK_TIMEOUT_SEC timeout
    and no retries; markets whose tokens fail or time out are skipped.

    Pass validate_tokens=False for Gamma-sourced markets — bypasses the CLOB
    token-lookup step that rejects them due to primary/secondary ordering
    differences.
    """
    t0 = time.monotonic()

    valid_markets: list[Market] = []
    for market in markets:
        if validate_tokens and not _validate_market_tokens(client, market):
            continue
        valid_markets.append(market)

    # Submit YES and NO fetches for every market simultaneously.
    future_to_info: dict = {}
    with ThreadPoolExecutor(max_workers=_BOOK_CONCURRENCY) as executor:
        for market in valid_markets:
            for side, token in (("yes", market.yes_token), ("no", market.no_token)):
                fut = executor.submit(client.fetch_orderbook, token.token_id, _BOOK_TIMEOUT_SEC)
                future_to_info[fut] = (market, side, token)

        # Collect results as they arrive.
        books: dict[str, dict] = {}  # condition_id -> {market, yes_raw, no_raw}
        for fut in as_completed(future_to_info):
            market, side, token = future_to_info[fut]
            try:
                raw = fut.result()
                entry = books.setdefault(market.condition_id, {"market": market})
                entry[side] = raw
            except Exception as exc:
                _log_orderbook_skip(
                    market=market,
                    token=token,
                    reason="book_fetch_failed",
                    error=exc,
                )

    # Only emit a MarketOrderbook when both sides are present.
    result = [
        MarketOrderbook(
            market=entry["market"],
            yes=_parse_orderbook_side(entry["yes"]),
            no=_parse_orderbook_side(entry["no"]),
        )
        for entry in books.values()
        if "yes" in entry and "no" in entry
    ]

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    LOGGER.info(
        "polymarket_book_fetch_complete markets=%d elapsed_ms=%d",
        len(result),
        elapsed_ms,
    )
    return result
