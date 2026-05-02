"""Thin Coinbase Advanced Trade REST client for basis arb spot execution.

Auth (set in /etc/trauto/env):
  COINBASE_API_KEY    — organizations/xxx/apiKeys/xxx
  COINBASE_API_SECRET — EC private key PEM string

Notes:
  - Spot short selling is NOT available in New York; only long (buy) supported.
  - All functions return 0.0 / empty dict on error and log at debug level.
  - get_coinbase_client() returns None if credentials are missing; callers must
    check for None and fall back gracefully.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

LOGGER = logging.getLogger("theta.fundingarb.coinbase")

_CB_CLIENT: Any = None          # cached RESTClient singleton
_CB_WARNED: bool = False        # log missing-creds warning only once


def get_coinbase_client() -> Any | None:
    """Lazy singleton. Returns None (with one-time warning) if credentials absent."""
    global _CB_CLIENT, _CB_WARNED
    if _CB_CLIENT is not None:
        return _CB_CLIENT

    api_key    = os.getenv("COINBASE_API_KEY", "").strip()
    api_secret = os.getenv("COINBASE_API_SECRET", "").strip()

    if not api_key or not api_secret:
        if not _CB_WARNED:
            LOGGER.warning(
                "coinbase_client_unavailable reason=missing_credentials "
                "set COINBASE_API_KEY and COINBASE_API_SECRET in /etc/trauto/env"
            )
            _CB_WARNED = True
        return None

    try:
        from coinbase.rest import RESTClient
        # Coinbase SDK accepts the PEM key directly
        _CB_CLIENT = RESTClient(api_key=api_key, api_secret=api_secret)
        LOGGER.info("coinbase_client_initialized")
        return _CB_CLIENT
    except Exception as exc:
        LOGGER.warning("coinbase_client_init_failed error=%s", exc)
        return None


def get_spot_mid(asset: str) -> float:
    """Return (best_bid + best_ask) / 2 for asset-USDC on Coinbase. 0.0 on error."""
    cb = get_coinbase_client()
    if cb is None:
        return 0.0
    try:
        product_id = f"{asset}-USDC"
        resp = cb.get_best_bid_ask(product_ids=[product_id])
        books = getattr(resp, "pricebooks", None) or []
        if not books:
            return 0.0
        book = books[0]
        bids = getattr(book, "bids", [])
        asks = getattr(book, "asks", [])
        if not bids or not asks:
            return 0.0
        best_bid = float(bids[0].price)
        best_ask = float(asks[0].price)
        mid = (best_bid + best_ask) / 2.0
        LOGGER.debug("coinbase_spot_mid asset=%s bid=%.4f ask=%.4f mid=%.4f",
                     asset, best_bid, best_ask, mid)
        return mid
    except Exception as exc:
        LOGGER.debug("coinbase_spot_mid_failed asset=%s error=%s", asset, exc)
        return 0.0


def execute_spot_market_buy(asset: str, quote_size_usd: float) -> dict[str, Any]:
    """Place a market buy order for quote_size_usd USDC worth of asset.

    Returns dict with order_id, status, filled_size, avg_fill_price.
    Raises on failure so the caller can handle unhedged-position logic.
    """
    cb = get_coinbase_client()
    if cb is None:
        raise RuntimeError("coinbase_client_unavailable")

    product_id      = f"{asset}-USDC"
    client_order_id = f"trauto-basis-{int(time.time())}"
    order_config    = {
        "market_market_ioc": {"quote_size": f"{quote_size_usd:.2f}"}
    }

    LOGGER.info(
        "coinbase_spot_buy_placing asset=%s product_id=%s size_usd=%.2f client_oid=%s",
        asset, product_id, quote_size_usd, client_order_id,
    )

    try:
        resp = cb.create_order(
            client_order_id=client_order_id,
            product_id=product_id,
            side="BUY",
            order_configuration=order_config,
        )
        if not getattr(resp, "success", False):
            err = getattr(resp, "failure_reason", None) or getattr(resp, "error_response", "unknown")
            raise RuntimeError(f"coinbase_order_rejected reason={err}")

        order_id   = getattr(resp, "order_id", "") or getattr(
            getattr(resp, "success_response", None), "order_id", ""
        )
        result = {
            "order_id":       order_id,
            "status":         "filled",
            "filled_size":    0.0,    # not returned synchronously; poll if needed
            "avg_fill_price": 0.0,
            "client_order_id": client_order_id,
        }
        LOGGER.info(
            "coinbase_spot_buy_placed asset=%s size_usd=%.2f order_id=%s",
            asset, quote_size_usd, order_id,
        )
        return result

    except Exception as exc:
        LOGGER.error(
            "coinbase_spot_buy_failed asset=%s size_usd=%.2f error=%s",
            asset, quote_size_usd, exc,
        )
        raise


def execute_spot_market_sell(asset: str, base_size: float) -> dict[str, Any]:
    """Place a market sell order for base_size units of asset.

    Raises on failure.
    """
    cb = get_coinbase_client()
    if cb is None:
        raise RuntimeError("coinbase_client_unavailable")

    product_id      = f"{asset}-USDC"
    client_order_id = f"trauto-basis-sell-{int(time.time())}"
    order_config    = {
        "market_market_ioc": {"base_size": f"{base_size:.8f}"}
    }

    LOGGER.info(
        "coinbase_spot_sell_placing asset=%s product_id=%s base_size=%.8f client_oid=%s",
        asset, product_id, base_size, client_order_id,
    )

    try:
        resp = cb.create_order(
            client_order_id=client_order_id,
            product_id=product_id,
            side="SELL",
            order_configuration=order_config,
        )
        if not getattr(resp, "success", False):
            err = getattr(resp, "failure_reason", None) or getattr(resp, "error_response", "unknown")
            raise RuntimeError(f"coinbase_order_rejected reason={err}")

        order_id = getattr(resp, "order_id", "") or getattr(
            getattr(resp, "success_response", None), "order_id", ""
        )
        result = {
            "order_id":       order_id,
            "status":         "filled",
            "filled_size":    base_size,
            "avg_fill_price": 0.0,
            "client_order_id": client_order_id,
        }
        LOGGER.info(
            "coinbase_spot_sell_placed asset=%s base_size=%.8f order_id=%s",
            asset, base_size, order_id,
        )
        return result

    except Exception as exc:
        LOGGER.error(
            "coinbase_spot_sell_failed asset=%s base_size=%.8f error=%s",
            asset, base_size, exc,
        )
        raise


def get_spot_balance(currency: str = "USD") -> float:
    """Return available spot balance for a given currency from Coinbase Advanced Trade.

    Walks all pages of get_accounts() (default page size is 49) until the
    matching account is found or the list is exhausted.
    """
    cb = get_coinbase_client()
    if cb is None:
        return 0.0

    target = (currency or "").upper()
    cursor: str | None = None
    page = 0

    while True:
        page += 1
        try:
            kwargs: dict = {"limit": 250}
            if cursor:
                kwargs["cursor"] = cursor
            resp = cb.get_accounts(**kwargs)
        except Exception as exc:
            LOGGER.warning(
                "coinbase_get_accounts_failed currency=%s page=%d "
                "error_type=%s error=%s",
                target, page, type(exc).__name__, exc,
            )
            return 0.0

        accounts = getattr(resp, "accounts", None) or []

        # Diagnostic: log what currencies exist on first page so problems are visible.
        if page == 1:
            found_currencies = [
                str(getattr(a, "currency", "") or "").upper()
                for a in accounts
            ]
            LOGGER.debug(
                "coinbase_get_accounts page=1 count=%d currencies=%s",
                len(accounts), found_currencies,
            )

        for acct in accounts:
            acct_currency = str(getattr(acct, "currency", "") or "").upper()
            if acct_currency != target:
                continue

            available = getattr(acct, "available_balance", None)
            # available_balance may be a typed Balance object, a plain dict,
            # or None if the SDK version doesn't deserialize nested objects.
            if isinstance(available, dict):
                value = available.get("value")
            elif available is not None:
                value = getattr(available, "value", None)
            else:
                # Fallback: try to_dict() on the account itself
                value = None
                try:
                    if hasattr(acct, "to_dict"):
                        d = acct.to_dict()
                        ab = (d.get("available_balance") or {})
                        value = ab.get("value") if isinstance(ab, dict) else None
                except Exception:
                    pass

            try:
                bal = float(value) if value is not None else 0.0
            except (TypeError, ValueError):
                bal = 0.0

            LOGGER.info(
                "coinbase_spot_balance currency=%s balance=%.8f page=%d",
                target, bal, page,
            )
            return bal

        # Check for next page
        has_next = getattr(resp, "has_next", False)
        if not has_next:
            break
        cursor = getattr(resp, "cursor", None) or None
        if not cursor:
            break

    LOGGER.warning(
        "coinbase_spot_balance currency=%s balance=0.00000000 "
        "reason=not_found pages_checked=%d",
        target, page,
    )
    return 0.0
