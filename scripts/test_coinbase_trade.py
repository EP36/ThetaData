#!/usr/bin/env python3
"""One-shot Coinbase spot test trade.

Places a single small market buy (default: ETH, $2 notional) and exits.
Reads credentials from /etc/trauto/env or environment variables.

Usage:
    source .venv/bin/activate
    python -m scripts.test_coinbase_trade                      # ETH buy, $2
    python -m scripts.test_coinbase_trade --asset BTC          # BTC buy, $2
    python -m scripts.test_coinbase_trade --asset ETH --size 5 # ETH buy, $5
    python -m scripts.test_coinbase_trade --dry-run            # price check only, no order

Required env vars in /etc/trauto/env:
    COINBASE_API_KEY    — organizations/xxx/apiKeys/xxx
    COINBASE_API_SECRET — EC private key PEM string (full multi-line value)

Product: {ASSET}-USDC on Coinbase Advanced Trade.
Safety: notional size is hard-capped at $10.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
LOGGER = logging.getLogger("theta.test_coinbase_trade")

MAX_NOTIONAL_USD = 10.0
DEFAULT_ASSET    = "ETH"
DEFAULT_SIZE_USD = 2.0


def _load_env() -> None:
    """Inject /etc/trauto/env into os.environ so coinbase_client picks them up."""
    try:
        with open("/etc/trauto/env") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip()
                    # Don't override values already set in the shell environment
                    if k not in os.environ:
                        os.environ[k] = v
    except FileNotFoundError:
        LOGGER.debug("test_coinbase_trade /etc/trauto/env not found; using os.environ only")


def main() -> int:
    parser = argparse.ArgumentParser(description="One-shot Coinbase spot test trade")
    parser.add_argument("--asset",   default=DEFAULT_ASSET,
                        help="Spot asset to buy (default: ETH; product will be ASSET-USDC)")
    parser.add_argument("--size",    type=float, default=DEFAULT_SIZE_USD,
                        help=f"Notional USDC size (default: {DEFAULT_SIZE_USD}, max: {MAX_NOTIONAL_USD})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch mid price and check balances, but do not place an order")
    args = parser.parse_args()

    # --- Safety cap ---
    if args.size > MAX_NOTIONAL_USD:
        LOGGER.error(
            "test_coinbase_trade_rejected size_usd=%.2f max_notional=%.2f reason=size_exceeds_cap",
            args.size, MAX_NOTIONAL_USD,
        )
        return 1

    # Load /etc/trauto/env into os.environ before importing the client
    _load_env()

    # --- Verify credentials are present before importing client ---
    api_key    = os.environ.get("COINBASE_API_KEY", "").strip()
    api_secret = os.environ.get("COINBASE_API_SECRET", "").strip()

    if not api_key:
        LOGGER.error(
            "test_coinbase_trade_aborted reason=missing_COINBASE_API_KEY "
            "hint=set_COINBASE_API_KEY_in_/etc/trauto/env"
        )
        return 1
    if not api_secret:
        LOGGER.error(
            "test_coinbase_trade_aborted reason=missing_COINBASE_API_SECRET "
            "hint=set_COINBASE_API_SECRET_in_/etc/trauto/env"
        )
        return 1

    LOGGER.info(
        "test_coinbase_trade_starting asset=%s size_usd=%.2f dry_run=%s "
        "api_key=%s",
        args.asset, args.size, args.dry_run,
        api_key[:20] + "...",
    )

    # --- Import client (late, after env is populated) ---
    try:
        from funding_arb.coinbase_client import (
            get_coinbase_client,
            get_spot_mid,
            get_spot_balance,
            execute_spot_market_buy,
        )
    except ImportError as exc:
        LOGGER.error("test_coinbase_trade_aborted reason=import_failed error=%s", exc)
        return 1

    # --- Verify client initialises ---
    cb = get_coinbase_client()
    if cb is None:
        LOGGER.error(
            "test_coinbase_trade_aborted reason=client_init_failed "
            "hint=check_COINBASE_API_KEY_and_COINBASE_API_SECRET_format"
        )
        return 1

    # --- Balance and mid-price preflight ---
    usdc_balance = get_spot_balance("USDC")
    mid          = get_spot_mid(args.asset)

    LOGGER.info(
        "test_coinbase_trade_preflight asset=%s product=%s-USDC "
        "mid_price=%.4f usdc_balance=%.2f size_usd=%.2f",
        args.asset, args.asset, mid, usdc_balance, args.size,
    )

    if mid <= 0:
        LOGGER.error(
            "test_coinbase_trade_aborted reason=mid_price_unavailable asset=%s "
            "hint=check_asset_name_is_valid_Coinbase_product",
            args.asset,
        )
        return 1

    if usdc_balance < args.size:
        LOGGER.error(
            "test_coinbase_trade_aborted reason=insufficient_usdc_balance "
            "available=%.2f required=%.2f asset=%s",
            usdc_balance, args.size, args.asset,
        )
        return 1

    if args.dry_run:
        implied_qty = args.size / mid
        LOGGER.info(
            "test_coinbase_trade_DRY_RUN asset=%s mid_price=%.4f size_usd=%.2f "
            "implied_qty=%.6f usdc_balance=%.2f — no order sent",
            args.asset, mid, args.size, implied_qty, usdc_balance,
        )
        print(
            f"\nDRY RUN — no order sent\n"
            f"  product     : {args.asset}-USDC\n"
            f"  mid price   : ${mid:,.4f}\n"
            f"  size (USDC) : ${args.size:.2f}\n"
            f"  implied qty : {implied_qty:.6f} {args.asset}\n"
            f"  USDC balance: ${usdc_balance:.2f}\n"
        )
        return 0

    # --- Place market buy ---
    try:
        result = execute_spot_market_buy(args.asset, args.size)
    except Exception as exc:
        LOGGER.error(
            "test_coinbase_trade_FAILED asset=%s size_usd=%.2f error=%s",
            args.asset, args.size, exc,
        )
        print(f"\n✗ Order failed: {exc}\n")
        return 1

    order_id        = result.get("order_id", "")
    client_order_id = result.get("client_order_id", "")

    LOGGER.info(
        "test_coinbase_trade_SUCCESS asset=%s size_usd=%.2f "
        "order_id=%s client_order_id=%s",
        args.asset, args.size, order_id, client_order_id,
    )
    print(
        f"\n✓ Order placed\n"
        f"  product         : {args.asset}-USDC\n"
        f"  size (USDC)     : ${args.size:.2f}\n"
        f"  order_id        : {order_id}\n"
        f"  client_order_id : {client_order_id}\n"
        f"\nNote: Coinbase IOC market orders do not return fill details synchronously.\n"
        f"Check your Coinbase account or use the order_id to poll for fill status.\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
