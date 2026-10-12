"""本机任务服务接口契约：与看板共用持久队列，不提交真实交易。"""
import pytest
from fastapi import HTTPException
from core import task_manager
from service import app,create_experiment,experiment,experiments,cancel_experiment


def test_task_api_persistence_cancel_and_sealed_guard(monkeypatch,tmp_path):
    """验证提交后查询到同一参数、持久取消、未知标识404及拒绝绕过封存预登记。"""
    monkeypatch.setattr(task_manager,'TASK_ROOT',tmp_path)
    monkeypatch.setattr(task_manager,'DATABASE',tmp_path/'tasks.sqlite3')
    monkeypatch.setattr(task_manager,'ensure_worker',lambda:None)
    identifier=create_experiment(dict(kind='review',config=dict(records=[])))['id']
    assert experiment(identifier)['config']==dict(records=[])
    assert experiments(40)[0]['id']==identifier
    assert cancel_experiment(identifier)['cancel_requested']
    assert experiment(identifier)['status']=='cancelled'
    with pytest.raises(HTTPException) as missing:experiment('unknown')
    assert missing.value.status_code==404
    with pytest.raises(HTTPException) as sealed:create_experiment(dict(kind='acceptance',config={}))
    assert sealed.value.status_code==400
    assert '/experiments/{identifier}/cancel' in {route.path for route in app.routes}
