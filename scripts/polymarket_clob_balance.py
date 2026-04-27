#!/usr/bin/env python3
import os
import sys
from decimal import Decimal

from py_clob_client_v2 import ClobClient
from py_clob_client_v2.clob_types import BalanceAllowanceParams, AssetType

HOST = os.getenv("POLY_CLOB_HOST", "https://clob.polymarket.com")
CHAIN = int(os.getenv("POLY_CHAIN", "137"))
PRIVATE_KEY = os.getenv("POLY_PRIVATE_KEY") or os.getenv("POLYGON_PRIVATE_KEY")
FUNDER = os.getenv("POLY_WALLET_ADDRESS")
SIGNATURE_TYPE = int(os.getenv("POLY_SIGNATURE_TYPE", "1"))
DECIMALS = 6


def fmt_units(v: int | str) -> str:
    value = int(v)
    return f"{Decimal(value) / (Decimal(10) ** DECIMALS):,.6f}"


def main():
    if not PRIVATE_KEY:
        raise SystemExit("Missing POLY_PRIVATE_KEY / POLYGON_PRIVATE_KEY")
    if not FUNDER:
        raise SystemExit("Missing POLY_WALLET_ADDRESS")

    pk = PRIVATE_KEY if PRIVATE_KEY.startswith("0x") else "0x" + PRIVATE_KEY

    client = ClobClient(
        host=HOST,
        key=pk,
        chain_id=CHAIN,
        signature_type=SIGNATURE_TYPE,
        funder=FUNDER,
    )

    # Prefer derive of existing creds; only create if derive isn't available in your installed version
    if hasattr(client, "derive_api_key"):
        creds = client.derive_api_key()
    elif hasattr(client, "create_or_derive_api_key"):
        creds = client.create_or_derive_api_key()
    else:
        raise SystemExit("No supported API-key derivation method found on installed py_clob_client_v2")

    client.set_api_creds(creds)

    bal = client.get_balance()
    ba = client.get_balance_allowance(
        BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
    )

    print("Raw get_balance():")
    print(bal)
    print("\nRaw get_balance_allowance():")
    print(ba)

    balance = int(ba.get("balance", 0))
    allowance = int(ba.get("allowance", 0))

    print("\nCLOB collateral state:")
    print(f"  Balance   : {fmt_units(balance)} pUSD")
    print(f"  Allowance : {fmt_units(allowance)} pUSD")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)