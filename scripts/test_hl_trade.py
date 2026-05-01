#!/usr/bin/env python3
"""One-shot Hyperliquid test trade.

Places a single small perp short (default: ETH, $2 notional) and exits.
Reads credentials from /etc/trauto/env or environment variables.

Usage:
    source .venv/bin/activate
    python -m scripts.test_hl_trade                      # ETH perp short, $2
    python -m scripts.test_hl_trade --asset BTC          # BTC perp short, $2
    python -m scripts.test_hl_trade --asset ETH --size 5 # ETH perp short, $5
    python -m scripts.test_hl_trade --side long          # ETH spot long, $2
    python -m scripts.test_hl_trade --dry-run            # simulate, no order sent

Required env vars in /etc/trauto/env:
    HL_PRIVATE_KEY   — Ethereum private key (hex, with or without 0x prefix)
    HL_WALLET        — Ethereum wallet address (checksummed)

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
LOGGER = logging.getLogger("theta.test_hl_trade")

MAX_NOTIONAL_USD = 10.0
DEFAULT_ASSET    = "ETH"
DEFAULT_SIZE_USD = 2.0


def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    try:
        with open("/etc/trauto/env") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    except FileNotFoundError:
        LOGGER.debug("test_hl_trade /etc/trauto/env not found; using os.environ only")
    env.update({k: v for k, v in os.environ.items()})
    return env


def main() -> int:
    parser = argparse.ArgumentParser(description="One-shot Hyperliquid test trade")
    parser.add_argument("--asset",   default=DEFAULT_ASSET, help="Perp asset (default: ETH)")
    parser.add_argument("--size",    type=float, default=DEFAULT_SIZE_USD,
                        help=f"Notional USD size (default: {DEFAULT_SIZE_USD}, max: {MAX_NOTIONAL_USD})")
    parser.add_argument("--side",    choices=["short", "long"], default="short",
                        help="'short' = perp short (default); 'long' = spot long")
    parser.add_argument("--dry-run", action="store_true",
                        help="Simulate without sending an order to HL")
    args = parser.parse_args()

    # --- Safety cap ---
    if args.size > MAX_NOTIONAL_USD:
        LOGGER.error(
            "test_hl_trade_rejected size_usd=%.2f max_notional=%.2f reason=size_exceeds_cap",
            args.size, MAX_NOTIONAL_USD,
        )
        return 1

    # --- Load credentials ---
    env = _load_env()
    private_key = env.get("HL_PRIVATE_KEY", "").strip()
    wallet      = env.get("HL_WALLET", "").strip()

    if not private_key:
        LOGGER.error(
            "test_hl_trade_aborted reason=missing_HL_PRIVATE_KEY "
            "hint=set_HL_PRIVATE_KEY_in_/etc/trauto/env"
        )
        return 1
    if not wallet:
        LOGGER.error(
            "test_hl_trade_aborted reason=missing_HL_WALLET "
            "hint=set_HL_WALLET_in_/etc/trauto/env"
        )
        return 1

    # Normalise private key to 0x prefix
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key

    dry_run = args.dry_run
    LOGGER.info(
        "test_hl_trade_starting asset=%s side=%s size_usd=%.2f "
        "wallet=%s dry_run=%s",
        args.asset, args.side, args.size,
        wallet[:10] + "...",
        dry_run,
    )

    # --- Import executor (late import so credential errors show up first) ---
    try:
        from funding_arb.executor import place_perp_short, place_spot_long, get_mark_price
    except ImportError as exc:
        LOGGER.error("test_hl_trade_aborted reason=import_failed error=%s", exc)
        return 1

    # --- Fetch mark price for pre-flight sanity check ---
    try:
        mark_px = get_mark_price(args.asset)
    except Exception as exc:
        LOGGER.error(
            "test_hl_trade_aborted reason=mark_price_fetch_failed asset=%s error=%s",
            args.asset, exc,
        )
        return 1

    if mark_px is None or mark_px <= 0:
        LOGGER.error(
            "test_hl_trade_aborted reason=mark_price_unavailable asset=%s "
            "hint=check_asset_name_is_valid_HL_perp",
            args.asset,
        )
        return 1

    implied_contracts = round(args.size / mark_px, 6)
    LOGGER.info(
        "test_hl_trade_preflight asset=%s mark_px=%.4f size_usd=%.2f "
        "implied_contracts=%.6f",
        args.asset, mark_px, args.size, implied_contracts,
    )

    # --- Place order ---
    if args.side == "short":
        result = place_perp_short(
            private_key=private_key,
            wallet=wallet,
            asset=args.asset,
            size_usd=args.size,
            dry_run=dry_run,
        )
    else:
        result = place_spot_long(
            private_key=private_key,
            wallet=wallet,
            asset=args.asset,
            size_usd=args.size,
            dry_run=dry_run,
        )

    # --- Report result ---
    if result.success:
        LOGGER.info(
            "test_hl_trade_SUCCESS asset=%s side=%s size=%.6f "
            "price=%.4f order_id=%s dry_run=%s",
            result.asset, result.side, result.size,
            result.price, result.order_id, dry_run,
        )
        print(
            f"\n✓ {'DRY RUN — ' if dry_run else ''}Order placed\n"
            f"  asset    : {result.asset}\n"
            f"  side     : {result.side}\n"
            f"  size     : {result.size:.6f} contracts\n"
            f"  price    : ${result.price:,.4f}\n"
            f"  order_id : {result.order_id}\n"
        )
        return 0
    else:
        LOGGER.error(
            "test_hl_trade_FAILED asset=%s side=%s error=%s",
            result.asset, result.side, result.error,
        )
        print(f"\n✗ Order failed: {result.error}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
