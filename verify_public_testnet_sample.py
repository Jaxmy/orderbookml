"""组件用途：公开第三方测试网样本验证，不是个人操作证明。

原始说明：Read an existing PUBLIC third-party Sepolia receipt; never claim user ownership."""
from web3 import Web3
from core.proof import validate_receipt
from core.io import ROOT,dump,utcnow

if __name__=='__main__':
    result={'checked_at':utcnow(),'personal_interaction_proof':False,'submitted_transaction':False}
    try:
        url='https://ethereum-sepolia-rpc.publicnode.com'
        w=Web3(Web3.HTTPProvider(url,request_kwargs={'timeout':20}))
        if w.eth.chain_id!=11155111: raise ValueError('Not Sepolia')
        token=Web3.to_checksum_address('0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238')
        head=w.eth.block_number
        if not w.eth.get_code(token,block_identifier=head-24): raise ValueError('Missing token contract')
        topic='0x'+w.keccak(text='Transfer(address,address,uint256)').hex().removeprefix('0x')
        logs=w.eth.get_logs({'address':token,'topics':[topic],'fromBlock':head-124,'toBlock':head-24})
        if not logs: raise ValueError('No sample in bounded 100-block search')
        receipt=w.eth.get_transaction_receipt(logs[0]['transactionHash'])
        tx=w.eth.get_transaction(logs[0]['transactionHash'])
        proof=validate_receipt(tx,receipt,w.eth.get_block(receipt['blockNumber']),11155111,11155111,
            tx['to'],topic,head,expected_sender=tx['from'],event_contract=token)
        result.update(status='public_sample_verified',proof=proof,
            explorer='https://sepolia.etherscan.io/tx/0x'+receipt['transactionHash'].hex().removeprefix('0x'),
            contract_source='https://developers.circle.com/stablecoins/usdc-contract-addresses',
            interpretation='Existing third-party public receipt validates software; NOT this user or project performing a transaction')
    except Exception as e:
        result.update(status='unavailable',error=type(e).__name__+': '+str(e)[:250])
    dump(ROOT/'logs'/'public_testnet_sample.json',result)
    print(result)
