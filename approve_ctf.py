import os, requests, time
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

w3 = Web3(Web3.HTTPProvider('https://polygon.drpc.org'))
w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)  # fix POA extraData error

WALLET      = Web3.to_checksum_address('0x2415BE0f0107b905051Fe866BA5a995f65f32c9a')
PRIVATE_KEY = os.getenv('POLY_PRIVATE_KEY')
MAX_UINT256 = 2**256 - 1

CTF_TOKEN    = Web3.to_checksum_address('0x4D97DCd97eC945f40cF65F87097ACe5EA0476045')
CTF_EXCHANGE = Web3.to_checksum_address('0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E')
NEG_RISK_ADP = Web3.to_checksum_address('0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296')

ERC1155_ABI = [
    {'inputs':[{'name':'operator','type':'address'},{'name':'approved','type':'bool'}],
     'name':'setApprovalForAll','outputs':[],'stateMutability':'nonpayable','type':'function'},
    {'inputs':[{'name':'account','type':'address'},{'name':'operator','type':'address'}],
     'name':'isApprovedForAll','outputs':[{'name':'','type':'bool'}],'stateMutability':'view','type':'function'},
]

ctf = w3.eth.contract(address=CTF_TOKEN, abi=ERC1155_ABI)

gas_data     = requests.get('https://gasstation.polygon.technology/v2').json()
max_priority = w3.to_wei(float(gas_data['standard']['maxPriorityFee']) + 10, 'gwei')
max_fee      = w3.to_wei(float(gas_data['standard']['maxFee']) + 20, 'gwei')

for name, operator in [('CTF Exchange', CTF_EXCHANGE), ('Neg Risk Adapter', NEG_RISK_ADP)]:
    approved = ctf.functions.isApprovedForAll(WALLET, operator).call()
    print(f'CTF Token → {name}: {approved}')
    if not approved:
        nonce = w3.eth.get_transaction_count(WALLET, 'pending')
        tx = ctf.functions.setApprovalForAll(operator, True).build_transaction({
            'from': WALLET, 'nonce': nonce, 'gas': 100000,
            'maxFeePerGas': max_fee, 'maxPriorityFeePerGas': max_priority, 'chainId': 137,
        })
        signed = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
        h = w3.eth.send_raw_transaction(signed.raw_transaction)
        r = w3.eth.wait_for_transaction_receipt(h, timeout=120)
        print(f"  {'OK' if r.status==1 else 'FAILED'}: https://polygonscan.com/tx/{h.hex()}")
        time.sleep(4)
    else:
        print('  Already approved')

print('\nAll done!')
