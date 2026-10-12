"""组件用途：有界公开成交日档下载。

原始说明：Fixed-window public spot trade tape; included in the historical storage budget."""
import gzip
import requests
from core.io import ROOT,read,dump,sha,utcnow
from download_history import HOME,usage

if __name__=='__main__':
    cfg=read(ROOT/'history.json'); folder=HOME/'trades'; folder.mkdir(exist_ok=True)
    sources=[]
    for day in cfg['dates']:
        name=f'ETHUSDC_{day}.csv.gz'; path=folder/name
        url='https://public.bybit.com/spot/ETHUSDC/'+name
        if not path.exists():
            with requests.get(url,stream=True,timeout=(15,60)) as r:
                r.raise_for_status(); length=int(r.headers.get('Content-Length',0))
                if not 0<length<100_000_000 or usage()+length>4_000_000_000: raise ValueError('Trade download budget')
                tmp=path.with_suffix('.part'); n=0
                with tmp.open('xb') as f:
                    for block in r.iter_content(1024*1024):
                        n+=len(block)
                        if n>length: raise ValueError('Response larger than reserved size')
                        f.write(block)
                if n!=length: raise ValueError('Truncated trade file')
                tmp.rename(path)
        with gzip.open(path,'rt',encoding='utf-8') as f:
            header=f.readline().strip(); first=f.readline().strip()
        sources.append(dict(day=day,url=url,bytes=path.stat().st_size,sha256=sha(path)))
        print(day,path.stat().st_size,header,first[:150],flush=True)
    dump(folder/'manifest.json',dict(created_at=utcnow(),kind='historical_spot_trades',symbol='ETHUSDC',files=sources))
