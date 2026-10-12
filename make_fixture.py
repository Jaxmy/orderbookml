"""组件用途：生成明确标注的合成软件验收数据和清单，供数学/异常路径测试；不混入真实市场研究结论。。

原始说明：Deterministic SYNTHETIC fixtures for code acceptance, never market evidence."""
import argparse
import json
import math
from pathlib import Path
import numpy as np
import pandas as pd
from core.io import read, manifest


def generate(folder, start=1767225600., seconds=21600, seed=42, external=False):
    """生成明确标注的合成软件验收数据和清单，供数学/异常路径测试；不混入真实市场研究结论。

    输入参数：folder、start、seconds、seed、external（单位和范围由下方校验及调用方契约限定）。"""
    folder=Path(folder)
    if folder.exists():raise ValueError('Fixture directory already exists')
    folder.mkdir(parents=True)
    rng=np.random.default_rng(seed)
    rows=[];quotes=[]
    for i in range(seconds):
        p=3000+18*math.sin(i/700)+4*math.sin(i/37)+(8 if external else 0)
        spread=.15+.4*(1+math.sin(i/150))+(0.3 if external else 0)
        depth=.08+.08*(1+math.sin(i/350))
        bids=[];asks=[]
        for j in range(20):
            bids.append([f'{p-spread/2-j*.12:.2f}',f'{depth+rng.uniform(.01,.12):.6f}'])
            asks.append([f'{p+spread/2+j*.12:.2f}',f'{depth+rng.uniform(.01,.12):.6f}'])
        rows.append(dict(id=f'synthetic-{seed}-{i}',available_at=start+i+.1,update_id=str(i),
                         bids_json=json.dumps(bids),asks_json=json.dumps(asks)))
        if i%60==0 and not external:
            pool_price=p+math.sin(i/250)*1.5
            for size in ['0.05','0.5','2']:
                q=float(size)
                for side in ['buy','sell']:
                    price=pool_price*(1+(.0005+q/9000)*(1 if side=='buy' else -1))
                    quotes.append(dict(id=f'synthetic-dex-{i}-{size}-{side}',available_at=start+i+.6,
                        side=side,quantity=size,quote_usdc=f'{q*price:.6f}',quote_raw=str(int(q*price*1e6)),
                        base_fee_wei='1000000000',block_time=start+i,block_number=i//12,
                        block_hash='SYNTHETIC_NOT_A_CHAIN_HASH',group_id=f'synthetic-group-{i}',
                        sqrt_price_x96=str(int(math.sqrt(1e12/pool_price)*2**96)),
                        sqrt_price_after='0',ticks_crossed=0,quoter_gas_estimate=0,
                        tick=int(math.log(1e12/pool_price,1.0001)),liquidity='100000000000000000',
                        pool='SYNTHETIC_NOT_A_CONTRACT'))
    pd.DataFrame(rows).to_parquet(folder/'cex.parquet',index=False)
    from collect import DEX_COLS
    (pd.DataFrame(quotes) if quotes else pd.DataFrame(columns=DEX_COLS)).to_parquet(folder/'dex.parquet',index=False)
    c=read(Path(__file__).parent/'config.json')
    manifest(folder,'synthetic',start,start+seconds,c,extra={'role':'external' if external else 'main',
              'fixture_seed':seed,'warning':'SYNTHETIC SOFTWARE TEST ONLY; NOT MARKET RESULTS',
              'counts':{'cex':len(rows),'dex':len(quotes)}})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',default='sample_data/demo')
    a=p.parse_args();root=Path(a.output)
    generate(root/'main')
    generate(root/'external',start=1767312000.,seconds=7200,seed=43,external=True)
    print('Created synthetic main and external fixtures:',root)
