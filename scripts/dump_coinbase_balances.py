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

    # First dump the raw account list so we can see what currencies exist.
    try:
        from funding_arb.coinbase_client import get_coinbase_client
        cb = get_coinbase_client()
        if cb is not None:
            resp = cb.get_accounts(limit=250)
            accounts = getattr(resp, "accounts", None) or []
            LOGGER.info(
                "raw_accounts count=%d has_next=%s",
                len(accounts), getattr(resp, "has_next", "?"),
            )
            for acct in accounts:
                cur = getattr(acct, "currency", "?")
                avail = getattr(acct, "available_balance", None)
                val = getattr(avail, "value", "?") if avail else "?"
                name = getattr(acct, "name", "?")
                LOGGER.info("  account name=%r currency=%s available=%s", name, cur, val)
    except Exception as exc:
        LOGGER.warning("raw_accounts_dump_failed error=%s", exc)

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