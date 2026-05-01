#!/usr/bin/env python3
"""Dump Coinbase quote balances as seen by the theta.marketdata layer."""

from __future__ import annotations

import logging
import os


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
LOGGER = logging.getLogger("theta.scripts.dump_coinbase_balances")


def _load_env_file() -> None:
    """Inject /etc/trauto/env into os.environ (shell env takes precedence)."""
    try:
        with open("/etc/trauto/env") as fh:
            for line in fh:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip()
                    if k not in os.environ:
                        os.environ[k] = v
    except FileNotFoundError:
        LOGGER.debug("no /etc/trauto/env found; using shell environment only")


def main() -> int:
    _load_env_file()

    if not os.environ.get("COINBASE_API_KEY", "").strip():
        LOGGER.error("missing COINBASE_API_KEY")
        return 1
    if not os.environ.get("COINBASE_API_SECRET", "").strip():
        LOGGER.error("missing COINBASE_API_SECRET")
        return 1

    try:
        from theta.marketdata.coinbase import get_quote_balance
    except ImportError as exc:
        LOGGER.error("import_failed error=%s", exc)
        return 1

    for quote in ("USD", "USDC", "CASH", "EUR"):
        try:
            bal = get_quote_balance(quote)
        except Exception as exc:  # type: ignore[catching-general-exception]
            LOGGER.warning("balance_fetch_failed quote=%s error=%s", quote, exc)
            continue
        LOGGER.info("quote_balance quote=%s balance=%.8f", quote, bal)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())