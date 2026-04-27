#!/usr/bin/env python3
import os
import sys
from decimal import Decimal

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import GetAccountInfoParams

HOST = os.getenv("POLY_CLOB_HOST", "https://clob.polymarket.com")
CHAIN_ID = int(os.getenv("POLY_CHAIN_ID", "137"))

# These should match what Trauto uses for Polymarket
PRIVATE_KEY = os.getenv("POLY_PRIVATE_KEY") or os.getenv("POLYGON_PRIVATE_KEY")
FUNDER = os.getenv("POLY_WALLET_ADDRESS")  # address that actually holds pUSD


DECIMALS = 6


def fmt_units(v: int) -> str:
    return f"{Decimal(v) / (Decimal(10) ** DECIMALS):,.6f}"


def main():
    if not PRIVATE_KEY:
        raise SystemExit("Set POLY_PRIVATE_KEY (or POLYGON_PRIVATE_KEY) in env.")

    if not FUNDER:
        raise SystemExit("Set POLY_WALLET_ADDRESS to your Polymarket wallet address.")

    # Normalize 0x prefix
    pk = PRIVATE_KEY if PRIVATE_KEY.startswith("0x") else "0x" + PRIVATE_KEY

    client = ClobClient(
        HOST,
        key=pk,
        chain_id=CHAIN_ID,
        signature_type=1,  # magic/email-style signatures
        funder=FUNDER,
    )
    client.set_api_creds(client.create_or_derive_api_creds())

    info = client.get_account_info(GetAccountInfoParams())
    # Shape is defined in py_clob_client docs; typically includes freeCollateral, allowance, balances, etc.
    print("Raw account info:")
    print(info)

    free_collateral = info.get("freeCollateral", 0)
    used_collateral = info.get("usedCollateral", 0)
    total_collateral = free_collateral + used_collateral

    allowance = info.get("allowance", 0)

    print("\nCLOB collateral state (pUSD units):")
    print(f"  Free collateral : {fmt_units(free_collateral)}")
    print(f"  Used collateral : {fmt_units(used_collateral)}")
    print(f"  Total collateral: {fmt_units(total_collateral)}")
    print(f"  Allowance       : {fmt_units(allowance)}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)