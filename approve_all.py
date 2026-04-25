import os, requests, time
from web3 import Web3

w3 = Web3(Web3.HTTPProvider('https://polygon.drpc.org'))
WALLET       = Web3.to_checksum_address('0x2415BE0f0107b905051Fe866BA5a995f65f32c9a')
PRIVATE_KEY  = os.getenv('POLY_PRIVATE_KEY')
MAX_UINT256  = 2**256 - 1

# Contracts
USDC         = Web3.to_checksum_address('0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359')
CTF_TOKEN    = Web3.to_checksum_address('0x4D97DCd97eC945f40cF65F87097ACe5EA0476045')  # conditional token (ERC1155)
CTF_EXCHANGE = Web3.to_checksum_address('0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E')
NEG_RISK_EX  = Web3.to_checksum_address('0xC5d563A36AE78145C45a50134d48A1215220f80a')
NEG_RISK_ADP = Web3.to_checksum_address('0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296')

ERC20_ABI = [
    {'inputs':[{'name':'spender','type':'address'},{'name':'amount','type':'uint256'}],
     'name':'approve','outputs':[{'name':'','type':'bool'}],'stateMutability':'nonpayable','type':'function'},
    {'inputs':[{'name':'owner','type':'address'},{'name':'spender','type':'address'}],
     'name':'allowance','outputs':[{'name':'','type':'uint256'}],'stateMutability':'view','type':'function'},
]
ERC1155_ABI = [
    {'inputs':[{'name':'operator','type':'address'},{'name':'approved','type':'bool'}],
     'name':'setApprovalForAll','outputs':[],'stateMutability':'nonpayable','type':'function'},
    {'inputs':[{'name':'account','type':'address'},{'name':'operator','type':'address'}],
     'name':'isApprovedForAll','outputs':[{'name':'','type':'bool'}],'stateMutability':'view','type':'function'},
]

usdc = w3.eth.contract(address=USDC, abi=ERC20_ABI)
ctf  = w3.eth.contract(address=CTF_TOKEN, abi=ERC1155_ABI)

gas_data     = requests.get('https://gasstation.polygon.technology/v2').json()
max_priority = w3.to_wei(float(gas_data['standard']['maxPriorityFee']) + 10, 'gwei')
max_fee      = w3.to_wei(float(gas_data['standard']['maxFee']) + 20, 'gwei')

def send_tx(tx):
    nonce = w3.eth.get_transaction_count(WALLET, 'pending')
    tx.update({'from': WALLET, 'nonce': nonce, 'gas': 100000,
               'maxFeePerGas': max_fee, 'maxPriorityFeePerGas': max_priority, 'chainId': 137})
    signed = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
    h = w3.eth.send_raw_transaction(signed.raw_transaction)
    r = w3.eth.wait_for_transaction_receipt(h, timeout=120)
    print(f"  {'OK' if r.status==1 else 'FAILED'}: https://polygonscan.com/tx/{h.hex()}")
    time.sleep(4)

# USDC approvals (ERC20)
for name, spender in [('CTF Exchange', CTF_EXCHANGE), ('Neg Risk Exchange', NEG_RISK_EX), ('Neg Risk Adapter', NEG_RISK_ADP)]:
    a = usdc.functions.allowance(WALLET, spender).call()
    print(f'USDC → {name}: {a/1e6:.2f}')
    if a < 10 * 10**6:
        send_tx(usdc.functions.approve(spender, MAX_UINT256).build_transaction({}))
    else:
        print('  Already approved')

# CTF conditional token approvals (ERC1155 setApprovalForAll)
for name, operator in [('CTF Exchange', CTF_EXCHANGE), ('Neg Risk Adapter', NEG_RISK_ADP)]:
    approved = ctf.functions.isApprovedForAll(WALLET, operator).call()
    print(f'CTF Token → {name}: {approved}')
    if not approved:
        send_tx(ctf.functions.setApprovalForAll(operator, True).build_transaction({}))
    else:
        print('  Already approved')

print('\nAll done!')
