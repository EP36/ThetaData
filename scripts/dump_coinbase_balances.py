#!/usr/bin/env python
import json
import logging

from theta.fundingarb import coinbase as cb_mod  # same module used by test_coinbase_trade

log = logging.getLogger("theta.scripts.dump_coinbase_balances")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    client = cb_mod.get_client()  # or whatever factory test_coinbase_trade uses

    # Adjust this call to however your client exposes balances.
    # Common Advanced Trade pattern is something like client.get_accounts() or list_accounts().
    accounts = client.list_accounts()  # replace with the real method name

    # Print a compact view for debugging
    rows = []
    for acct in accounts:
        # adapt keys based on your client’s response shape
        currency = acct.get("currency") or acct.get("asset") or acct.get("balance", {}).get("currency")
        available = (
            acct.get("available_balance", {}).get("value")
            or acct.get("available")
            or acct.get("balance", {}).get("available")
            or "0"
        )
        rows.append({"currency": currency, "available": available, "raw": acct})

    log.info("coinbase_balances summary=%s", json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()