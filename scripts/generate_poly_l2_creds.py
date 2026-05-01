#!/usr/bin/env python
"""
One-time helper to generate Polymarket CLOB L2 API credentials (key/secret/passphrase)
from an L1 private key using py_clob_client_v2.

Usage (on a trusted machine, NOT the Hetzner VPS):

    export POLY_PK=0xYOUR_PRIVATE_KEY
    # optionally override host/chain:
    # export POLY_CLOB_HOST=https://clob.polymarket.com
    # export POLY_CHAIN_ID=137
    python -m scripts.generate_poly_l2_creds

It prints the L2 API key, secret, and passphrase. Copy those into your
Trauto env on the VPS (e.g. /etc/trauto/env) and stop using POLY_PK there.
"""

import os
import sys

try:
    from py_clob_client_v2.client import ClobClient  # adjust import if your repo uses a different path
except ImportError as e:
    print("Failed to import py_clob_client_v2. Make sure your venv is active and the package is installed.")
    print(f"ImportError: {e}")
    sys.exit(1)


def main() -> None:
    pk = os.getenv("POLY_PK")
    if not pk:
        print("Error: POLY_PK environment variable is not set.")
        print("Set POLY_PK to the private key of the wallet you use on Polymarket, e.g.:")
        print("  export POLY_PK=0xYOUR_PRIVATE_KEY")
        sys.exit(1)

    host = os.getenv("POLY_CLOB_HOST", "https://clob.polymarket.com")
    chain_id_str = os.getenv("POLY_CHAIN_ID", "137")

    try:
        chain_id = int(chain_id_str)
    except ValueError:
        print(f"Error: POLY_CHAIN_ID must be an integer, got {chain_id_str!r}")
        sys.exit(1)

    print(f"Using host={host}, chain_id={chain_id}")

    # Initialize L1 client using private key
    client = ClobClient(
        host=host,
        key=pk,
        chain_id=chain_id,
    )

    # Create or derive L2 API credentials (key/secret/passphrase)
    creds = client.create_or_derive_api_creds()

    print("\n=== Polymarket L2 API Credentials ===")
    print("API Key      :", creds.api_key)
    print("API Secret   :", creds.api_secret)
    print("API Passphrase:", creds.api_passphrase)
    print("=====================================")
    print("\nNext steps:")
    print("1) On your Hetzner VPS, add these to /etc/trauto/env (or equivalent):")
    print("   POLY_L2_API_KEY=<API Key>")
    print("   POLY_L2_API_SECRET=<API Secret>")
    print("   POLY_L2_API_PASSPHRASE=<API Passphrase>")
    print("2) Make sure POLY_WALLET matches the wallet address linked to this private key.")
    print("3) Restart trauto-worker.")
    print("4) Remove POLY_PK from all envs on the VPS; you only need it here for this script.")


if __name__ == "__main__":
    main()