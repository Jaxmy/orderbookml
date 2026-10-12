"""P3 样本外验收：先锁定配置与代码，再下载未使用日期并只评价一次。"""
from __future__ import annotations
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error

from .conditional_model import load_conditional_model, _day_samples, FEATURES, TARGETS, predict_with_models
from .experiment_engine import _prepare_day, _resolve_book, _bytes, DATA_CAP
from .io import ROOT, read, dump, code_hash, sha, utcnow, log
from .mpc import run_mpc_replay

ACCEPT_ROOT = ROOT / 'data' / 'experiments' / 'acceptance'
_POOL = ThreadPoolExecutor(max_workers=1,thread_name_prefix='sealed-acceptance')
_CANCEL = {}


def register_acceptance(day, model_id):
    """在读取测试行情前锁定日期、模型、代码和八个固定订单场景；已缓存/已注册日期拒绝。

    此守卫能证明本应用没有先下载此日再登记；不能证明其他软件或人没有看过该市场。
    阈值不要求策略胜出，所有失败场景也必须记录，登记后不得调参再打开同日测试。
    """
    date = pd.Timestamp(day, tz='UTC')
    if date >= pd.Timestamp.now(tz='UTC').normalize():
        raise ValueError('Acceptance requires a completed UTC day')
    _, manifest = load_conditional_model(model_id)
    if date.timestamp() <= pd.Timestamp(manifest['training']['validation_label_end_utc']).timestamp():
        raise ValueError('Acceptance date must follow the frozen validation cutoff')
    try:
        _resolve_book(day, 'bybit')
    except FileNotFoundError:
        pass
    else:
        raise ValueError('This date is already cached/observed; choose an unused day')
    for path in ACCEPT_ROOT.glob('*/specification.json'):
        if read(path)['day'] == day:
            raise ValueError('This date was already registered; re-use its evidence instead of re-tuning')
    run_id = uuid.uuid4().hex
    spec = dict(run_id=run_id, day=day, model_id=model_id, model_sha256=manifest['model_sha256'],
        code_sha256=code_hash(), registered_at=utcnow(),
        cases=[dict(utc_time=time,side=side,quantity=quantity) for time in ('12:00:00','16:00:00')
               for side in ('buy','sell') for quantity in ('0.1','0.3')],
        parameters=dict(horizon_seconds=60,interval_seconds=10,max_child_pct=100,fee_bps=10,
                        risk_aversion=0.5,quote_balance=5000,base_balance=1,latency_ms=250,
                        max_book_age_ms=3000,quantity_step='0.01'),
        acceptance='functional completion, causality and reconciliation; no requirement to outperform',
        scope='one new day and eight predeclared orders; not long-term generalization')
    folder=ACCEPT_ROOT/run_id;folder.mkdir(parents=True,exist_ok=False)
    dump(folder/'specification.json',spec)
    log('acceptance_registered',run_id=run_id,day=day,model_id=model_id)
    return spec


