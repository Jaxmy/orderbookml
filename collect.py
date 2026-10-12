"""组件用途：并行检查公开REST、WebSocket及RPC，把结果和错误类型写日志；拒绝凭据URL回显。；校验新窗口和项目内输出路径，预留全局容量，采集只读数据并最终保存Parquet/清单；不覆盖冻结产物。。"""
import argparse
import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
import pandas as pd
from websockets.asyncio.client import connect
from core.io import ROOT, read, dump, manifest, log, sha, code_hash
from core.network import rest_check, ws_check, DexReader, book_row

CEX_COLS=['id','available_at','update_id','bids_json','asks_json']
DEX_COLS=['id','available_at','side','quantity','quote_usdc','base_fee_wei','block_time','block_number','block_hash','group_id','sqrt_price_x96','tick','liquidity']


async def preflight(c):
    """并行检查公开REST、WebSocket及RPC，把结果和错误类型写日志；拒绝凭据URL回显。

    输入参数：c（单位和范围由下方校验及调用方契约限定）。"""
    result={}
    async def check(name, task):
        """等待单个连通性任务，将成功结果或不含凭据的错误分类放入预检字典。

        输入参数：name、task（单位和范围由下方校验及调用方契约限定）。"""
        try:
            result[name]={'ok':True,'result':await task}
        except Exception as e:
            # Avoid recording RPC credential-bearing URL exception strings.
            result[name]={'ok':False,'error_type':type(e).__name__,'message':'Request failed; inspect connectivity/service access, no secrets logged.'}
    d=DexReader(c)
    def dex():
        """在后台线程核验链上元数据并读取一组同区块报价。"""
        return {'metadata':d.verify(),'quotes':d.sample()}
    await asyncio.gather(check('rest',asyncio.to_thread(rest_check,c)), check('websocket',ws_check(c)), check('rpc',asyncio.to_thread(dex)))
    result['ok']=all(result[n]['ok'] for n in ['rest','websocket','rpc'])
    dump(ROOT/'logs'/'preflight.json',result)
    log('preflight',ok=result['ok'],checks={n:result[n]['ok'] for n in ['rest','websocket','rpc']})
    return result


