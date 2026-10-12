import json
import pandas as pd
import pytest
from core.orderbook import OrderBook
from core.defi import Q96,Q128,v2_exact_input,v3_exact_input,fee_growth_inside,accrued_fees,lp_attribution
from core.research import partition
from core.research import build_features, FEATURES

def msg(kind='snapshot',u=10,ts=1000,b=None,a=None):
    """生成Bybit测试快照/增量消息，允许编号、时间和档位覆盖。

    输入参数：kind、u、ts、b、a（单位和范围由下方校验及调用方契约限定）。"""
    return dict(type=kind,ts=ts,data=dict(s='ETHUSDC',u=u,b=b if b is not None else [['99','2']],a=a if a is not None else [['101','3']]))

def test_reconstruction_gap_resnapshot():
    """验证快照/增量删除、编号断档后失效与新快照恢复；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    ob=OrderBook(); assert not ob.apply(msg('delta'))
    assert ob.apply(msg())
    assert ob.apply(msg('delta',11,1100,[['99','0'],['98','4']],[]))
    assert json.loads(ob.row(1.35)['bids_json'])==[['98','4']]
    assert not ob.apply(msg('delta',13,1200))
    assert not ob.valid
    assert ob.apply(msg('snapshot',15,1300))
    assert ob.gaps==1

def test_v2_hand_computation():
    """验证V2恒定乘积输出与独立整数手算；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    assert v2_exact_input(1000,10000,20000)==1813

def test_v3_crossing_and_unknown_depth():
    """验证V3跨tick流动性更新及未知边界停止；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    r=v3_exact_input(Q96,1000,1500,False,[(2*Q96,500),(3*Q96,0)],0)
    assert r['complete'] and r['ticks_crossed']==1
    # 1000*(1-1/2) + floor(1500*(1/2-3/7)) = 500+107.
    assert r['amount_out']==607 and r['liquidity_after']==1500
    partial=v3_exact_input(Q96,1000,1500,False,[(2*Q96,500)],0)
    assert not partial['complete'] and partial['remaining']==500
    reverse=v3_exact_input(2*Q96,1000,500,True,[(Q96,0)],0)
    assert reverse['amount_out']==1000 and reverse['complete']

def test_fee_growth_and_attribution():
    """验证区间手续费增长和LP盈亏归因；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    assert fee_growth_inside(10*Q128,2*Q128,3*Q128,0,-10,10)==5*Q128
    assert accrued_fees(2,4*Q128,5*Q128)==2
    assert lp_attribution(1000,1010,1020,15,2)['excess_vs_hodl']==3

def test_partition_purges_horizon():
    """验证未来标签跨分区边界剔除；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    x=pd.DataFrame({'t':[0,9,10], 'target_t':[5,14,15], 'target_available_at':[5,14,15]})
    assert partition(x,0,10).t.tolist()==[0]

def test_volatility_label_never_enters_features():
    """验证未来波动标签不得进入决策特征；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    b=pd.DataFrame([dict(id=str(i),available_at=float(i),
        bids_json=json.dumps([[str(99+i*.001),'1']]),asks_json=json.dumps([[str(101+i*.001),'1']])) for i in range(240)])
    before=build_features(b,0,240)
    b.loc[b.available_at>120,'asks_json']='[["150","1"]]'
    after=build_features(b,0,240)
    pd.testing.assert_frame_equal(before[before.t<=120][FEATURES],after[after.t<=120][FEATURES])
    assert 'vol_target' not in FEATURES and 'y' not in FEATURES

def test_decision_features_do_not_require_future_labels():
    """验证在线特征不需要未来标签；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    from core.model import features
    b=pd.DataFrame([dict(id=str(i),available_at=float(i),bids_json='[["99","1"]]',asks_json='[["101","1"]]') for i in range(240)])
    full=features(b,0,240,include_unlabeled=True)
    cut=features(b[b.available_at<=120],0,240,include_unlabeled=True)
    pd.testing.assert_frame_equal(full[full.t<=120][FEATURES],cut[cut.t<=120][FEATURES])
    assert cut[cut.t==120].y.isna().all()

def test_arbitrage_fees_not_double_counted():
    """验证双向套利池费不重复扣除及陈旧报价拒绝；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    from core.arbitrage import opportunity
    book=dict(available_at=10,bids_json='[["99","2"]]',asks_json='[["101","2"]]')
    sell=dict(available_at=10,quantity='1',side='sell',quote_usdc='105',block_hash='a')
    buy=dict(available_at=10,quantity='1',side='buy',quote_usdc='100',block_hash='a')
    r=opportunity(book,sell,buy,1,10,fee_bps=10,gas_usdc='1')
    assert float(r['net_usdc']['buy_cex_sell_dex'])==2.899
    assert opportunity(book,sell,buy,1,14)['status']=='rejected'

