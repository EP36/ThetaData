#!/usr/bin/env python3
import argparse
import json
import os
import sys
from decimal import Decimal

from web3 import Web3
from eth_account import Account

USDC_E = Web3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")
ONRAMP = Web3.to_checksum_address("0x93070a847efEf7F70739046A929D47a521F5B8ee")
PUSD = Web3.to_checksum_address("0xD652c5425aea2Afd5fb142e120FeCf79e18fafc3")
POLYGON_RPC_DEFAULT = "https://polygon-rpc.com"
CHAIN_ID = 137
DECIMALS = 6

ERC20_ABI = json.loads('[{"constant":true,"inputs":[{"name":"account","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":true,"inputs":[{"name":"owner","type":"address"},{"name":"spender","type":"address"}],"name":"allowance","outputs":[{"name":"","type":"uint256"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":false,"inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"payable":false,"stateMutability":"nonpayable","type":"function"}]')
ONRAMP_ABI = json.loads('[{"inputs":[{"internalType":"address","name":"_asset","type":"address"},{"internalType":"address","name":"_to","type":"address"},{"internalType":"uint256","name":"_amount","type":"uint256"}],"name":"wrap","outputs":[],"stateMutability":"nonpayable","type":"function"}]')


def parse_args():
    p = argparse.ArgumentParser(description="Approve Polygon USDC.e and wrap it into pUSD for Polymarket")
    p.add_argument("amount", type=Decimal, help="Amount of USDC.e to wrap into pUSD")
    p.add_argument("--rpc", default=os.getenv("POLYGON_RPC_URL", POLYGON_RPC_DEFAULT))
    p.add_argument("--private-key", default=os.getenv("POLY_PRIVATE_KEY") or os.getenv("POLYGON_PRIVATE_KEY"))
    p.add_argument("--to", default=os.getenv("POLY_WALLET_ADDRESS"), help="Destination wallet for pUSD; defaults to POLY_WALLET_ADDRESS or sender")
    p.add_argument("--approve-max", action="store_true", help="Approve max uint256 instead of exact amount")
    p.add_argument("--dry-run", action="store_true", help="Only print balances/allowances and planned actions")
    return p.parse_args()


def to_base_units(amount: Decimal) -> int:
    q = Decimal(10) ** DECIMALS
    return int((amount * q).quantize(Decimal('1')))


def fmt_units(value: int) -> str:
    return f"{Decimal(value) / (Decimal(10) ** DECIMALS):,.6f}"


def build_and_send(w3, account, tx):
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    return tx_hash.hex(), receipt


def main():
    args = parse_args()
    if not args.private_key:
        raise SystemExit("Missing private key. Set POLY_PRIVATE_KEY or POLYGON_PRIVATE_KEY.")

    private_key = args.private_key
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key

    w3 = Web3(Web3.HTTPProvider(args.rpc, request_kwargs={"timeout": 30}))
    if not w3.is_connected():
        raise SystemExit(f"Failed to connect to Polygon RPC: {args.rpc}")

    account = Account.from_key(private_key)
    sender = Web3.to_checksum_address(account.address)
    dest = Web3.to_checksum_address(args.to) if args.to else sender

    usdc = w3.eth.contract(address=USDC_E, abi=ERC20_ABI)
    onramp = w3.eth.contract(address=ONRAMP, abi=ONRAMP_ABI)
    pusd = w3.eth.contract(address=PUSD, abi=ERC20_ABI)

    amount_units = to_base_units(args.amount)
    max_uint = 2**256 - 1

    usdc_balance = usdc.functions.balanceOf(sender).call()
    pusd_balance_before = pusd.functions.balanceOf(dest).call()
    allowance = usdc.functions.allowance(sender, ONRAMP).call()
    nonce = w3.eth.get_transaction_count(sender)

    print(f"RPC:                  {args.rpc}")
    print(f"Sender:               {sender}")
    print(f"Destination:          {dest}")
    print(f"USDC.e balance:       {fmt_units(usdc_balance)}")
    print(f"Current allowance:    {fmt_units(allowance)}")
    print(f"pUSD balance before:  {fmt_units(pusd_balance_before)}")
    print(f"Requested wrap:       {fmt_units(amount_units)}")
    print(f"Onramp contract:      {ONRAMP}")
    print()

    if usdc_balance < amount_units:
        raise SystemExit("Not enough USDC.e balance for requested wrap amount.")

    need_approval = allowance < amount_units
    if args.dry_run:
        print("Dry run only.")
        print(f"Needs approval:       {need_approval}")
        print("Next step: approve then wrap USDC.e -> pUSD via Polymarket onramp.")
        return

    max_fee = w3.eth.max_priority_fee if hasattr(w3.eth, 'max_priority_fee') else w3.to_wei(30, 'gwei')
    base_fee = w3.eth.gas_price

    if need_approval:
        approve_amount = max_uint if args.approve_max else amount_units
        approve_tx = usdc.functions.approve(ONRAMP, approve_amount).build_transaction({
            "from": sender,
            "chainId": CHAIN_ID,
            "nonce": nonce,
            "gas": 120000,
            "maxFeePerGas": base_fee * 2,
            "maxPriorityFeePerGas": max_fee,
        })
        tx_hash, receipt = build_and_send(w3, account, approve_tx)
        print(f"Approve tx:           {tx_hash}")
        print(f"Approve status:       {receipt.status}")
        if receipt.status != 1:
            raise SystemExit("Approval transaction failed.")
        nonce += 1
    else:
        print("Approval skipped:     existing allowance is sufficient")

    wrap_tx = onramp.functions.wrap(USDC_E, dest, amount_units).build_transaction({
        "from": sender,
        "chainId": CHAIN_ID,
        "nonce": nonce,
        "gas": 220000,
        "maxFeePerGas": base_fee * 2,
        "maxPriorityFeePerGas": max_fee,
    })
    tx_hash, receipt = build_and_send(w3, account, wrap_tx)
    print(f"Wrap tx:              {tx_hash}")
    print(f"Wrap status:          {receipt.status}")
    if receipt.status != 1:
        raise SystemExit("Wrap transaction failed.")

    pusd_balance_after = pusd.functions.balanceOf(dest).call()
    print(f"pUSD balance after:   {fmt_units(pusd_balance_after)}")
    print(f"Added pUSD:           {fmt_units(max(0, pusd_balance_after - pusd_balance_before))}")
    print(f"PolygonScan:          https://polygonscan.com/tx/{tx_hash}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
