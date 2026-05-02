#!/usr/bin/env python3
"""Fetch or poll a Coinbase Advanced Trade order by order_id or client_order_id.

Usage:
    # By server-assigned order_id:
    python -m scripts.poll_coinbase_order --order-id <uuid>

    # By client_order_id (as logged by test_coinbase_trade):
    python -m scripts.poll_coinbase_order --client-order-id trauto-spot-1777697807727

    # With product hint (speeds up client_order_id search):
    python -m scripts.poll_coinbase_order --client-order-id trauto-spot-xxx --product ETH-USD

    # Keep polling until filled or 30s timeout:
    python -m scripts.poll_coinbase_order --client-order-id trauto-spot-xxx --poll

    # Custom poll interval/timeout:
    python -m scripts.poll_coinbase_order --order-id <uuid> --poll --interval 5 --timeout 60
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
LOGGER = logging.getLogger("theta.scripts.poll_coinbase_order")

_TERMINAL_STATUSES = frozenset({
    "FILLED", "CANCELLED", "CANCELED", "EXPIRED", "FAILED",
    "UNKNOWN_ORDER_STATUS",
})


# ---------------------------------------------------------------------------
# Env loading (same hardened PEM-safe implementation as test_coinbase_trade)
# ---------------------------------------------------------------------------

def _load_env_file() -> None:
    """Inject /etc/trauto/env into os.environ (shell env takes precedence).

    Skips lines that don't look like ENV_VAR=value assignments so that
    multi-line PEM values (e.g. COINBASE_API_SECRET) don't corrupt the parse.
    """
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


# ---------------------------------------------------------------------------
# Order fetching
# ---------------------------------------------------------------------------

def _fetch_by_order_id(cb, order_id: str):
    """Return the Order object from get_order(order_id), or None if not found."""
    try:
        resp = cb.get_order(order_id=order_id)
    except Exception as exc:
        LOGGER.error(
            "get_order_failed order_id=%s error_type=%s error=%s",
            order_id, type(exc).__name__, exc,
        )
        return None

    order = getattr(resp, "order", None)
    if order is None:
        # resp may be a plain dict
        if isinstance(resp, dict):
            raw = resp.get("order")
            if isinstance(raw, dict):
                from coinbase.rest.types.orders_types import Order
                order = Order(**raw)
    return order


def _fetch_by_client_order_id(cb, client_order_id: str, product_id: str | None):
    """Search list_orders for a matching client_order_id.

    Searches the given product first (fast), then all recent orders if needed.
    """
    def _scan(orders) -> object | None:
        for o in orders or []:
            coid = getattr(o, "client_order_id", None)
            if isinstance(o, dict):
                coid = o.get("client_order_id")
            if coid == client_order_id:
                return o
        return None

    # --- Pass 1: filter by product_id if provided ---
    if product_id:
        try:
            resp = cb.list_orders(product_ids=[product_id], limit=250)
        except Exception as exc:
            LOGGER.warning(
                "list_orders_failed product=%s error=%s", product_id, exc,
            )
            resp = None

        if resp is not None:
            orders = getattr(resp, "orders", None)
            if isinstance(resp, dict):
                orders = resp.get("orders", [])
            match = _scan(orders)
            if match:
                return match

    # --- Pass 2: recent orders across all products ---
    try:
        resp = cb.list_orders(limit=250)
    except Exception as exc:
        LOGGER.error(
            "list_orders_all_failed error_type=%s error=%s",
            type(exc).__name__, exc,
        )
        return None

    orders = getattr(resp, "orders", None)
    if isinstance(resp, dict):
        orders = resp.get("orders", [])
    return _scan(orders)


def _order_to_dict(order) -> dict:
    """Extract key fields from an Order object or plain dict."""
    if isinstance(order, dict):
        return order
    if hasattr(order, "to_dict"):
        return order.to_dict()
    return {
        "order_id":             getattr(order, "order_id", ""),
        "client_order_id":      getattr(order, "client_order_id", ""),
        "product_id":           getattr(order, "product_id", ""),
        "side":                 getattr(order, "side", ""),
        "status":               getattr(order, "status", ""),
        "filled_size":          getattr(order, "filled_size", ""),
        "average_filled_price": getattr(order, "average_filled_price", ""),
        "fee":                  getattr(order, "fee", ""),
        "created_time":         getattr(order, "created_time", ""),
    }


def _print_order(d: dict) -> None:
    status = d.get("status", "")
    print(
        f"\nOrder status:\n"
        f"  product         : {d.get('product_id', '')}\n"
        f"  order_id        : {d.get('order_id', '')}\n"
        f"  client_order_id : {d.get('client_order_id', '')}\n"
        f"  side            : {d.get('side', '')}\n"
        f"  status          : {status}\n"
        f"  filled_size     : {d.get('filled_size', '')} {d.get('product_id', '').split('-')[0]}\n"
        f"  avg_fill_price  : {d.get('average_filled_price', '')}\n"
        f"  fee             : {d.get('fee', '')}\n"
        f"  created_time    : {d.get('created_time', '')}\n"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch or poll a Coinbase Advanced Trade order status",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    id_group = parser.add_mutually_exclusive_group(required=True)
    id_group.add_argument(
        "--order-id",
        dest="order_id",
        help="Server-assigned order UUID (from order_id in trades.jsonl).",
    )
    id_group.add_argument(
        "--client-order-id",
        dest="client_order_id",
        help="Client order ID (e.g. trauto-spot-1777697807727).",
    )
    parser.add_argument(
        "--product", default="ETH-USD",
        help="Product ID hint for client_order_id search (default: ETH-USD).",
    )
    parser.add_argument(
        "--poll", action="store_true",
        help="Keep polling until a terminal state or timeout.",
    )
    parser.add_argument(
        "--interval", type=float, default=2.0,
        help="Poll interval in seconds (default: 2).",
    )
    parser.add_argument(
        "--timeout", type=float, default=30.0,
        help="Max polling time in seconds before giving up (default: 30).",
    )
    args = parser.parse_args()

    _load_env_file()

    if not os.environ.get("COINBASE_API_KEY", "").strip():
        LOGGER.error("aborted reason=missing_COINBASE_API_KEY")
        return 1
    if not os.environ.get("COINBASE_API_SECRET", "").strip():
        LOGGER.error("aborted reason=missing_COINBASE_API_SECRET")
        return 1

    try:
        from funding_arb.coinbase_client import get_coinbase_client
    except ImportError as exc:
        LOGGER.error("import_failed error=%s", exc)
        return 1

    cb = get_coinbase_client()
    if cb is None:
        LOGGER.error("aborted reason=coinbase_client_unavailable")
        return 1

    LOGGER.info(
        "poll_coinbase_order order_id=%s client_order_id=%s product=%s poll=%s",
        args.order_id or "", args.client_order_id or "", args.product, args.poll,
    )

    def _fetch():
        if args.order_id:
            return _fetch_by_order_id(cb, args.order_id)
        return _fetch_by_client_order_id(cb, args.client_order_id, args.product)

    deadline = time.monotonic() + args.timeout

    while True:
        order = _fetch()

        if order is None:
            print("\n✗ Order not found.\n")
            return 1

        d = _order_to_dict(order)
        status = str(d.get("status", "")).upper()

        LOGGER.info(
            "order_status order_id=%s client_order_id=%s status=%s "
            "filled_size=%s avg_price=%s",
            d.get("order_id", ""), d.get("client_order_id", ""),
            status, d.get("filled_size", ""), d.get("average_filled_price", ""),
        )

        if not args.poll or status in _TERMINAL_STATUSES:
            _print_order(d)
            return 0

        if time.monotonic() >= deadline:
            _print_order(d)
            print(
                f"⚠ Timed out after {args.timeout:.0f}s waiting for terminal state. "
                f"Last status: {status}\n"
            )
            return 1

        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