def test_store_idempotent_and_retention(tmp_path):
    """验证缓存id去重和六小时保留窗口；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。

    输入参数：tmp_path（单位和范围由下方校验及调用方契约限定）。"""
    from core.store import Store
    store=Store('sqlite:///'+(tmp_path/'test.db').as_posix())
    row=dict(id='one',available_at=0)
    store.put('book',row); store.put('book',row)
    assert len(store.latest('book'))==1
    store.put('book',dict(id='two',available_at=21601))
    assert len(store.latest('book'))==1 and store.latest('book')[0]['id']=='two'
    store.engine.dispose()

def test_testnet_proof_rejects_wrong_chain_and_revert():
    """验证错误网络与回滚回执拒绝；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    from core.proof import validate_receipt
    topic=b'x'*32
    tx=dict(to='0xabc',hash=b't')
    receipt=dict(status=1,blockHash=b'b',blockNumber=10,transactionHash=b't',logs=[dict(address='0xabc',topics=[topic],data=b'')])
    assert validate_receipt(tx,receipt,{'hash':b'b'},11155111,11155111,'0xabc',topic.hex(),25)['status']=='verified'
    with pytest.raises(ValueError): validate_receipt(tx,receipt,{'hash':b'b'},1,11155111,'0xabc',topic.hex(),25)
    receipt['status']=0
    with pytest.raises(ValueError): validate_receipt(tx,receipt,{'hash':b'b'},11155111,11155111,'0xabc',topic.hex(),25)

def test_market_dashboard_all_pages(tmp_path,monkeypatch):
    """验证各看板页面实际渲染无异常；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。

    输入参数：tmp_path、monkeypatch（单位和范围由下方校验及调用方契约限定）。"""
    from streamlit.testing.v1 import AppTest
    from core.io import ROOT
    url='sqlite:///'+(tmp_path/'dashboard.db').as_posix()
    monkeypatch.setenv('DATABASE_URL',url)
    app=AppTest.from_file(str(ROOT/'market_app.py')).run(timeout=20)
    assert not app.exception
    for name in ['跨所数据与套利','历史研究与 ML','成交量与订单流','执行回放与风险','DeFi 与 LP 历史','优化求解与限价情景']:
        app.sidebar.radio[0].set_value(name).run(timeout=20)
        assert not app.exception
    from core.store import engine_for
    engine_for(url).dispose()

def test_health_uses_market_freshness_and_worker_state(monkeypatch):
    """验证API健康不能把已停worker或陈旧行情标为可执行；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。

    输入参数：monkeypatch（单位和范围由下方校验及调用方契约限定）。"""
    import service
    class FakeStore:
        """提供隔离的数据库心跳替身，避免健康测试依赖真实数据库。"""
        def health(self): 
            """返回固定的心跳和worker状态，用于检查市场新鲜度判断。"""
            return {'cex':{'received_at':10},'dex':{'received_at':10},'worker':{'status':'stopped'}}
    monkeypatch.setattr(service,'Store',FakeStore)
    monkeypatch.setattr(service.time,'time',lambda:20)
    result=service.health()
    assert result['stale']=={'cex':True,'dex':False}
    assert result['database']=='connected' and not result['market_ready']

def test_trade_flow_bucket_is_causal_and_rpi_separate():
    """验证成交聚合桶结束后才可用并单列RPI；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    from core.flow import aggregate_trades
    tape=pd.DataFrame({'available_at':[1.,59.,60.],'side':['buy','sell','buy'],
        'price':[100.,102.,200.],'volume':[2.,1.,100.],'rpi':[0,1,0]})
    result=aggregate_trades(tape,60)
    first=result.iloc[0]
    assert first.available_at==60 and first.volume_eth==3
    assert first.vwap==pytest.approx(302/3) and first.flow_imbalance==pytest.approx(1/3)
    assert first.rpi_volume_eth==1

def test_proof_decodes_signed_swap_amounts():
    """验证Swap事件有符号金额解码；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    from web3 import Web3
    from core.proof import decode_event
    w=Web3()
    e=dict(topics=[w.keccak(text='Swap(address,address,int256,int256,uint160,uint128,int24)'),bytes(32),bytes(32)],
        data=w.codec.encode(['int256','int256','uint160','uint128','int24'],[100,-200,2**96,1000,-1]))
    result=decode_event(e)
    assert result['amount0_raw']=='100' and result['amount1_raw']=='-200' and result['tick']==-1

def test_live_prediction_ignores_future_rows():
    """验证实时冻结模型不读未来记录；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    from core.live_model import LiveModel
    model=LiveModel.__new__(LiveModel)
    model.models={'execution_cost':object(),'volatility':object()}
    model.manifest={'model_sha256':'test','tasks':{k:{'selected':'persistence'} for k in model.models}}
    rows=[dict(id=str(i),available_at=float(i),bids_json='[["99","1"]]',asks_json='[["101","1"]]') for i in range(180)]
    a=model.predict(rows,120)
    for row in rows[121:]: row['asks_json']='[["150","1"]]'
    b=model.predict(rows,120)
    assert a['outputs']==b['outputs'] and b['latest_feature_source_at']<=120
