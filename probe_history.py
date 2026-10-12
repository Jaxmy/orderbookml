"""组件用途：对Tardis候选档案只读探测状态和小段响应，返回可访问性及错误类型，不下载整日数据。。"""
import concurrent.futures
import requests
from core.io import dump,ROOT

def probe(symbol):
    """对Tardis候选档案只读探测状态和小段响应，返回可访问性及错误类型，不下载整日数据。

    输入参数：symbol（单位和范围由下方校验及调用方契约限定）。"""
    url=f'https://datasets.tardis.dev/v1/binance/book_snapshot_25/2026/09/01/{symbol}.csv.gz'
    try:
        with requests.get(url,headers={'Range':'bytes=0-1023'},stream=True,timeout=30) as r:
            head=next(r.iter_content(1024),b'')
            return dict(symbol=symbol,url=url,status=r.status_code,length=r.headers.get('Content-Length'),
                        content_range=r.headers.get('Content-Range'),gzip_magic=head[:2].hex(),
                        error=head.decode(errors='replace')[:300] if r.status_code>=400 else None)
    except Exception as e:return dict(symbol=symbol,error=type(e).__name__)

if __name__=='__main__':
    with concurrent.futures.ThreadPoolExecutor(2) as pool:r=list(pool.map(probe,['ETHUSDC','ETHUSDT']))
    dump(ROOT/'logs'/'history_probe.json',r)
    print(r)
