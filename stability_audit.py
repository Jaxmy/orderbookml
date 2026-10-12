"""有界只读影子验收：记录资源、行情新鲜度，主动断开自己的连接并重启自己创建的工作者。"""
import argparse
import json
import os
import subprocess
import sys
import time
import uuid
import psutil
from sqlalchemy import text
from core.io import ROOT,dump,utcnow,code_hash
from core.store import Store
from core.experiment_engine import _bytes,DATA_CAP


def launch_feed(seconds,folder,disconnect_after=None):
    """创建本次审计专属只读采集进程，保留 Popen 身份；不接管或停止其他用户进程。"""
    arguments=[sys.executable,str(ROOT/'worker.py'),'--seconds',str(seconds)]
    if disconnect_after:arguments+=['--disconnect-after',str(disconnect_after)]
    with (folder/'feed.stdout.log').open('ab') as out,(folder/'feed.stderr.log').open('ab') as err:
        return subprocess.Popen(arguments,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)


def snapshot(store,process,elapsed):
    """记录本进程及其专属采集进程的内存、研究数据与数据库/WAL占用；心跳只保存业务状态，不记录凭据。"""
    memory=psutil.Process().memory_info().rss
    child_rss=psutil.Process(process.pid).memory_info().rss if process.poll() is None else 0
    with store.engine.connect() as connection:
        if store.engine.dialect.name=='postgresql':
            database_bytes=connection.scalar(text('SELECT pg_database_size(current_database())'))
            # 应用角色没有 pg_ls_waldir 权限：只读统计本机已知数据库目录，不提升数据库账户权限。
            wal_bytes=_bytes(ROOT/'data'/'postgres-native'/'pg_wal')
        else:database_bytes=0;wal_bytes=0
        event_count=connection.scalar(text('SELECT count(*) FROM market_events'))
    now=time.time();health=store.health()
    states={name:dict(status=health.get(name,{}).get('status','missing'),age_seconds=now-health.get(name,{}).get('received_at',0)) for name in ('cex','dex','ml','worker','audit_disconnect')}
    return dict(at=utcnow(),elapsed_seconds=elapsed,monitor_rss_bytes=memory,feed_rss_bytes=child_rss,
        available_ram_bytes=psutil.virtual_memory().available,disk_free_bytes=psutil.disk_usage(str(ROOT)).free,
        research_data_bytes=_bytes(ROOT/'data'),database_bytes=int(database_bytes),wal_bytes=int(wal_bytes),event_count=int(event_count),states=states,feed_running=process.poll() is None)


def run_audit(seconds=3600,interval=15):
    """运行一次不可覆盖的影子验收；断连后等待重连，并在中段终止自己创建的工作者再重启，最终按证据判断通过。"""
    if not 60<=seconds<=7200 or not 5<=interval<=60:raise ValueError('Use 60–7200 audit seconds and 5–60 second samples')
    folder=ROOT/'logs'/'stability'/uuid.uuid4().hex;folder.mkdir(parents=True)
    started=time.monotonic();store=Store();rows=[];restart_at=min(180,seconds//2);disconnect_at=min(45,seconds//4)
    existing=store.health().get('worker',{})
    if existing.get('status')=='running' and psutil.pid_exists(existing.get('pid',-1)):
        raise ValueError('Another market collector is running; wait for it to finish before auditing')
    store.heartbeat('audit_disconnect',dict(status='not_injected',received_at=time.time()))
    process=launch_feed(seconds+60,folder,disconnect_at);restarted=False;observed_disconnect=False;reconnected=False;restart_recovered=False
    dump(folder/'report.json',dict(status='running',started_at=utcnow(),duration_seconds=seconds,code_sha256=code_hash(),folder=str(folder)))
    try:
        while time.monotonic()-started<seconds:
            elapsed=time.monotonic()-started
            if elapsed>=restart_at and not restarted:
                if process.poll() is None:process.terminate();process.wait(timeout=30)
                process=launch_feed(int(seconds-elapsed)+60,folder);restarted=True
            row=snapshot(store,process,elapsed);rows.append(row)
            with (folder/'resources.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(row,ensure_ascii=False)+'\n')
            if row['research_data_bytes']>DATA_CAP or row['available_ram_bytes']<256_000_000 or row['event_count']>30000:
                raise ValueError('Resource guard exceeded during shadow audit')
            state=row['states'];observed_disconnect=observed_disconnect or (state['audit_disconnect']['status']=='injected' and state['audit_disconnect']['age_seconds']<=seconds)
            if observed_disconnect and state['cex']['status']=='connected' and state['cex']['age_seconds']<=5:reconnected=True
            if restarted and elapsed>=restart_at+interval and state['worker']['status']=='running' and state['cex']['status']=='connected' and state['cex']['age_seconds']<=5:restart_recovered=True
            time.sleep(min(interval,max(0,seconds-(time.monotonic()-started))))
        good=sum(row['states']['cex']['status']=='connected' and row['states']['cex']['age_seconds']<=5 for row in rows)
        dex_good=sum(row['states']['dex']['status']=='connected' and row['states']['dex']['age_seconds']<=60 for row in rows)
        passed=seconds>=3600 and observed_disconnect and reconnected and restart_recovered and good>=.9*len(rows) and dex_good>=.9*len(rows)
        report=dict(status='passed' if passed else 'not_passed',completed_at=utcnow(),duration_seconds=time.monotonic()-started,
            samples=len(rows),cex_fresh_samples=good,dex_fresh_samples=dex_good,disconnect_observed=observed_disconnect,
            reconnect_observed=reconnected,restart_recovery_observed=restart_recovered,
            peak_feed_rss_bytes=max(row['feed_rss_bytes'] for row in rows),peak_database_bytes=max(row['database_bytes'] for row in rows),
            peak_wal_bytes=max(row['wal_bytes'] for row in rows),minimum_disk_free_bytes=min(row['disk_free_bytes'] for row in rows),
            scope='Single Bybit public feed and Uniswap quotes; controlled socket disconnect, not a host-wide network outage; no account execution',code_sha256=code_hash())
    except Exception as exc:report=dict(status='failed',error=f'{type(exc).__name__}: {exc}',completed_at=utcnow())
    finally:
        if process.poll() is None:process.terminate();process.wait(timeout=30)
        store.heartbeat('worker',dict(status='stopped',received_at=time.time()))
    dump(folder/'report.json',report)
    print(str(folder/'report.json'))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--seconds',type=int,default=3600);parser.add_argument('--interval',type=int,default=15)
    args=parser.parse_args();run_audit(args.seconds,args.interval)
