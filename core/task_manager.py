"""持久化的串行研究任务队列：页面退出不丢失状态，重启不自动重复实验。"""
from __future__ import annotations
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from .io import ROOT, utcnow, code_hash

TASK_ROOT=ROOT/'data'/'experiments'/'tasks'
DATABASE=TASK_ROOT/'tasks.sqlite3'
KINDS={'execution','cross','static','mpc','limit','passive','training','acceptance','review','chain_events','channels'}


@contextmanager
def connect():
    """创建 SQLite 连接与任务表，使用事务和忙等待保护多页面并发读写。"""
    TASK_ROOT.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(DATABASE,timeout=15)
    db.row_factory=sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, kind TEXT NOT NULL, config TEXT NOT NULL, status TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0, stage TEXT, error TEXT, result TEXT, cancel INTEGER NOT NULL DEFAULT 0, parent TEXT, code TEXT NOT NULL)')
    db.commit()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback();raise
    finally:db.close()


def unpack(row):
    """解码保存的配置和结果，并兼容旧看板需要的创建时间及进度字段。"""
    if row is None:return None
    item=dict(row)
    item['config']=json.loads(item['config'])
    item['result']=json.loads(item['result']) if item['result'] else None
    item['created_at']=item['created'];item['message']=item['stage']
    return item


def get_task(identifier):
    """按标识读取任务；SQL 参数绑定防止标识被当作查询语句执行。"""
    with connect() as db:return unpack(db.execute('SELECT * FROM tasks WHERE id=?',(identifier,)).fetchone())


def list_tasks(kind=None,limit=40):
    """按创建时间列出统一实验历史，可按类型过滤，最多返回一百条。"""
    limit=max(1,min(100,int(limit)))
    with connect() as db:
        rows=db.execute('SELECT * FROM tasks '+('WHERE kind=? ' if kind else '')+'ORDER BY created DESC LIMIT ?',((kind,limit) if kind else (limit,))).fetchall()
    return [unpack(row) for row in rows]


def ensure_worker():
    """启动独立后台队列进程；进程内部文件锁保证只有一个工作者，窗口关闭不杀任务。"""
    (ROOT/'logs').mkdir(exist_ok=True)
    with (ROOT/'logs'/'tasks.stdout.log').open('ab') as output,(ROOT/'logs'/'tasks.stderr.log').open('ab') as error:
        subprocess.Popen([sys.executable,str(ROOT/'task_worker.py')],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=output,stderr=error,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)


def submit_task(kind,config,parent=None,start=True):
    """先持久化参数后入队；每次提交创建新标识，旧结果不覆盖，串行执行防止内存并发峰值。"""
    if kind not in KINDS:raise ValueError('Unsupported experiment type')
    payload=json.dumps(config,ensure_ascii=False,allow_nan=False)
    if len(payload.encode())>2_000_000:raise ValueError('Experiment configuration is too large')
    from .experiment_engine import _bytes,DATA_CAP
    if _bytes(ROOT/'data')+len(payload.encode())+6_000_000>DATA_CAP:
        raise ValueError('Task reservation would exceed the 5 GB data budget')
    identifier=uuid.uuid4().hex;now=utcnow()
    with connect() as db:
        if db.execute("SELECT COUNT(*) FROM tasks WHERE status IN ('queued','running')").fetchone()[0]>=20:
            raise ValueError('Too many queued experiments; wait or cancel an existing run')
        db.execute('INSERT INTO tasks (id,kind,config,status,created,updated,parent,code) VALUES (?,?,?,?,?,?,?,?)',
            (identifier,kind,payload,'queued',now,now,parent,code_hash()))
    if start:ensure_worker()
    return identifier


def cancel_task(identifier):
    """持久化取消请求；队列中直接取消，运行中在当前计算步骤结束或数据检查点响应。"""
    with connect() as db:
        cursor=db.execute("UPDATE tasks SET cancel=1,status=CASE WHEN status='queued' THEN 'cancelled' ELSE status END,updated=? WHERE id=? AND status IN ('queued','running')",(utcnow(),identifier))
    return cursor.rowcount>0


def retry_task(identifier,start=True):
    """复制原配置创建新实验并关联原任务；一次性封存测试禁止重试，避免再次打开同一测试集。"""
    task=get_task(identifier)
    if not task:raise ValueError('Experiment not found')
    if task['status'] in ('queued','running'):raise ValueError('This experiment is still active')
    if task['kind']=='acceptance':raise ValueError('A sealed evaluation cannot be retried; use a new unseen date')
    return submit_task(task['kind'],task['config'],identifier,start)