async def capture(c, output, start, end, role='main', kind='live', model_info=None):
    """校验新窗口和项目内输出路径，预留全局容量，采集只读数据并最终保存Parquet/清单；不覆盖冻结产物。

    输入参数：c、output、start、end、role、kind、model_info（单位和范围由下方校验及调用方契约限定）。"""
    output=Path(output).resolve()
    if not output.is_relative_to((ROOT/'data').resolve()):
        raise ValueError('Live capture output must stay under project data/ for the global storage cap')
    source_version=code_hash()
    if output.exists():
        raise ValueError('Output exists: use a new path; never overwrite frozen data')
    if start > time.time()+60:
        raise ValueError('Window is in the future. Run near its start; no automation was scheduled.')
    if end <= time.time() or (kind=='live' and time.time() > start+3):
        raise ValueError('Window already started/expired; lock a new window before collection, do not truncate it')
    output.mkdir(parents=True)
    books,quotes,errors=[],[],[]
    stop=asyncio.Event()
    # Reserve half the remaining cap for Parquet plus manifests and errors.
    root=ROOT/'data'
    already=sum(p.stat().st_size for p in root.rglob('*') if p.is_file()) if root.exists() else 0
    remaining=(c['data_cap_bytes']-already)//2-2**20
    used=0
    raw=(output/'raw.jsonl').open('w',encoding='utf-8')
    def save(typ,row):
        """向raw.jsonl追加单条观测，累计字节超预留时设置停止事件，避免无界写入。

        输入参数：typ、row（单位和范围由下方校验及调用方契约限定）。"""
        nonlocal used
        line=json.dumps({'type':typ,'row':row},ensure_ascii=False)+'\n'
        used+=len(line.encode())
        if used > remaining:
            stop.set()
            raise ValueError('Storage budget reached; stopping')
        raw.write(line);raw.flush()
    def fail(component,e):
        """将组件和异常类型记录到最多一千条错误列表，避免泄露凭据和无限增长。

        输入参数：component、e（单位和范围由下方校验及调用方契约限定）。"""
        if len(errors)<1000:
            errors.append(dict(at=time.time(),component=component,error_type=type(e).__name__))
    while time.time()<start:
        await asyncio.sleep(min(1,start-time.time()))
    async def cex():
        """在窗口内读取公开盘口，每秒保留一条有效接收记录；断开重连并遵守停止事件。"""
        last_bucket=-1
        while time.time()<end and not stop.is_set():
            try:
                async with connect(c['ws_url'],open_timeout=15,ping_interval=20,max_size=2**20) as ws:
                    while time.time()<end and not stop.is_set():
                        payload=await asyncio.wait_for(ws.recv(),timeout=max(.1,min(10,end-time.time())))
                        now=time.time()
                        if now>=end:break
                        bucket=int(now-start)
                        if bucket==last_bucket:continue
                        row=book_row(json.loads(payload),now)
                        save('cex',row);books.append(row);last_bucket=bucket
            except Exception as e:
                fail('cex',e)
                await asyncio.sleep(min(2,max(0,end-time.time())))
    async def dex():
        """按一分钟时隙读取同区块报价，过窗口或容量停止则退出。"""
        reader=DexReader(c)
        for slot in range(int((end-start+59)//60)):
            delay=start+slot*60-time.time()
            if delay>0:await asyncio.sleep(delay)
            if time.time()>=end or stop.is_set():break
            try:
                sample=await asyncio.to_thread(reader.sample)
                if sample[0]['available_at']>=end:break
                for row in sample:
                    save('dex',row);quotes.append(row)
            except Exception as e:fail('dex',e)
    try:
        await asyncio.gather(cex(),dex() if role!='external' else asyncio.sleep(0))
    finally:
        raw.close()
        pd.DataFrame(books,columns=CEX_COLS).to_parquet(output/'cex.parquet',index=False)
        pd.DataFrame(quotes) .to_parquet(output/'dex.parquet',index=False) if quotes else pd.DataFrame(columns=DEX_COLS).to_parquet(output/'dex.parquet',index=False)
        extra={'role':role,'counts':{'cex':len(books),'dex':len(quotes)},'completed_at':time.time(), 'budget_stopped':stop.is_set(), 'code_sha256':source_version}
        if model_info:extra['model_sha256']=model_info['model_sha256']
        manifest(output,kind,start,end,c,errors,extra)
        log('capture_finished',output=str(output),**extra)
    return extra


def main():
    """解析采集/预检/烟测命令参数，核验外部冻结窗口，调用异步流程并返回状态码。"""
    p=argparse.ArgumentParser(description='Read-only, bounded market capture')
    p.add_argument('--config',default='config.json');p.add_argument('--preflight',action='store_true')
    p.add_argument('--output',default='data/main');p.add_argument('--smoke-seconds',type=int)
    p.add_argument('--external-model',help='Frozen model_manifest.json: locks external window')
    a=p.parse_args();c=read(a.config)
    if a.preflight:
        r=asyncio.run(preflight(c));print(json.dumps(r,indent=2));return 0 if r['ok'] else 2
    mi=None;role='main';kind='live'
    start=datetime.fromisoformat(c['start']).timestamp();end=start+c['duration_seconds']
    if a.external_model:
        mi=read(a.external_model)
        if mi['kind']!='live':raise ValueError('Synthetic model cannot authorize live external evaluation')
        if sha(Path(a.external_model).parent/'models.joblib')!=mi['model_sha256']:raise ValueError('Model integrity failure')
        start,end,role=mi['external_start'],mi['external_end'],'external'
    if a.smoke_seconds:
        if a.external_model or not 1<=a.smoke_seconds<=120:raise ValueError('Smoke must be 1–120 seconds, not external')
        start=time.time()+1;end=start+a.smoke_seconds;kind='smoke';role='preflight'
    print(asyncio.run(capture(c,a.output,start,end,role,kind,mi)))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
