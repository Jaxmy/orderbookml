"""组件用途：把数据库异常转为HTTP503及本机恢复提示，不回显连接凭据。；读取心跳，按CEX/DEX允许年龄判断陈旧，并结合worker状态输出market_ready；API存活不等于可交易。。"""
import time
from fastapi import FastAPI,Query,HTTPException,Body
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from core.io import ROOT,read
from core.store import Store

app=FastAPI(title='Market Execution Research',version='2.0')

@app.exception_handler(SQLAlchemyError)
async def database_unavailable(request,exc):
    """把数据库异常转为HTTP503及本机恢复提示，不回显连接凭据。

    输入参数：request、exc（单位和范围由下方校验及调用方契约限定）。"""
    return JSONResponse(status_code=503,content={'status':'database_unavailable','action':'Run native_database.py ensure; inspect local logs'})

@app.get('/health')
def health():
    """读取心跳，按CEX/DEX允许年龄判断陈旧，并结合worker状态输出market_ready；API存活不等于可交易。"""
    states=Store().health()
    now=time.time()
    stale={k:not 0<=now-states.get(k,{}).get('received_at',0)<=age for k,age in [('cex',3),('dex',30)]}
    running=states.get('worker',{}).get('status')=='running'
    return {'api':'ok','database':'connected','execution_mode':'paper','workers':states,'now':now,
        'stale':stale,'worker_running':running,'market_ready':running and not any(stale.values())}

@app.get('/market/{kind}')
def market(kind:str,limit:int=Query(100,ge=1,le=1000)):
    """只接受已知流名称，返回有界最新观测，未知kind以404拒绝。

    输入参数：kind、limit（单位和范围由下方校验及调用方契约限定）。"""
    if kind not in ('book','dex','opportunity','prediction'): raise HTTPException(404,'Unknown stream')
    return Store().latest(kind,limit)

@app.get('/research')
def research():
    """读取已保存冻结研究和测试指标，文件尚未生成则明确pending。"""
    folder=ROOT/'data'/'historical'/'research'
    return {name:read(folder/name) if (folder/name).exists() else {'status':'pending'}
        for name in ('frozen.json','test_metrics.json')}

@app.get('/quality')
def quality():
    """读取历史规范化质量清单，缺清单返回pending。"""
    p=ROOT/'data'/'historical'/'normalized_manifest.json'
    return read(p) if p.exists() else {'status':'pending'}


@app.get('/experiments')
def experiments(limit:int=Query(40,ge=1,le=100)):
    """本机内部接口列出统一队列历史；结果与状态从持久数据库读取，不重复执行计算。"""
    from core.task_manager import list_tasks
    return list_tasks(limit=limit)


@app.get('/experiments/{identifier}')
def experiment(identifier:str):
    """读取指定实验配置、进度及报告；不存在时返回404，保留历史失败原因。"""
    from core.task_manager import get_task
    result=get_task(identifier)
    if result is None:raise HTTPException(404,'Experiment not found')
    return result


@app.post('/experiments')
def create_experiment(payload:dict=Body(...)):
    """只创建本机研究任务，不创建交易所真实订单；一次性验收必须走预登记入口。"""
    from core.task_manager import submit_task
    if payload.get('kind')=='acceptance':raise HTTPException(400,'Use the sealed evaluation registration workflow')
    if not isinstance(payload.get('config'),dict):raise HTTPException(400,'Experiment configuration must be an object')
    try:return dict(id=submit_task(payload.get('kind'),payload['config']))
    except ValueError as error:raise HTTPException(400,str(error)) from None


@app.post('/experiments/{identifier}/cancel')
def cancel_experiment(identifier:str):
    """向持久队列提交协作取消；后台组件到检查点停止，不伪装立即中断。"""
    from core.task_manager import cancel_task
    return dict(cancel_requested=cancel_task(identifier))
