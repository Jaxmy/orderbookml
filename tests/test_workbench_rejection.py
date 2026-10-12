"""订单工作台回归：行情过期拒单、旧报告及金额单位都必须可正确处理。"""
from decimal import Decimal as D
import threading
import pytest
from streamlit.testing.v1 import AppTest
from core.io import ROOT
from core.experiment_engine import _simulate, run_experiment


@pytest.mark.parametrize('mode,amount',[('quote_budget',D('5000')),('base_quantity',D('0.3'))])
@pytest.mark.parametrize('rows',[[],[dict(exchange_ts=90)]])
def test_rejection_has_complete_financial_fields(mode,amount,rows):
    """无过去盘口或盘口过期时，返回零成交、零费用和全部余量；价格成本不可计算。"""
    result=_simulate(rows,100,60,'buy',mode,amount,D(10),250,3000,D('.00000001'),10,'twap_equal_slices')
    assert result['status']=='rejected'
    assert result['fee_quote']==result['net_quote']==result['gross_quote']==result['filled_base']=='0'
    assert result['average_price'] is None and result['all_in_shortfall_bps'] is None
    assert D(result['unspent_quote'] if mode=='quote_budget' else result['remaining_base'])==amount


def test_invalid_display_text_rejected_before_loading_data():
    """未知输入单位在读数据前被拒绝，不能把预算文案当 ETH 数量继续成交。"""
    with pytest.raises(ValueError,match='amount mode'):
        run_experiment(dict(amount_mode='USDC budget including fees',side='buy'),None,threading.Event())


@pytest.mark.parametrize('language',['English','中文'])
def test_workbench_old_rejection_and_budget_submission(language,monkeypatch):
    """复现缺 fee_quote 的旧未成交报告，同时检查预算和 ETH 切换提交正确内部单位及金额。"""
    import core.task_manager as engine
    configs=[]
    legacy=dict(window=dict(available_utc_days=['2026-10-04']),data=dict(venue='Bybit'),
        config=dict(side='buy'),results={key:dict(status='rejected',reason='decision_stale_book_at_arrival',
        completion_pct=0,filled_base='0',unspent_quote='5000',fills=[]) for key in ['immediate','equal_slice_baseline']})
    def capture(config):
        """记录看板传来的参数，返回本地测试标识，避免触发网络下载。"""
        configs.append(config);return 'test-order'
    monkeypatch.setattr(engine,'submit_execution',capture)
    monkeypatch.setattr(engine,'get_execution_job',lambda identifier:dict(status='completed'))
    monkeypatch.setattr(engine,'get_execution_result',lambda identifier:legacy)
    app=AppTest.from_file(str(ROOT/'market_app.py')).run(timeout=30)
    app.selectbox(key='ui_language').set_value(language).run(timeout=30)
    app.number_input(key='experiment_amount_quote_budget').set_value(5000.)
    next(b for b in app.button if b.label in ['Prepare data and simulate','准备数据并运行模拟']).click().run(timeout=30)
    assert not app.exception and not app.error
    assert configs[-1]['amount_mode']=='quote_budget' and configs[-1]['amount']=='5000.0'
    assert any('quote' in w.value or '报价' in w.value for w in app.warning)
    app.radio(key='experiment_mode_v2').set_value('base_quantity').run(timeout=30)
    app.number_input(key='experiment_amount_base_quantity').set_value(.3)
    next(b for b in app.button if b.label in ['Prepare data and simulate','准备数据并运行模拟']).click().run(timeout=30)
    assert not app.exception and not app.error
    assert configs[-1]['amount_mode']=='base_quantity' and configs[-1]['amount']=='0.3'

@pytest.mark.parametrize('language',['English','中文'])
def test_failed_simulation_displays_reason_in_active_and_history(language,monkeypatch):
    """失败任务的当前结果和历史结果都显示缺少哪天的 OKX 数据以及上传建议。"""
    import core.task_manager as engine
    job=dict(id='missing-okx',status='failed',created_at='2026-10-06T09:00:00',
             config=dict(start_date='2026-10-04'),error='FileNotFoundError: Upload the official OKX ETH-USDC L2 archive for 2026-10-04 in the dashboard first')
    monkeypatch.setattr(engine,'get_execution_job',lambda identifier:job)
    monkeypatch.setattr(engine,'execution_history',lambda:[job])
    app=AppTest.from_file(str(ROOT/'market_app.py'))
    app.session_state['active_experiment_id']=job['id']
    app.run(timeout=30)
    app.selectbox(key='ui_language').set_value(language).run(timeout=30)
    assert not app.exception and len(app.error)==2
    for error in app.error:
        assert '2026-10-04' in error.value and 'OKX' in error.value
        assert ('Upload' if language=='English' else '上传') in error.value
        assert 'FileNotFoundError' not in error.value


def test_failure_formatter_preserves_unknown_reason_and_hides_private_fields():
    """未识别原因仍展示具体说明，屏蔽本机地址和连接口令，不输出堆栈。"""
    from core.dashboard_errors import describe_failure
    value=describe_failure('RuntimeError: Could not open D:\\private\\data.bin token=abc123\nTraceback hidden')
    assert 'Could not open' in value and 'private' not in value and 'abc123' not in value and 'Traceback' not in value
    assert 'No reason was recorded' in describe_failure(None)

    assert describe_failure('HTTP 404 https://example.com/data?token=abc')=='HTTP 404 https://example.com/data'
