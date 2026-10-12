"""组件用途：只读检查公开档案存在性、响应长度和格式，避免把不可访问文件当可用数据。。"""
import concurrent.futures
import requests
from web3 import Web3
from core.io import ROOT,dump

def probe(url):
    """只读检查公开档案存在性、响应长度和格式，避免把不可访问文件当可用数据。

    输入参数：url（单位和范围由下方校验及调用方契约限定）。"""
    result={'provider':url,'block':25878704}
    try:
        r=requests.post(url,json={'jsonrpc':'2.0','id':1,'method':'eth_chainId','params':[]},timeout=20)
        r.raise_for_status()
        result['chain']=r.json()
        if r.json().get('result')!='0x1': raise ValueError('Wrong network')
        r=requests.post(url,json={'jsonrpc':'2.0','id':2,'method':'eth_call',
            'params':[{'to':'0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640','data':'0x'+Web3.keccak(text='slot0()')[:4].hex()},hex(25878704)]},timeout=20)
        result['http_status']=r.status_code
        r.raise_for_status(); result['response']=r.json()
    except Exception as e: result['error']=str(e)[:300]
    return result

if __name__=='__main__':
    with concurrent.futures.ThreadPoolExecutor(2) as p:
        result=list(p.map(probe,['https://public.1rpc.io/eth','https://eth.drpc.org/']))
    dump(ROOT/'logs'/'additional_archive_probes.json',result)
    print(result)