def evaluate_acceptance(run_id, progress=None, cancelled=None):
    """一次性打开已登记日：先写 opened，再下载/核验、预测评分与八场景回放，绝不重新训练。

    代码或权重变化、重复打开均拒绝；网络失败保留失败证据，不把同日重新登记为封存测试。
    每个场景单独保存成功/失败，对账与完成率是验收结果，收益改善为独立事实。
    """
    if len(run_id)!=32 or not run_id.isalnum():
        raise ValueError('Invalid acceptance identifier')
    folder=ACCEPT_ROOT/run_id;spec=read(folder/'specification.json')
    if (folder/'opened.json').exists():
        raise ValueError('Acceptance was already opened; evaluation is single-use')
    models,manifest=load_conditional_model(spec['model_id'])
    if code_hash()!=spec['code_sha256'] or manifest['model_sha256']!=spec['model_sha256']:
        raise ValueError('Code or model changed after acceptance registration')
    event=cancelled or threading.Event()
    callback=progress or (lambda state: None)
    dump(folder/'opened.json',dict(opened_at=utcnow(),specification_sha256=sha(folder/'specification.json')))
    try:
        path,data=_prepare_day(spec['day'],callback,event,venue='bybit')
        callback(dict(stage='evaluation',message='Building held-out causal features; no fitting'))
        frame=_day_samples(spec['day'],source_path=path)
        if frame.empty:
            raise ValueError('No complete conditional-model samples in the held-out day')
        predictions=predict_with_models(models,frame[FEATURES].to_dict('records'))
        baseline=dict(adverse_mid_bps=np.zeros(len(frame)),
            future_execution_cost_bps=frame.current_cost_bps.to_numpy(),
            future_volatility_bps=frame.vol60_bps.to_numpy()*np.sqrt(frame.horizon_seconds.to_numpy()/60))
        metrics={target:dict(n=len(frame),selected=manifest['selected'][target],
                   deployed_mae=float(mean_absolute_error(frame[target],predictions.get(target,baseline[target]))),
                   persistence_mae=float(mean_absolute_error(frame[target],baseline[target]))) for target in TARGETS}
        cases=[]
        for index,case in enumerate(spec['cases']):
            if event.is_set():
                raise InterruptedError('Acceptance cancelled; opened test remains consumed')
            callback(dict(stage='evaluation',completed=index,total=len(spec['cases']),message='Replaying predeclared order cases'))
            try:
                report=run_mpc_replay(spec['day'],model_id=spec['model_id'],**case,**spec['parameters'])
                cases.append(dict(config=case,report_path=report['report_path'],results={k:{field:value for field,value in r.items()
                    if field not in ('decisions','fills')} for k,r in report['results'].items()}))
            except Exception as exc:
                cases.append(dict(config=case,status='failed',error_type=type(exc).__name__,reason=str(exc)))
        functional=all('results' in case and all(r['status']=='complete' and r['reconciliation']['ok']
                         for r in case['results'].values()) for case in cases)
        result=dict(run_id=run_id,created_at=utcnow(),status='passed_functional' if functional else 'incomplete_functional',
            specification=spec,data=data,metrics=metrics,cases=cases,trained=False,
            limitations=['One preregistered day only; not proof of long-term improvement.',
                         'Previously observed dates remain development examples.',
                         'All policies have identical balances, delays, fees, and child-size limits.'])
        if _bytes(ROOT/'data')+5_000_000>DATA_CAP:
            raise ValueError('Report reservation exceeds global data cap')
        dump(folder/'report.json',result)
        log('acceptance_evaluated',run_id=run_id,status=result['status'])
        return result
    except Exception as exc:
        dump(folder/'failure.json',dict(time=utcnow(),error_type=type(exc).__name__,reason=str(exc),test_opened=True))
        raise


def list_acceptance():
    """列出登记、是否打开及结果/失败状态供看板检索；不会重新评价已打开的窗口。"""
    items=[]
    for path in ACCEPT_ROOT.glob('*/specification.json'):
        folder=path.parent
        result=read(folder/'report.json') if (folder/'report.json').exists() else None
        failure=read(folder/'failure.json') if (folder/'failure.json').exists() else None
        items.append(dict(specification=read(path),opened=(folder/'opened.json').exists(),report=result,failure=failure))
    return sorted(items,key=lambda item:item['specification']['registered_at'],reverse=True)


def submit_acceptance(day, model_id):
    """看板先登记再提交串行后台验收，返回id以便页面刷新后轮询，不阻塞页面下载。"""
    spec=register_acceptance(day,model_id)
    event=threading.Event();_CANCEL[spec['run_id']]=event
    dump(ACCEPT_ROOT/spec['run_id']/'job.json',dict(status='queued',message='Registered before data access'))
    _POOL.submit(_acceptance_worker,spec['run_id'],event)
    return spec['run_id']


def _acceptance_worker(run_id, event):
    """后台执行已锁验收，将下载进度、结果、取消或失败写到本次独立job.json。"""
    path=ACCEPT_ROOT/run_id/'job.json'
    def progress(state):
        """把下载/样本/回放阶段进度持久化；只含运行状态，不写RPC凭据或模型输入标签。"""
        dump(path,dict(status='running',updated_at=utcnow(),**state))
    try:
        report=evaluate_acceptance(run_id,progress,event)
        dump(path,dict(status='completed',result_status=report['status'],completed_at=utcnow()))
    except Exception as exc:
        dump(path,dict(status='cancelled' if isinstance(exc,InterruptedError) else 'failed',
                       reason=str(exc),completed_at=utcnow()))
    finally:
        _CANCEL.pop(run_id,None)


def acceptance_job(run_id):
    """校验标识后回读后台状态，供Streamlit定时片段显示；不存在则返回None。"""
    if len(run_id)!=32 or not run_id.isalnum():
        raise ValueError('Invalid acceptance identifier')
    path=ACCEPT_ROOT/run_id/'job.json'
    return read(path) if path.exists() else None


def cancel_acceptance(run_id):
    """对本进程中的验收设置取消事件；已打开的测试不因此恢复为未使用日期。"""
    event=_CANCEL.get(run_id)
    if event is None:
        return False
    event.set()
    return True
