"""组件用途：只读检查给定公开行情/RPC服务连通情况，将成功与失败分类供来源选择。。

原始说明：Credential-free, read-only connectivity evidence; run before dependencies exist."""
import concurrent.futures
import json
import urllib.request
from pathlib import Path


def probe(url):
    """只读检查给定公开行情/RPC服务连通情况，将成功与失败分类供来源选择。

    输入参数：url（单位和范围由下方校验及调用方契约限定）。"""
    try:
        data=None if 'binance' in url else json.dumps({'jsonrpc':'2.0','id':1,'method':'eth_chainId','params':[]}).encode()
        request=urllib.request.Request(url,data=data,headers={'Content-Type':'application/json','User-Agent':'execution-replay/1'})
        with urllib.request.urlopen(request,timeout=20) as response:
            payload=json.load(response)
        return {'url':url,'ok':True,'result':payload.get('result') if data else [{'symbol':s['symbol'],'status':s['status']} for s in payload.get('symbols',[])]}
    except Exception as e:
        return {'url':url,'ok':False,'error':type(e).__name__+': '+str(e)}


if __name__=='__main__':
    urls=['https://api.binance.com/api/v3/exchangeInfo?symbol=ETHUSDC','https://ethereum-rpc.publicnode.com']
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        results=list(pool.map(probe,urls))
    root=Path(__file__).resolve().parent/'logs';root.mkdir(exist_ok=True)
    (root/'network_authorized.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    print(json.dumps(results,indent=2))
