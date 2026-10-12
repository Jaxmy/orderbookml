"""组件用途：只读历史RPC能力探测。"""
from datetime import datetime
from core.network import DexReader
from core.io import ROOT, read, dump
import os
from urllib.parse import urlparse

if __name__ == '__main__':
    d = DexReader(read(ROOT/'config.json'))
    result = {}
    try:
        result['metadata'] = d.verify()
        target = int(datetime.fromisoformat('2026-09-01T00:00:00+00:00').timestamp())
        lo, hi = 1, d.w3.eth.block_number
        while lo<hi:
            mid = (lo+hi+1)//2
            if d.w3.eth.get_block(mid)['timestamp']<=target: lo=mid
            else: hi=mid-1
        block=d.w3.eth.get_block(lo)
        result['historical_block'] = dict(number=lo,timestamp=block['timestamp'],hash=block['hash'].hex())
        result['slot0'] = d.call(d.pool,'slot0()',[],[],['uint160','int24','uint16','uint16','uint16','uint8','bool'],lo)
        result['liquidity'] = d.call(d.pool,'liquidity()',[],[],['uint128'],lo)[0]
        result['status'] = 'archive_state_available'
    except Exception as e:
        result['status']='unavailable'
        result['error']=str(e)[:500]
    provider=urlparse(os.environ.get('ETH_RPC_URL',read(ROOT/'config.json')['rpc_default'])).hostname.replace('.','_')
    dump(ROOT/'logs'/f'archive_rpc_probe_{provider}.json',result)
    print(result)
