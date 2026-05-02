#!/usr/bin/env python3
"""One-shot Coinbase spot test trade using the theta execution stack.

This script is the integration point between the new theta/ modules and
the server's /etc/trauto/env config.  It handles env loading, arg parsing,
safety checks, and final output — all business logic lives in theta/.

Usage:
    source .venv/bin/activate

    # Dry run (fetches price + evaluates edge, no order):
    python -m scripts.test_coinbase_trade --dry-run

    # Live buy ETH-USD, $2, with an explicit edge signal of 200 bps:
    python -m scripts.test_coinbase_trade --asset ETH --size 2 --edge-bps 200

    # Skip the edge check entirely (for connectivity testing only):
    python -m scripts.test_coinbase_trade --asset ETH --size 2 --force

    # Different quote currency (ETH-USDC):
    python -m scripts.test_coinbase_trade --asset ETH --quote USDC --size 2 --force

Required env vars (in /etc/trauto/env or shell env):
    COINBASE_API_KEY    — organizations/xxx/apiKeys/xxx
    COINBASE_API_SECRET — EC private key PEM string

Optional env vars (all have safe defaults):
    CB_TAKER_FEE_BPS, CB_SLIPPAGE_BUFFER_BPS, MIN_EDGE_BPS
    MIN_NOTIONAL_USD, MAX_NOTIONAL_USD, MAX_DAILY_NOTIONAL_USD
    DEFAULT_QUOTE, TRADE_LOG_DIR

Safety: notional size is hard-capped at $25 in this script.
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
LOGGER = logging.getLogger("theta.scripts.test_coinbase_trade")

_SCRIPT_MAX_NOTIONAL_USD = 25.0


def _load_env_file() -> None:
    """Inject /etc/trauto/env into os.environ (shell env takes precedence).

    Skips lines that don't look like ENV_VAR=value assignments so that
    multi-line PEM values (e.g. COINBASE_API_SECRET) don't corrupt the parse.
    """
    import re
    _env_key = re.compile(r'^[A-Z_][A-Z0-9_]*$')
    try:
        with open("/etc/trauto/env") as fh:
            for line in fh:
                line = line.strip()
                if "=" not in line or line.startswith("#"):
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                if not _env_key.match(k):
                    continue
                v = v.strip()
                if k not in os.environ:
                    os.environ[k] = v
    except FileNotFoundError:
        LOGGER.debug("no /etc/trauto/env found; using shell environment only")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="One-shot Coinbase spot test trade",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--asset", default="ETH",
        help="Base currency to trade (default: ETH). Product will be ASSET-QUOTE.",
    )
    parser.add_argument(
        "--quote", default=None,
        help="Quote currency (default: USD from config, NOT USDC). "
             "ETH-USD is the primary liquidity venue.",
    )
    parser.add_argument(
        "--size", type=float, default=2.0,
        help=f"Notional USD size (default: 2.0, script cap: {_SCRIPT_MAX_NOTIONAL_USD})",
    )
    parser.add_argument(
        "--edge-bps", type=float, default=0.0,
        dest="edge_bps",
        help="Expected alpha in basis points (default: 0). "
             "The hurdle is ~130–150 bps with default fee params. "
             "Pass a value above the hurdle to allow a live order.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Bypass the edge check (for connectivity testing only). "
             "Uses min_edge_bps=0 so the hurdle equals round-trip cost only.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        dest="dry_run",
        help="Fetch price, evaluate edge, log details, but do NOT place an order.",
    )
    args = parser.parse_args()

    # Load /etc/trauto/env before anything reads os.environ
    _load_env_file()

    # Script-level hard cap (independent of config)
    if args.size > _SCRIPT_MAX_NOTIONAL_USD:
        LOGGER.error(
            "script_cap_exceeded size=%.2f cap=%.2f "
            "reason=modify_SCRIPT_MAX_NOTIONAL_USD_if_intentional",
            args.size, _SCRIPT_MAX_NOTIONAL_USD,
        )
        return 1

    # Credential check before importing anything that might fail noisily
    if not os.environ.get("COINBASE_API_KEY", "").strip():
        LOGGER.error(
            "aborted reason=missing_COINBASE_API_KEY "
            "hint=add_to_/etc/trauto/env"
        )
        return 1
    if not os.environ.get("COINBASE_API_SECRET", "").strip():
        LOGGER.error(
            "aborted reason=missing_COINBASE_API_SECRET "
            "hint=add_to_/etc/trauto/env"
        )
        return 1

    # Late imports — env is populated by now
    try:
        from theta.config.basis import BasisConfig
        from theta.marketdata.coinbase import get_spot_mid_price, get_quote_balance, MarketDataError
        from theta.execution.coinbase import should_trade_spot, place_market_order, ExecutionError
    except ImportError as exc:
        LOGGER.error("import_failed error=%s", exc)
        return 1

    # Build config — reads CB_TAKER_FEE_BPS, MIN_EDGE_BPS, etc. from env
    cfg = BasisConfig.from_env()
    if args.force:
        cfg = BasisConfig(
            cb_taker_fee_bps=cfg.cb_taker_fee_bps,
            slippage_buffer_bps=cfg.slippage_buffer_bps,
            min_edge_bps=0.0,         # zero margin so round-trip cost is the only hurdle
            min_notional_usd=cfg.min_notional_usd,
            max_notional_usd=_SCRIPT_MAX_NOTIONAL_USD,
            default_quote=cfg.default_quote,
            log_dir=cfg.log_dir,
        )

    quote = args.quote or cfg.default_quote
    product_id = f"{args.asset}-{quote}"

    LOGGER.info(
        "test_coinbase_trade_starting asset=%s quote=%s "
        "product=%s size=%.2f edge_bps=%.1f "
        "dry_run=%s force=%s "
        "hurdle=%.1fbps [fees=%.1fbps×2 slip=%.1fbps×2 margin=%.1fbps]",
        args.asset, quote, product_id, args.size, args.edge_bps,
        args.dry_run, args.force,
        cfg.hurdle_bps, cfg.cb_taker_fee_bps,
        cfg.slippage_buffer_bps, cfg.min_edge_bps,
    )

    # --- Edge / risk gate ---
    trade_ok, reason = should_trade_spot(
        asset=args.asset,
        notional_usd=args.size,
        expected_edge_bps=args.edge_bps,
        config=cfg,
    )
    LOGGER.info(
        "edge_check result=%s reason=%s",
        "PASS" if trade_ok else "FAIL", reason,
    )
    if not trade_ok and not args.dry_run:
        LOGGER.warning(
            "trade_blocked reason=%s "
            "hint=pass_--edge-bps_above_%.0f_or_use_--force_for_testing",
            reason, cfg.hurdle_bps,
        )
        print(
            f"\n✗ Trade blocked: {reason}\n"
            f"  Hurdle is {cfg.hurdle_bps:.0f} bps. "
            f"Pass --edge-bps {cfg.hurdle_bps:.0f} or higher to trade, "
            f"or --force to bypass the margin check.\n"
        )
        return 1

    # --- Market data preflight ---
    try:
        mid_price = get_spot_mid_price(args.asset, quote)
    except MarketDataError as exc:
        LOGGER.error("mid_price_failed product=%s error=%s", product_id, exc)
        print(f"\n✗ Market data error: {exc}\n")
        return 1

    balance = get_quote_balance(quote)
    implied_qty = args.size / mid_price if mid_price > 0 else 0.0
    exp_fee = args.size * cfg.cb_taker_fee_bps / 10_000.0
    exp_slip = args.size * cfg.slippage_buffer_bps / 10_000.0

    LOGGER.info(
        "preflight_ok product=%s mid=%.6f balance_%s=%.2f "
        "size=%.2f implied_qty=%.6f "
        "exp_fee=%.4f exp_slippage=%.4f",
        product_id, mid_price, quote, balance,
        args.size, implied_qty, exp_fee, exp_slip,
    )

    if balance < args.size and not args.dry_run:
        LOGGER.error(
            "aborted reason=insufficient_%s_balance "
            "available=%.2f required=%.2f",
            quote, balance, args.size,
        )
        print(
            f"\n✗ Insufficient {quote} balance: "
            f"${balance:.2f} available, ${args.size:.2f} required\n"
        )
        return 1

    # --- Dry run summary ---
    if args.dry_run:
        print(
            f"\nDRY RUN — no order sent\n"
            f"  product        : {product_id}\n"
            f"  mid price      : ${mid_price:,.6f}\n"
            f"  size ({quote})       : ${args.size:.2f}\n"
            f"  implied qty    : {implied_qty:.6f} {args.asset}\n"
            f"  {quote} balance    : ${balance:.2f}\n"
            f"  expected fee   : ${exp_fee:.4f}  ({cfg.cb_taker_fee_bps:.0f} bps)\n"
            f"  expected slip  : ${exp_slip:.4f}  ({cfg.slippage_buffer_bps:.0f} bps)\n"
            f"  edge provided  : {args.edge_bps:.1f} bps\n"
            f"  hurdle         : {cfg.hurdle_bps:.1f} bps\n"
            f"  edge_check     : {'PASS' if trade_ok else 'FAIL — but dry_run requested'}\n"
        )
        # Still produce a telemetry record so dry runs are visible in trades.jsonl
        from theta.execution.coinbase import place_market_order
        place_market_order(
            asset=args.asset,
            side="buy",
            notional_usd=args.size,
            quote=quote,
            expected_edge_bps=args.edge_bps,
            config=cfg,
            dry_run=True,
        )
        return 0

    # --- Live order ---
    try:
        record = place_market_order(
            asset=args.asset,
            side="buy",
            notional_usd=args.size,
            quote=quote,
            expected_edge_bps=args.edge_bps,
            config=cfg,
            dry_run=False,
        )
    except ExecutionError as exc:
        LOGGER.error("order_failed error=%s", exc)
        print(f"\n✗ Order failed: {exc}\n")
        return 1

    print(
        f"\n✓ Order submitted\n"
        f"  product         : {product_id}\n"
        f"  side            : {record.side}\n"
        f"  notional        : ${record.notional_usd:.2f}\n"
        f"  mid at order    : ${record.mid_price_at_order:,.6f}\n"
        f"  expected fee    : ${record.expected_fee_usd:.4f}\n"
        f"  order_id        : {record.order_id}\n"
        f"  client_order_id : {record.client_order_id}\n"
        f"  telemetry       : logs/trades.jsonl\n"
        f"\nNote: Coinbase IOC fills are not returned synchronously.\n"
        f"Use the order_id to poll /api/v3/brokerage/orders/historical/{{order_id}}\n"
        f"or check your Coinbase account for actual fill details.\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
