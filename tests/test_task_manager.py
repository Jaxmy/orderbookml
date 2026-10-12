"""持久队列、重启恢复及真实成交资金核算测试。"""
import json
import subprocess
import sys
import time
from decimal import Decimal
import pandas as pd
import pytest
from core import task_manager as tasks
from core.order_review import normalize_fills,review_fills


@pytest.fixture
def isolated_queue(tmp_path,monkeypatch):
    """将任务数据库隔离在测试目录，禁止单元测试启动真实后台进程。"""
    monkeypatch.setattr(tasks,'TASK_ROOT',tmp_path)
    monkeypatch.setattr(tasks,'DATABASE',tmp_path/'tasks.sqlite3')
    monkeypatch.setattr(tasks,'ensure_worker',lambda:None)
    return tmp_path


def test_persistent_restart_marks_interrupted_without_reexecuting(isolated_queue):
    """重启接管仅标记中断，不重新执行旧任务，原配置可复制成新任务。"""
    identifier=tasks.submit_task('static',dict(day='2026-10-01'))
    claimed=tasks.claim_next();assert claimed['id']==identifier
    assert tasks.get_task(identifier)['status']=='running'
    tasks.recover_interrupted()
    old=tasks.get_task(identifier)
    assert old['status']=='interrupted' and tasks.claim_next() is None
    new=tasks.retry_task(identifier)
    assert new!=identifier and tasks.get_task(new)['config']==old['config']
    assert tasks.get_task(new)['parent']==identifier


def test_cancel_and_failure_and_single_use_evaluation(isolated_queue,monkeypatch):
    """排队取消不执行，错误原因完整保存，封存测试禁止复制重试。"""
    identifier=tasks.submit_task('training',{})
    assert tasks.cancel_task(identifier) and tasks.get_task(identifier)['status']=='cancelled'
    assert tasks.claim_next() is None
    identifier=tasks.submit_task('static',{})
    def fail(task):
        """返回有明确原因的可控异常，核验失败状态和错误文本持久化。"""
        raise ValueError('Missing market data')
    monkeypatch.setattr(tasks,'dispatch',fail)
    tasks.execute_task(tasks.claim_next())
    assert tasks.get_task(identifier)['error']=='ValueError: Missing market data'
    sealed=tasks.submit_task('acceptance',dict(run_id='unused'))
    tasks.cancel_task(sealed)
    with pytest.raises(ValueError,match='sealed'):tasks.retry_task(sealed)


def test_queue_success_is_atomic_and_parameters_are_preserved(isolated_queue,monkeypatch):
    """任务结果以事务提交，复制实验不修改原始金额或完成报告。"""
    identifier=tasks.submit_task('static',dict(amount='5000',amount_mode='quote_budget'))
    monkeypatch.setattr(tasks,'dispatch',lambda task:dict(filled='2',fee='5'))
    tasks.execute_task(tasks.claim_next())
    assert tasks.get_task(identifier)['result']==dict(filled='2',fee='5')
    repeated=tasks.retry_task(identifier)
    assert tasks.get_task(repeated)['config']==dict(amount='5000',amount_mode='quote_budget')
    assert tasks.get_task(identifier)['status']=='completed'


def test_trade_import_timezone_fees_and_conservation():
    """真实成交映射时区、双方向费用与资金流，独立手算验证，不把现金流当收益。"""
    frame=pd.DataFrame([dict(timestamp='2026-10-01 12:00:00',side='buy',quantity='0.3',price='2500',fee='0.75',id='a'),dict(timestamp='2026-10-01 12:01:00',side='sell',quantity='0.1',price='2600',fee='0.26',id='b')])
    rows=normalize_fills(frame,{k:k for k in frame.columns},'Asia/Shanghai','bybit')
    assert rows[0]['timestamp']=='2026-10-01T04:00:00+00:00'
    result=review_fills(rows)
    assert Decimal(result['net_quote_change'])==Decimal('-491.01')
    assert Decimal(result['net_base_change'])==Decimal('.2')
    assert result['source']=='user_uploaded_fills'
    frame.loc[1,'id']='a'
    with pytest.raises(ValueError,match='Duplicate'):normalize_fills(frame,{k:k for k in frame.columns})
    frame.loc[1,'id']='b';frame.loc[1,'fee']='NaN'
    with pytest.raises(ValueError,match='fee'):normalize_fills(frame,{k:k for k in frame.columns})


def test_real_worker_process_crash_lock_and_recovery(isolated_queue):
    """启动真实独立 Python 进程，验证排他锁、进程崩溃接管和新任务完成；只终止本测试自己创建的进程。"""
    prefix=f"from pathlib import Path; from core import task_manager as t; t.TASK_ROOT=Path({str(isolated_queue)!r}); t.DATABASE=t.TASK_ROOT/'tasks.sqlite3'; "
    with tasks.worker_lock() as acquired:
        assert acquired
        child=subprocess.run([sys.executable,'-c',prefix+'t.run_worker(.1)'],capture_output=True,timeout=20)
        assert child.returncode==0
    identifier=tasks.submit_task('static',dict(day='2026-10-01'))
    child=subprocess.Popen([sys.executable,'-c',prefix+'import time; t.claim_next(); time.sleep(60)'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        deadline=time.monotonic()+20
        while tasks.get_task(identifier)['status']!='running' and time.monotonic()<deadline:time.sleep(.1)
        assert tasks.get_task(identifier)['status']=='running'
    finally:
        child.terminate();child.wait(timeout=20)
    rows=[dict(id='1',timestamp='2026-10-01T12:00:00+00:00',venue='bybit',side='buy',quantity='.3',price='2500',fee='.75')]
    fresh=tasks.submit_task('review',dict(records=rows))
    result=subprocess.run([sys.executable,'-c',prefix+'t.run_worker(.1)'],capture_output=True,timeout=30)
    assert result.returncode==0,result.stderr.decode(errors='replace')
    assert tasks.get_task(identifier)['status']=='interrupted'
    assert tasks.get_task(fresh)['status']=='completed'
    assert tasks.get_task(fresh)['result']['net_quote_change']=='-750.75'


def test_cancel_running_at_progress_checkpoint(isolated_queue,monkeypatch):
    """运行途中取消由数据库跨检查点传递，不发布伪造成功结果。"""
    identifier=tasks.submit_task('training',{})
    def cancelled_compute(task):
        """模拟用户在计算阶段发出取消，下一进度检查应中断。"""
        tasks.cancel_task(task['id'])
        tasks.update_progress(task['id'],dict(stage='training',progress=.5))
    monkeypatch.setattr(tasks,'dispatch',cancelled_compute)
    tasks.execute_task(tasks.claim_next())
    assert tasks.get_task(identifier)['status']=='cancelled' and tasks.get_task(identifier)['result'] is None
