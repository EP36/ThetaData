"""Coinbase Advanced Trade market-data layer.

Provides a clean, fail-loudly interface for prices and product metadata.
Unlike funding_arb.coinbase_client (which returns 0.0 on errors),
functions here raise MarketDataError so callers always know when data
is unavailable, rather than silently trading on a stale or zero price.

Root-cause fix:
  The old code used {asset}-USDC (e.g. ETH-USDC) which is a thin stablecoin
  pair with unreliable bid/ask data.  This module defaults to {asset}-USD
  (e.g. ETH-USD), the primary liquidity venue on Coinbase Advanced Trade.

Auth:
  Delegates to funding_arb.coinbase_client.get_coinbase_client() — same
  credentials (COINBASE_API_KEY, COINBASE_API_SECRET), same singleton.
"""
from __future__ import annotations

import logging
from typing import Any

LOGGER = logging.getLogger("theta.marketdata.coinbase")


class MarketDataError(RuntimeError):
    """Raised when a price or product cannot be determined."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _require_client() -> Any:
    """Return the Coinbase RESTClient or raise MarketDataError."""
    from funding_arb.coinbase_client import get_coinbase_client
    cb = get_coinbase_client()
    if cb is None:
        raise MarketDataError(
            "coinbase_client_unavailable — "
            "check COINBASE_API_KEY and COINBASE_API_SECRET"
        )
    return cb


def _safe_float(value: Any) -> float:
    """Convert a value to float; return 0.0 on any failure."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_spot_mid_price(asset: str, quote: str = "USD") -> float:
    """Return (best_bid + best_ask) / 2 for the given Coinbase product.

    Attempts three methods in order:
      1. get_best_bid_ask  — most accurate live spread.
      2. product.best_bid / best_ask fields from get_product.
      3. product.price     — last-trade fallback (logs a warning).

    Raises MarketDataError if no usable price is found.

    Args:
        asset: Base currency (e.g. "ETH", "BTC", "SOL").
        quote: Quote currency (default "USD", not "USDC").
    """
    product_id = f"{asset}-{quote}"
    cb = _require_client()

    # --- Method 1: get_best_bid_ask (live spread) ---
    try:
        resp = cb.get_best_bid_ask(product_ids=[product_id])
        for book in getattr(resp, "pricebooks", []) or []:
            if getattr(book, "product_id", "") != product_id:
                continue
            bids = getattr(book, "bids", []) or []
            asks = getattr(book, "asks", []) or []
            if bids and asks:
                bid = _safe_float(getattr(bids[0], "price", None))
                ask = _safe_float(getattr(asks[0], "price", None))
                if bid > 0.0 and ask > 0.0:
                    mid = (bid + ask) / 2.0
                    LOGGER.info(
                        "coinbase_mid product=%s bid=%.6f ask=%.6f "
                        "mid=%.6f method=best_bid_ask",
                        product_id, bid, ask, mid,
                    )
                    return mid
    except Exception as exc:
        LOGGER.warning(
            "coinbase_mid_best_bid_ask_failed product=%s error=%s — "
            "falling back to get_product",
            product_id, exc,
        )

    # --- Methods 2 & 3: get_product ---
    try:
        product = cb.get_product(product_id)
    except Exception as exc:
        raise MarketDataError(
            f"get_product_failed product_id={product_id} error={exc}"
        ) from exc

    # Check product status
    status = getattr(product, "status", "unknown")
    if status not in ("online", "", None, "unknown"):
        raise MarketDataError(
            f"product_not_tradeable product_id={product_id} status={status}"
        )

    # Method 2: best_bid / best_ask from product response
    bid = _safe_float(getattr(product, "best_bid", None))
    ask = _safe_float(getattr(product, "best_ask", None))
    if bid > 0.0 and ask > 0.0:
        mid = (bid + ask) / 2.0
        LOGGER.info(
            "coinbase_mid product=%s bid=%.6f ask=%.6f "
            "mid=%.6f method=get_product_spread",
            product_id, bid, ask, mid,
        )
        return mid

    # Method 3: last-trade price (stale but better than nothing)
    last = _safe_float(getattr(product, "price", None))
    if last > 0.0:
        LOGGER.warning(
            "coinbase_mid product=%s last_trade=%.6f method=last_trade_price "
            "reason=spread_unavailable bid=%s ask=%s — "
            "price may be stale; verify before live trading",
            product_id, last, bid or "n/a", ask or "n/a",
        )
        return last

    raise MarketDataError(
        f"no_price_available product_id={product_id} "
        f"status={status} bid={bid} ask={ask} last_trade={last}"
    )


def get_quote_balance(quote: str = "USD") -> float:
    """Return available balance of the quote currency (e.g. USD or USDC).

    Returns 0.0 on any error rather than raising, so callers can check
    balance availability without crashing the preflight.
    """
    from funding_arb.coinbase_client import get_spot_balance
    bal = get_spot_balance(quote)
    LOGGER.info("coinbase_quote_balance quote=%s balance=%.8f", quote, bal)
    return bal


def validate_product(asset: str, quote: str = "USD") -> str:
    """Confirm the product exists and is tradeable on Coinbase.

    Returns the canonical product_id string (e.g. "ETH-USD").
    Raises MarketDataError if the product is unknown or offline.
    """
    product_id = f"{asset}-{quote}"
    cb = _require_client()
    try:
        product = cb.get_product(product_id)
    except Exception as exc:
        raise MarketDataError(
            f"product_not_found product_id={product_id} error={exc}"
        ) from exc

    status = getattr(product, "status", "unknown")
    if status not in ("online", "", None, "unknown"):
        raise MarketDataError(
            f"product_not_tradeable product_id={product_id} status={status}"
        )

    LOGGER.info(
        "coinbase_product_validated product_id=%s status=%s",
        product_id, status,
    )
    return product_id
