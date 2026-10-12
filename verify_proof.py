"""组件用途：测试网回执及事件验证。"""
import os
import argparse
from web3 import Web3
from core.proof import validate_receipt
from core.io import ROOT,dump

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--tx',required=True); p.add_argument('--to',required=True)
    p.add_argument('--topic',required=True); p.add_argument('--chain-id',type=int,default=11155111)
    p.add_argument('--sender',required=True); p.add_argument('--event-contract')
    a=p.parse_args()
    if len(a.tx)!=66 or not a.tx.startswith('0x') or any(c not in '0123456789abcdefABCDEF' for c in a.tx[2:]):
        raise ValueError('Expected a 32-byte transaction hash')
    w=Web3(Web3.HTTPProvider(os.environ['TESTNET_RPC_URL'],request_kwargs={'timeout':20}))
    tx=w.eth.get_transaction(a.tx); receipt=w.eth.get_transaction_receipt(a.tx)
    result=validate_receipt(tx,receipt,w.eth.get_block(receipt['blockNumber']),w.eth.chain_id,a.chain_id,a.to,a.topic,w.eth.block_number,
        expected_sender=a.sender,event_contract=a.event_contract)
    dump(ROOT/'logs'/'proofs'/(a.tx+'.json'),result)
    print(result)
