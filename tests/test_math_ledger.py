import json
from decimal import Decimal as D
import pytest
from core.execution import sweep, mid, dex_cost
from core.ledger import Ledger,reconcile
from core.lp import inventory, scenario, single_range_swap


@pytest.fixture
def book():
    """构造可控的买卖档位测试输入，允许价格和数量变化，避免依赖网络行情。"""
    return {'id':'manual','available_at':0,'bids_json':json.dumps([['99','.2'],['98','.3']]),
            'asks_json':json.dumps([['100','.2'],['101','.3']])}


def test_hand_buy(book):
    """验证逐档买入、费用和均价与手算一致；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。

    输入参数：book（单位和范围由下方校验及调用方契约限定）。"""
    q=sweep(book,'buy','.5','10')
    assert q['complete'] and D(q['quote'])==D('50.3')
    assert D(q['vwap'])==D('100.6') and D(q['fee'])==D('.0503')
    assert D(q['net_quote'])==D('50.3503')


def test_hand_sell(book):
    """验证逐档卖出、费用和净收入与手算一致；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。

    输入参数：book（单位和范围由下方校验及调用方契约限定）。"""
    q=sweep(book,'sell','.5','10')
    assert D(q['quote'])==D('49.2') and D(q['vwap'])==D('98.4')
    assert D(q['net_quote'])==D('49.1508')


def test_partial_not_extrapolated(book):
    """验证深度不足保留缺量而不外推；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。

    输入参数：book（单位和范围由下方校验及调用方契约限定）。"""
    q=sweep(book,'buy','1')
    assert not q['complete'] and D(q['filled'])==D('.5')


def test_crossed_book_rejected(book):
    """验证交叉盘口拒绝进入计算；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。

    输入参数：book（单位和范围由下方校验及调用方契约限定）。"""
    book['bids_json']='[["102","1"]]'
    with pytest.raises(ValueError):mid(book)


def test_dex_fee_not_double_counted():
    """验证DEX已含池费报价只另加gas；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    r=dex_cost({'side':'buy','quote_usdc':'1500','base_fee_wei':'1000000000'},3000)
    assert D(r['gas_eth'])==D('.0004') and D(r['net_quote'])==D('1501.2')


def test_ledger_identity_and_independent_rebuild():
    """验证账本盈亏恒等式与独立现金流重建；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    a=Ledger('CEX',100)
    a.apply('1','buy','.5','50.3','.0503',0,100,1,'x')
    a.apply('2','sell','.5','49.2','.0492',0,102,2,'y')
    assert a.balances['USDC']==D('9998.8005')
    assert abs(D(a.status(102)['pnl_identity_gap']))<D('1e-20')
    assert reconcile(a.initial,a.events,a.balances)['ok']
    altered=a.balances.copy();altered['USDC']+=D('.01')
    assert not reconcile(a.initial,a.events,altered)['ok']


def test_duplicate_stale_and_insufficient():
    """验证重复委托、陈旧报价和余额不足的拒单；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    a=Ledger('CEX',3000);before=a.balances.copy()
    e=a.apply('1','buy','.05',150,.15,0,3000,1,'expired',reason='stale_cex')
    assert e['status']=='rejected' and a.balances==before
    assert a.apply('1','buy','.05',150,.15,0,3000,1,'x')['status']=='duplicate_rejected'
    assert a.apply('2','sell','2',6000,6,0,3000,2,'x')['reason']=='insufficient_balance'
    assert a.balances==before


def test_dex_gas_pnl_identity():
    """验证链上原生gas消耗计入盈亏恒等式；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    a=Ledger('DEX',3000)
    a.apply('1','buy','.05',151,0,'.0004',3010,1,'q')
    a.apply('2','sell','.05',149,0,'.0004',2990,2,'q2')
    assert a.balances['ETH']==D('.0192')
    assert abs(D(a.status(2990)['pnl_identity_gap']))<D('1e-18')
    assert reconcile(a.initial,a.events,a.balances)['ok']


def test_loss_limit_persists():
    """验证止损一旦触发不能因价格恢复自动抹掉；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    a=Ledger('CEX',3000)
    assert a.apply('1','buy','.05',100,0,0,2000,1,'x')['reason']=='loss_limit'
    assert a.apply('2','buy','.05',150,0,0,3000,2,'x')['reason']=='loss_limit'


def test_stale_reference_does_not_trigger_loss_pause():
    """验证陈旧估值不错误触发暂停；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    a=Ledger('CEX',3000)
    a.apply('1','buy','.05',100,0,0,100,1,'expired',reason='stale_cex')
    assert not a.paused


def test_lp_boundary_and_conservation():
    """验证LP区间边界资产与守恒；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    assert inventory(1,4,9,10)[1]==0
    assert inventory(16,4,9,10)[0]==0
    r=scenario(3000,gas_cost=3)
    assert r['lower']<=2940 and r['upper']>=3060
    assert r['scenarios'][2]['lp_value']==pytest.approx(1000)
    assert r['scenarios'][2]['fee_to_break_even']==pytest.approx(3)


def test_single_range_independent_answer():
    # sqrtP=2, L=1000, zero-for-one dx=10 and fee=0:
    # sqrtP' = 1/(.5+.01)=100/51; dy=2000/51.
    """验证单区间兑换与独立预期答案；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    after,out=single_range_swap(2,1000,10,True,fee=0)
    assert after==pytest.approx(100/51)
    assert out==pytest.approx(2000/51)


def test_real_preflight_book_against_independent_answer():
    """验证真实预检盘口逐档独立核算；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    from pathlib import Path
    path=Path(__file__).resolve().parents[1]/'logs'/'preflight.json'
    if not path.exists():pytest.skip('Read-only preflight has not been run')
    data=json.loads(path.read_text(encoding='utf-8'))
    if not data.get('websocket',{}).get('ok'):pytest.skip('WebSocket preflight unavailable')
    b=data['websocket']['result']['sample']
    if b['id']!='cex-19310291508-1791031096.843400':
        pytest.skip('Preflight replaced: hand-check applies to the archived snapshot ID only')
    assert D(sweep(b,'buy','.5')['net_quote'])==D('1342.310970')
    assert D(sweep(b,'sell','.5')['net_quote'])==D('1339.624035')
