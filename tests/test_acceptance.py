import numpy as np
import pandas as pd
import pytest
from core import acceptance


def setup_acceptance(monkeypatch, tmp_path):
    """隔离验收目录和冻结模型，并把下载及行情样本替换为确定输入，测试无需外网。"""
    monkeypatch.setattr(acceptance,'ACCEPT_ROOT',tmp_path/'acceptance')
    manifest=dict(model_sha256='fixed-weight',training={'validation_label_end_utc':'2026-09-06T00:00:00Z'},
        selected={target:'persistence' for target in acceptance.TARGETS})
    monkeypatch.setattr(acceptance,'load_conditional_model',lambda model_id:({},manifest))
    monkeypatch.setattr(acceptance,'code_hash',lambda:'fixed-code')
    def missing(day,venue):
        """模拟本机没有观察过该日期，允许登记但不真实请求来源。"""
        raise FileNotFoundError(day)
    monkeypatch.setattr(acceptance,'_resolve_book',missing)
    monkeypatch.setattr(acceptance,'_prepare_day',lambda *a,**k:(tmp_path/'books.parquet',{'test_fixture':True}))
    frame=pd.DataFrame([{**{f:1.0 for f in acceptance.FEATURES},'horizon_seconds':60,
                         'adverse_mid_bps':0.0,'future_execution_cost_bps':1.,'future_volatility_bps':1.}]*2)
    monkeypatch.setattr(acceptance,'_day_samples',lambda *a,**k:frame)
    monkeypatch.setattr(acceptance,'predict_with_models',lambda *a,**k:{})
    return acceptance.register_acceptance('2026-10-02','a'*32)


def test_once_only_and_code_change_guard(monkeypatch,tmp_path):
    """登记后代码变化必须拒绝打开；正常打开后禁止二次评价，避免封存测试反复调参。"""
    spec=setup_acceptance(monkeypatch,tmp_path)
    monkeypatch.setattr(acceptance,'code_hash',lambda:'changed')
    with pytest.raises(ValueError,match='changed'):
        acceptance.evaluate_acceptance(spec['run_id'])
    monkeypatch.setattr(acceptance,'code_hash',lambda:'fixed-code')
    monkeypatch.setattr(acceptance,'run_mpc_replay',lambda *a,**k:dict(report_path='fixture',
        results={'mpc':{'status':'complete','reconciliation':{'ok':True}}}))
    result=acceptance.evaluate_acceptance(spec['run_id'])
    assert result['status']=='passed_functional' and result['trained'] is False
    assert len(result['cases'])==8
    with pytest.raises(ValueError,match='already opened'):
        acceptance.evaluate_acceptance(spec['run_id'])
    with pytest.raises(ValueError,match='already registered'):
        acceptance.register_acceptance('2026-10-02','a'*32)


def test_failed_cases_remain_in_acceptance_denominator(monkeypatch,tmp_path):
    """某些订单失败不能从报告删除，整体必须标未完成，而不是只展示成功样本。"""
    spec=setup_acceptance(monkeypatch,tmp_path)
    def replay(day,**kwargs):
        """只让卖单失败，检查八个预定场景是否完整保留。"""
        if kwargs['side']=='sell':
            raise ValueError('fixture sell rejected')
        return dict(report_path='fixture',results={'mpc':{'status':'complete','reconciliation':{'ok':True}}})
    monkeypatch.setattr(acceptance,'run_mpc_replay',replay)
    report=acceptance.evaluate_acceptance(spec['run_id'])
    assert len(report['cases'])==8 and sum(c.get('status')=='failed' for c in report['cases'])==4
    assert report['status']=='incomplete_functional'