class Cancellation:
    """通过数据库读取取消标记，支持看板和独立后台进程之间协作，不依赖页面内存事件。"""
    def __init__(self,identifier):
        """保留当前任务标识，后续每个检查点读取最新取消状态。"""
        self.identifier=identifier
    def is_set(self):
        """返回是否已请求取消；未知任务按取消处理，避免孤立执行。"""
        task=get_task(self.identifier)
        return task is None or bool(task['cancel'])


def update_progress(identifier,state):
    """保存阶段及有界进度；同时检查取消，令已有下载循环能及时结束。"""
    if Cancellation(identifier).is_set():raise InterruptedError('Experiment cancelled by user')
    value=state.get('progress')
    if value is None and state.get('total'):value=state.get('completed',0)/state['total']
    with connect() as db:
        if value is None:
            db.execute('UPDATE tasks SET stage=?,updated=? WHERE id=?',(state.get('stage','processing'),utcnow(),identifier))
        else:
            db.execute('UPDATE tasks SET stage=?,progress=?,updated=? WHERE id=?',(state.get('stage','processing'),min(.99,max(0.,float(value))),utcnow(),identifier))


def dispatch(task):
    """根据类型调用现有计算组件；未来行情仍由模拟器读取，任务编排不改变策略信息边界。"""
    kind,config,identifier=task['kind'],task['config'],task['id']
    event=Cancellation(identifier)
    def progress(state):
        """把现有组件的阶段回调写入统一任务，并在回调时响应取消。"""
        update_progress(identifier,state)
    if event.is_set():raise InterruptedError('Experiment cancelled by user')
    progress(dict(stage='preparing',progress=.02))
    if kind=='execution':
        from .experiment_engine import run_experiment
        return run_experiment(config,progress,event)
    if kind=='cross':
        from .cross_venue import prepare_cross_venue_data,analyze_cross_venue
        prepare_cross_venue_data(config['day'],progress=progress,cancelled=event)
        return analyze_cross_venue(**config,progress=progress,cancelled=event,run_id=identifier)[1]
    if kind=='static':
        from .optimizer import run_static_snapshot
        return run_static_snapshot(**config)
    if kind=='mpc':
        from .mpc import run_mpc_replay
        return run_mpc_replay(**config,cancelled=event,progress=progress)
    if kind=='limit':
        from .limit_optimizer import run_limit_optimization
        return run_limit_optimization(**config)
    if kind=='passive':
        from .passive import load_bybit_passive_day,simulate_passive_limit
        day=config['day'];args={k:v for k,v in config.items() if k!='day'}
        books,trades=load_bybit_passive_day(day)
        return simulate_passive_limit(books,trades,**args)
    if kind=='training':
        from .conditional_model import train_conditional_model
        return train_conditional_model(cancelled=event,progress=progress)
    if kind=='acceptance':
        from .acceptance import evaluate_acceptance
        return evaluate_acceptance(config['run_id'],progress,event)
    if kind=='chain_events':
        from .chain_history import extract_events
        return extract_events(**config,progress=progress,cancelled=event)
    if kind=='channels':
        from .chain_history import compare_channels
        return compare_channels(**config,progress=progress,cancelled=event)
    if kind=='review':
        from .order_review import review_fills
        return review_fills(**config)
    raise ValueError('Unsupported experiment type')


def execute_task(task):
    """执行已领取任务，分别保存完成、取消或失败；取消后不将生成的中间产物伪装成成功。"""
    identifier=task['id']
    try:
        if task['code']!=code_hash():raise ValueError('Code changed after submission; repeat with the current version')
        result=dispatch(task)
        if Cancellation(identifier).is_set():raise InterruptedError('Experiment cancelled after the current calculation step')
        payload=json.dumps(result,ensure_ascii=False,allow_nan=False,default=str)
        if len(payload.encode())>5_000_000:raise ValueError('Result exceeds the task report size limit')
        with connect() as db:db.execute("UPDATE tasks SET status='completed',progress=1,result=?,updated=?,stage='complete' WHERE id=?",(payload,utcnow(),identifier))
    except Exception as exc:
        status='cancelled' if isinstance(exc,InterruptedError) else 'failed'
        with connect() as db:db.execute('UPDATE tasks SET status=?,error=?,updated=? WHERE id=?',(status,f'{type(exc).__name__}: {exc}',utcnow(),identifier))


