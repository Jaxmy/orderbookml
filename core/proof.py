"""组件用途：按事件签名解码 ERC20 Transfer 或 V3 Swap 的地址及有符号金额；未知事件明确未验证金额。；逐项检查测试网、成功状态、交易目的/发送人、区块一致性和所需日志，拒绝主网或回滚；第三方回执不证明个人操作。。

原始说明：Read-only testnet evidence validation; receipt existence alone is insufficient."""
from web3 import Web3

def decode_event(event):
    """按事件签名解码 ERC20 Transfer 或 V3 Swap 的地址及有符号金额；未知事件明确未验证金额。

    输入参数：event（单位和范围由下方校验及调用方契约限定）。"""
    signature=event['topics'][0].hex().removeprefix('0x')
    codec=Web3().codec
    data=bytes.fromhex(event['data'].removeprefix('0x')) if isinstance(event['data'],str) else bytes(event['data'])
    address=lambda x:'0x'+bytes(x)[-20:].hex()
    transfer=Web3.keccak(text='Transfer(address,address,uint256)').hex().removeprefix('0x')
    swap=Web3.keccak(text='Swap(address,address,int256,int256,uint160,uint128,int24)').hex().removeprefix('0x')
    if signature==transfer:
        if len(event['topics'])!=3: raise ValueError('Malformed Transfer topics')
        amount,=codec.decode(['uint256'],data)
        return dict(event='Transfer',sender=address(event['topics'][1]),recipient=address(event['topics'][2]),amount_raw=str(amount))
    if signature==swap:
        if len(event['topics'])!=3: raise ValueError('Malformed Swap topics')
        amount0,amount1,sqrt_price,liquidity,tick=codec.decode(['int256','int256','uint160','uint128','int24'],data)
        return dict(event='Swap',sender=address(event['topics'][1]),recipient=address(event['topics'][2]),
            amount0_raw=str(amount0),amount1_raw=str(amount1),sqrt_price_x96=str(sqrt_price),liquidity=str(liquidity),tick=tick)
    return dict(event='unrecognized',amounts_verified=False)

def validate_receipt(transaction,receipt,block,chain_id,expected_chain,expected_to,required_topic,head,
                     expected_sender=None,event_contract=None):
    """逐项检查测试网、成功状态、交易目的/发送人、区块一致性和所需日志，拒绝主网或回滚；第三方回执不证明个人操作。

    输入参数：transaction、receipt、block、chain_id、expected_chain、expected_to、required_topic、head、expected_sender、event_contract（单位和范围由下方校验及调用方契约限定）。"""
    if chain_id!=expected_chain or chain_id==1: raise ValueError('Wrong network / mainnet disallowed')
    if receipt['status']!=1: raise ValueError('Reverted transaction')
    if transaction['to'].lower()!=expected_to.lower(): raise ValueError('Unexpected destination')
    if expected_sender and transaction['from'].lower()!=expected_sender.lower(): raise ValueError('Unexpected sender')
    if receipt['blockHash']!=block['hash']: raise ValueError('Reorg / inconsistent block')
    if transaction['hash']!=receipt['transactionHash']: raise ValueError('Transaction mismatch')
    if head-receipt['blockNumber']<12: raise ValueError('Insufficient confirmations')
    matching=[x for x in receipt['logs'] if x['address'].lower()==(event_contract or expected_to).lower()
              and x['topics'] and x['topics'][0].hex().removeprefix('0x')==required_topic.removeprefix('0x')]
    if not matching: raise ValueError('Expected contract event absent')
    return dict(status='verified',chain_id=chain_id,transaction=receipt['transactionHash'].hex(),
        block=receipt['blockNumber'],confirmations=head-receipt['blockNumber'],matching_events=len(matching),
        decoded_events=[decode_event(x) for x in matching],sender_checked=expected_sender is not None,
        scope='Network/destination/status/block/event verified; supported Transfer/Swap raw amounts decoded; wallet ownership not established by a receipt')
