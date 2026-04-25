import os, requests, time
from web3 import Web3

# Try multiple RPCs in order until one works
RPCS = [
    "https://polygon.drpc.org",
    "https://rpc.ankr.com/polygon",
    "https://polygon.llamarpc.com",
]

w3 = None
for rpc in RPCS:
    try:
        _w3 = Web3(Web3.HTTPProvider(rpc))
        if _w3.is_connected():
            w3 = _w3
            print(f"Connected via {rpc} | Block: {w3.eth.block_number}")
            break
    except Exception as e:
        print(f"Failed {rpc}: {e}")

if not w3:
    raise Exception("All RPCs failed")

WALLET = Web3.to_checksum_address("0x2415BE0f0107b905051Fe866BA5a995f65f32c9a")
PRIVATE_KEY = os.getenv("POLY_PRIVATE_KEY")

USDC              = Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359")
CTF_EXCHANGE      = Web3.to_checksum_address("0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E")
NEG_RISK_EXCHANGE = Web3.to_checksum_address("0xC5d563A36AE78145C45a50134d48A1215220f80a")
MAX_UINT256       = 2**256 - 1

ERC20_ABI = [
    {"inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],
     "name":"approve","outputs":[{"name":"","type":"bool"}],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"name":"owner","type":"address"},{"name":"spender","type":"address"}],
     "name":"allowance","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"account","type":"address"}],
     "name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
]

usdc = w3.eth.contract(address=USDC, abi=ERC20_ABI)

gas_data = requests.get("https://gasstation.polygon.technology/v2").json()
max_priority = w3.to_wei(float(gas_data["standard"]["maxPriorityFee"]) + 10, "gwei")
max_fee      = w3.to_wei(float(gas_data["standard"]["maxFee"]) + 20, "gwei")
print(f"Gas maxFee: {gas_data['standard']['maxFee']} gwei\n")

usdc_balance = usdc.functions.balanceOf(WALLET).call()
print(f"USDC balance: {usdc_balance / 1e6:.2f} USDC\n")

for name, spender in [("CTF Exchange", CTF_EXCHANGE), ("Neg Risk Exchange", NEG_RISK_EXCHANGE)]:
    allowance = usdc.functions.allowance(WALLET, spender).call()
    print(f"{name} allowance: {allowance / 1e6:.2f} USDC")

    if allowance < 10 * 10**6:
        nonce = w3.eth.get_transaction_count(WALLET, "pending")
        tx = usdc.functions.approve(spender, MAX_UINT256).build_transaction({
            "from": WALLET,
            "nonce": nonce,
            "gas": 100000,
            "maxFeePerGas": max_fee,
            "maxPriorityFeePerGas": max_priority,
            "chainId": 137,
        })
        signed = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        print(f"  Sent: https://polygonscan.com/tx/{tx_hash.hex()}")
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        print(f"  {'Success' if receipt.status == 1 else 'FAILED'}!")
        time.sleep(4)
    else:
        print(f"  Already approved — skipping")

print(f"\nDone. Verify: https://polygonscan.com/address/{WALLET}#tokentxns")
