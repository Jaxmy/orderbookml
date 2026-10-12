"""组件用途：递归统计指定运行目录文件字节，供数据库/研究空间预算核验。。

原始说明：Read-only delivery inventory; intentionally omits credentials and database URLs."""
import json
import shutil
import urllib.request
import xml.etree.ElementTree as ET
import psutil
from core.io import ROOT,read,dump,utcnow
from core.store import Store

def size(folder):
    """递归统计指定运行目录文件字节，供数据库/研究空间预算核验。

    输入参数：folder（单位和范围由下方校验及调用方契约限定）。"""
    total=0
    for p in folder.rglob('*'):
        try:
            if p.is_file(): total+=p.stat().st_size
        except FileNotFoundError: pass
    return total

if __name__=='__main__':
    store=Store(); home=ROOT/'data'/'historical'
    result=dict(checked_at=utcnow(),historical_bytes=size(home),all_data_bytes=size(ROOT/'data'),
        runtime_bytes=size(ROOT/'.runtime'),python_environment_bytes=size(ROOT/'.venv'),
        D_free_bytes=shutil.disk_usage(ROOT).free,available_ram_bytes=psutil.virtual_memory().available,
        database_backend=store.engine.dialect.name,
        cached_events={k:len(store.latest(k,1000)) for k in ['book','dex','opportunity','prediction']},
        historical_orderbook_events=sum(r['events'] for r in read(home/'normalized_manifest.json')['days']),
        historical_orderbook_views=sum(r['views'] for r in read(home/'normalized_manifest.json')['days']),
        historical_trades=read(home/'trades'/'report.json')['total_trades'],
        dex_states=read(home/'dex'/'report.json')['states'],
        recovery_passed=read(ROOT/'logs'/'postgres_recovery.json')['passed'])
    for key,url in [('api','http://127.0.0.1:8010/health'),('dashboard','http://127.0.0.1:8502/_stcore/health'),('prediction_api','http://127.0.0.1:8010/market/prediction?limit=2')]:
        with urllib.request.urlopen(url,timeout=5) as response:
            value=response.read().decode()
            result[key]=json.loads(value) if key!='dashboard' else value
    suite=ET.parse(ROOT/'logs'/'tests-full.xml').find('testsuite')
    result['tests']={k:suite.attrib[k] for k in ['tests','failures','errors','skipped','time']}
    dump(ROOT/'logs'/'full_final_validation.json',result)
    print({k:v for k,v in result.items() if k!='prediction_api'})
