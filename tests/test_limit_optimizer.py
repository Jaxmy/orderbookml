from decimal import Decimal
import pandas as pd
import pytest

from core.limit_optimizer import choose_limit_plan, replay_limit_plan
from core.mpc import _at, _run_replay, _expected_action_cost


def market():
    """构造每秒时间戳更新但档位不变的簿态，便于核验队列和自有深度。"""
    return pd.DataFrame([dict(available_at=float(t), exchange_ts=float(t), mid=100.,
        bids_json='[["99","1"]]', asks_json='[["101","1"]]') for t in range(0,301)])


def tape():
    """在撤单延迟窗口和确认后各放一笔主动卖出，区分可计入的成交边界。"""
    return pd.DataFrame([dict(available_at=t, price=99., volume=.3, side='sell',rpi=0)
                         for t in (95.,104.,105.1,106.)])


def args():
    """提供买单测试的同一资金、精度、手续费和撤单延迟，避免对照条件漂移。"""
    return dict(decision_at=100.,side='buy',quantity='0.5',maker_bps=2,taker_bps=10,
        tick=Decimal('1'),quantity_step=Decimal('0.01'),quote_balance=1000.,base_balance=0.,
        latency_ms=0,cancel_latency_ms=250,max_book_age_ms=1500)


def test_selection_cannot_see_future_tape():
    """改变决策后的成交不应改变候选评分或选中方案，未来仅供回放使用。"""
    def choose(trades):
        """调用与看板相同的选择器，故意传完整数据以验证内部时间隔离。"""
        return choose_limit_plan(_at(market(),100,1500),trades,decision_at=100,side='buy',
            quantity='.5',wait_seconds=[5,10],offsets=[0],maker_bps=2,taker_bps=10,
            tick=Decimal('1'),risk_weight=0,quote_balance=1000,base_balance=0,quantity_step='.01')
    before=choose(tape());changed=tape();changed.loc[changed.available_at>100,'volume']=10000
    assert before == choose(changed)


def test_cancel_latency_fill_then_taker_and_independent_accounting():
    """撤单确认前的两笔可成交，确认后成交被排除，余量按主动费率补齐并对账。"""
    result=replay_limit_plan(market(),tape(),dict(kind='passive_then_taker',wait_seconds=5,
        offset_ticks=0,amend=False),scenario='optimistic',**args())
    assert Decimal(result['filled_quantity'])==Decimal('0.5')
    assert all(x['kind']=='maker' for x in result['fills'])
    assert max(x['at'] for x in result['fills']) == 105.1
    conservative=replay_limit_plan(market(),tape(),dict(kind='passive_then_taker',wait_seconds=5,
        offset_ticks=0,amend=False),scenario='conservative',**args())
    assert Decimal(conservative['filled_quantity'])==Decimal('0.5')
    assert Decimal(conservative['net_quote'])==Decimal('.5')*101*Decimal('1.001')
    assert conservative['reconciliation']['ok'] and result['reconciliation']['ok']


def test_amendment_requires_cancel_ack_and_new_queue():
    """改价只能在旧单撤单确认之后提交；两段不能重复使用同一成交。"""
    result=replay_limit_plan(market(),tape(),dict(kind='passive_then_taker',wait_seconds=10,
        offset_ticks=0,amend=True),scenario='middle',**args())
    submits=[x['at'] for x in result['events'] if x['status']=='submit_limit']
    assert submits == [100.,105.25]
    assert result['reconciliation']['ok']
    assert Decimal(result['filled_quantity'])<=Decimal('.5')


def test_sell_partial_preserves_balance():
    """卖出库存不足时只能部分完成，不能通过负持仓或虚构成交满足目标。"""
    kw=args();kw.update(side='sell',base_balance=.2,quote_balance=0)
    result=replay_limit_plan(market(),tape(),dict(kind='immediate',wait_seconds=0),
                             scenario='conservative',**kw)
    assert result['status']=='partial' and Decimal(result['filled_quantity'])==Decimal('.2')
    assert result['reconciliation']['ok']


def test_all_mpc_baselines_obey_cap_and_unchanged_depth_is_not_reused():
    """三个方案均遵守单次上限，时间戳刷新不能补回已经吃完的同一档位。"""
    frame=market()
    for policy in ('mpc','immediate','equal'):
        result=_run_replay(frame,start_at=100,side='buy',quantity=1.5,quantity_step=.1,
            horizon_seconds=30,interval_seconds=10,fee_bps=10,latency_ms=0,max_book_age_ms=1500,
            quote_balance=1000,base_balance=0,policy=policy,max_child_units=5,risk_aversion=0)
        assert all(x['requested']<=.5 for x in result['fills'])
        assert result['filled_quantity']<=1.+1e-10
        assert result['status']=='partial'


def test_ml_horizon_outside_support_uses_explicit_fallback():
    """超过训练期限的动作不调用模型，也不把 120 秒悄悄截为 60 秒。"""
    frame=market();book=_at(frame,100,1500)
    _, forecast=_expected_action_cost(book,frame[frame.available_at<=100], 'buy',.5,10,120,0,{'bad':object()})
    assert forecast['forecast'].startswith('persistence fallback')


def test_s3_dashboard_selects_new_report_and_preserves_reference_on_rerun(tmp_path, monkeypatch):
    """从看板输入并运行真实缓存案例，确认页面展示新报告且历史复跑保留撤改原方案。"""
    import json
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    from core.io import ROOT
    from core.store import engine_for
    url='sqlite:///'+(tmp_path/'limit-ui.db').as_posix()
    monkeypatch.setenv('DATABASE_URL',url)
    from tests.ui_queue import use_inline_queue
    use_inline_queue(monkeypatch,tmp_path)
    app=AppTest.from_file(str(ROOT/'market_app.py')).run(timeout=30)
    app.sidebar.radio[0].set_value('优化求解与限价情景').run(timeout=30)
    app.radio(key='optimizer_component').set_value('限价方案优化（S3）').run(timeout=30)
    app.selectbox(key='s3_day').set_value('2026-09-03')
    app.checkbox(key='s3_reference_amend').set_value(True)
    next(b for b in app.button if b.label=='Compare limit-order plans').click().run(timeout=40)
    assert not app.exception and not app.error
    first=Path(next(s for s in app.selectbox if s.label=='Saved limit-order comparisons').value)
    report=json.loads(first.read_text(encoding='utf-8'))
    assert report['config']['reference_plan']['amend'] is True
    assert all(r['reconciliation']['ok'] for r in report['reference_results'].values())
    next(b for b in app.button if b.label=='Repeat this saved comparison').click().run(timeout=40)
    assert not app.exception and not app.error
    second=Path(next(s for s in app.selectbox if s.label=='Saved limit-order comparisons').value)
    assert second!=first
    assert json.loads(second.read_text(encoding='utf-8'))['config']==report['config']
    engine_for(url).dispose()
