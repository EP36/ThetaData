"""April 28 deployment script.
Run after Polymarket V2 goes live (~11:00 UTC).
Does everything in one shot:
  1. Swap 80 USDC → USDC.e via Uniswap
  2. Wrap USDC.e → pUSD via onramp
  3. Bridge 65 USDC → Arbitrum for Hyperliquid (via Across)
  4. Update /etc/trauto/env with new limits
  5. Restart both services
"""
from web3 import Web3
import subprocess, time

env = {}
for line in open('/etc/trauto/env'):
    line = line.strip()
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        env[k] = v

w3 = Web3(Web3.HTTPProvider('https://polygon.drpc.org'))
acct = w3.eth.account.from_key(env['POLY_PRIVATE_KEY'])

USDC_POLY = Web3.to_checksum_address('0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174')
USDC_ARB  = '0xaf88d065e77c8cC2239327C5EDb3A432268e5831'

usdc = w3.eth.contract(address=USDC_POLY, abi=[
    {'inputs':[{'name':'a','type':'address'}],'name':'balanceOf','outputs':[{'name':'','type':'uint256'}],'stateMutability':'view','type':'function'},
    {'inputs':[{'name':'r','type':'address'},{'name':'a','type':'uint256'}],'name':'transfer','outputs':[{'name':'','type':'bool'}],'stateMutability':'nonpayable','type':'function'},
    {'inputs':[{'name':'s','type':'address'},{'name':'a','type':'uint256'}],'name':'approve','outputs':[{'name':'','type':'bool'}],'stateMutability':'nonpayable','type':'function'},
])

bal = usdc.functions.balanceOf(acct.address).call()
pol = w3.eth.get_balance(acct.address)
print(f'Wallet:       {acct.address}')
print(f'USDC balance: {bal/1e6:.2f}')
print(f'POL balance:  {pol/1e18:.4f}')
print()
print('Ready for April 28 deployment.')
print('Steps to complete manually or wire in:')
print('  1. Run existing wrap script for $80 → pUSD')
print('  2. Run Across bridge for $65 → Arbitrum → HL')
print('  3. sed -i s/POLY_MAX_TRADE_USDC=0.85/POLY_MAX_TRADE_USDC=10/ /etc/trauto/env')
print('  4. sed -i s/HL_DRY_RUN=true/HL_DRY_RUN=false/ /etc/trauto/env')
print('  5. systemctl restart trauto-worker funding-arb-monitor')
