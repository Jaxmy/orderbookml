"""独立事件 ABI、因果时间与费用校验；不依赖公共网络。"""
from types import SimpleNamespace
import pytest
from web3 import Web3
from hexbytes import HexBytes
from core.chain_history import decode_event,block_at,SWAP,MINT,BURN,compare_channels
import pandas as pd
import json
from core import chain_history


def test_decode_signed_swap_and_liquidity_events():
    """手工编码买入兑换与正负流动性事件，验证精度、符号、区块内位置和负 tick。"""
    w=Web3();reader=SimpleNamespace(w3=w)
    item=dict(blockNumber=100,blockHash=HexBytes('0x'+'11'*32),transactionHash=HexBytes('0x'+'22'*32),transactionIndex=3,logIndex=8,
        topics=[w.keccak(text=SWAP)],data=w.codec.encode(['int256','int256','uint160','uint128','int24'],[750000000,-300000000000000000,2**96,123,-5]))
    row=decode_event(reader,item,dict(timestamp=1700000000))
    assert row['usdc_pool_delta']=='750' and row['weth_pool_delta']=='-0.3'
    assert row['tick']==-5 and row['transaction_index']==3 and row['log_index']==8
    for signature,delta,types,values in [(MINT,'123',['address','uint128','uint256','uint256'],['0x'+'33'*20,123,1000000,10**18]),(BURN,'-123',['uint128','uint256','uint256'],[123,1000000,10**18])]:
        item['topics']=[w.keccak(text=signature),HexBytes('0x'+'00'*32),w.codec.encode(['int24'],[-20]),w.codec.encode(['int24'],[10])]
        item['data']=w.codec.encode(types,values)
        row=decode_event(reader,item,dict(timestamp=1700000000))
        assert row['liquidity_delta']==delta and row['tick_lower']==-20 and row['tick_upper']==10
        assert row['usdc_amount']=='1' and row['weth_amount']=='1'
    item['topics'][0]=w.keccak(text='Unsupported()')
    with pytest.raises(ValueError,match='signature'):decode_event(reader,item,dict(timestamp=1700000000))


def test_block_lookup_handles_missed_slot_without_future_block():
    """人为设置漏槽，验证查找只返回过去区块，不能用下一块补齐目标时刻。"""
    times=[0,12,24,48,60]
    eth=SimpleNamespace(block_number=4,get_block=lambda number:dict(number=number,timestamp=times[number]))
    reader=SimpleNamespace(w3=SimpleNamespace(eth=eth))
    assert block_at(reader,47)['number']==2
    assert block_at(reader,48)['number']==3
    with pytest.raises(ValueError,match='latest'):block_at(reader,61)


def test_chain_comparison_rejects_implicit_wrapping_and_bad_fees():
    """网络调用前拒绝未经同意的 WETH 结算及 NaN 手续费，不把参数错误展示成市场缺数据。"""
    with pytest.raises(ValueError,match='WETH'):compare_channels('2026-10-01','12:00:00','buy','.3',{'bybit':10,'okx':10})
    with pytest.raises(ValueError,match='fees'):compare_channels('2026-10-01','12:00:00','buy','.3',{'bybit':float('nan'),'okx':10},weth_accepted=True)


def test_channel_comparison_gas_and_future_book_exclusion(monkeypatch,tmp_path):
    """手算池费用已含750、gas1；未来便宜盘口不应影响当时渠道报价，交易所只加一次手续费。"""
    at=pd.Timestamp('2026-10-01T12:00:00Z').timestamp()
    header=dict(number=100,timestamp=int(at)-12,baseFeePerGas=10**9,hash=HexBytes('0x'+'11'*32))
    class Reader:
        """给出固定历史区块与可手算报价的测试只读节点。"""
        def __init__(self,config):
            """保存代币配置及固定区块查询，避免测试接触公网。"""
            self.config=config;self.pool='pool';self.w3=SimpleNamespace(eth=SimpleNamespace(get_block=lambda number:header))
        def verify(self):
            """测试中省略网络验证，固定元数据由夹具负责。"""
            return {}
        def call(self,address,signature,inputs,args,outputs,block):
            """返回池已含费报价或 sqrt 价格20000倍 Q96，对应2500USDC。"""
            return (2**96*20000,0,0,0,0,0,True) if signature=='slot0()' else (750000000,0,0,999999)
    monkeypatch.setattr(chain_history,'DexReader',Reader)
    monkeypatch.setattr(chain_history,'ROOT',tmp_path)
    monkeypatch.setattr(chain_history,'read',lambda path:dict(usdc='u',weth='w',fee=500,quoter='q'))
    monkeypatch.setattr(chain_history,'block_at',lambda reader,target:header)
    from core import experiment_engine
    monkeypatch.setattr(experiment_engine,'_resolve_book',lambda day,venue:('ignored',{'books_sha256':'verified'}))
    frame=pd.DataFrame([dict(exchange_ts=at-.3,bids_json=json.dumps([['2499','1']]),asks_json=json.dumps([['2500','1']])),dict(exchange_ts=at+.1,bids_json=json.dumps([['.9','1']]),asks_json=json.dumps([['1','1']]))])
    monkeypatch.setattr(chain_history.pd,'read_parquet',lambda *args,**kwargs:frame.copy())
    result=compare_channels('2026-10-01','12:00:00','buy','.3',{'bybit':10,'okx':10},weth_accepted=True)
    assert result['rows'][0]['total_quote']=='751.0000'
    assert result['rows'][1]['total_quote']=='750.750000'
    assert result['rows'][1]['books_sha256']=='verified'
    assert result['latency_effect_included'] is False