@contextmanager
def worker_lock():
    """尝试占有工作者文件锁；进程崩溃时操作系统释放锁，新进程才可接管。"""
    import msvcrt
    TASK_ROOT.mkdir(parents=True,exist_ok=True)
    with (TASK_ROOT/'worker.lock').open('a+b') as handle:
        if handle.seek(0,2)==0:handle.write(b'0');handle.flush()
        handle.seek(0)
        try:msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:
            yield False;return
        try:yield True
        finally:
            handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)


def recover_interrupted():
    """仅持有工作者锁时调用：标记前次崩溃遗留任务，不自动重跑或重复打开封存测试。"""
    with connect() as db:
        db.execute("UPDATE tasks SET status='interrupted',error='Previous worker stopped before the experiment finished',updated=? WHERE status='running'",(utcnow(),))


def claim_next():
    """在单个事务中领取最早的等待任务，防止重复执行同一份实验。"""
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute("SELECT * FROM tasks WHERE status='queued' AND cancel=0 ORDER BY created LIMIT 1").fetchone()
        if not row:return None
        db.execute("UPDATE tasks SET status='running',updated=? WHERE id=?",(utcnow(),row['id']))
        return unpack(row)


def run_worker(idle_seconds=None):
    """独立串行工作者：恢复崩溃状态、执行排队任务；默认常驻，测试可指定空闲退出时间，不依赖页面。"""
    with worker_lock() as acquired:
        if not acquired:return
        recover_interrupted();idle=time.monotonic()
        while idle_seconds is None or time.monotonic()-idle<idle_seconds:
            task=claim_next()
            if task:
                execute_task(task);idle=time.monotonic()
            else:time.sleep(.25)

# 以下适配入口保留旧报告查询能力，使看板升级后仍能查看此前实验。
def submit_execution(config):
    """把单笔订单模拟提交到统一队列，配置单位由计算组件验证。"""
    return submit_task('execution',config)


def get_execution_job(identifier):
    """优先查询统一队列，找不到时读取旧订单任务，不改写旧记录。"""
    from .experiment_engine import get_job
    return get_task(identifier) or get_job(identifier)


def get_execution_result(identifier):
    """读取新任务结果或旧不可变订单报告，兼容原结果展示组件。"""
    task=get_task(identifier)
    if task:return task['result']
    from .experiment_engine import get_result
    return get_result(identifier)


def execution_history(limit=20):
    """合并新旧订单实验，按时间排序供原工作台历史查看。"""
    from .experiment_engine import recent_jobs
    return sorted(list_tasks('execution',limit)+recent_jobs(limit),key=lambda v:v.get('created_at',''),reverse=True)[:limit]


def submit_cross(config):
    """将同窗跨所分析提交至共享串行队列，避免与模型训练同时占用内存。"""
    return submit_task('cross',config)


def cross_job(identifier):
    """读取新跨所任务状态，保留旧任务标识兼容性。"""
    from .cross_venue import get_cross_job
    return get_task(identifier) or get_cross_job(identifier)


def cross_result(identifier):
    """读取新跨所结果或旧报告，不再要求页面知道存储形式。"""
    task=get_task(identifier)
    if task:return task['result']
    from .cross_venue import get_cross_report
    return get_cross_report(identifier)


def cross_history(limit=20):
    """汇总新旧跨所历史实验，报告内容和旧标识保持不变。"""
    from .cross_venue import recent_cross_jobs
    return sorted(list_tasks('cross',limit)+recent_cross_jobs(limit),key=lambda v:v.get('created_at',''),reverse=True)[:limit]


def cancel_any(identifier):
    """统一任务优先使用持久取消；旧任务仍调用其原取消入口。"""
    if get_task(identifier):return cancel_task(identifier)
    from .experiment_engine import cancel
    from .cross_venue import cancel_cross_job
    return cancel(identifier) or cancel_cross_job(identifier)


def submit_sealed(day,model_id):
    """在入队前锁定未观察日期与代码/模型，再由独立进程一次性打开评估。"""
    from .acceptance import register_acceptance
    spec=register_acceptance(day,model_id)
    return submit_task('acceptance',dict(run_id=spec['run_id']))
