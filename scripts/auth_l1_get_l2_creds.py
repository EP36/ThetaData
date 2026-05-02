import os
from py_clob_client.client import ClobClient

HOST = "https://clob.polymarket.com"
CHAIN_ID = 137  # Polygon mainnet

def main():
    pk = os.getenv("POLY_PRIVATE_KEY")
    if not pk:
        raise RuntimeError("POLY_PRIVATE_KEY env var not set (0x-prefixed private key)")

    print(f"Using private key starting with: {pk[:10]}...")

    # L1 client using EOA private key, as in Polymarket auth docs[web:14][web:52]
    client = ClobClient(
        HOST,
        key=pk,
        chain_id=CHAIN_ID,
    )

    print("Calling create_or_derive_api_creds() via py_clob_client...")
    try:
        creds = client.create_or_derive_api_creds()
        api_key = getattr(creds, "api_key", None) or getattr(creds, "key", None)
        print("API Key     :", api_key)
        print("Secret      :", creds.secret)
        print("Passphrase  :", creds.passphrase)
    except Exception as e:
        print("Error from create_or_derive_api_creds():", repr(e))

if __name__ == "__main__":
    main()
