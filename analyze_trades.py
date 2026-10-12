"""入口脚本：按日读取已下载的 Bybit 成交，规范化时间和方向，向后对齐盘口，再输出成交量、订单流和事后 markout；不训练模型。"""
import json
import numpy as np
import pandas as pd
from core.io import ROOT,read,dump,sha
from core.flow import aggregate_trades
from download_history import HOME,usage
from research import stamp

if __name__=='__main__':
    folder=HOME/'trades'; manifest=read(folder/'manifest.json'); reports=[]; hours=[]
    for entry in manifest['files']:
        day=entry['day']; path=folder/f'ETHUSDC_{day}.csv.gz'
        if sha(path)!=entry['sha256']: raise ValueError('Trade source hash changed')
        trades=pd.read_csv(path)  # gzip footer/CRC verified on full read
        if trades.id.duplicated().any(): raise ValueError('Duplicate daily trade IDs')
        start=stamp(day+'T00:00:00+00:00')
        trades['available_at']=trades.timestamp/1000+.25
        outside=~trades.available_at.between(start,start+86400,inclusive='left')
        dropped=int(outside.sum()); trades=trades[~outside].copy()
        if not trades.available_at.is_monotonic_increasing: raise ValueError('Unordered tape')
        hours.append(aggregate_trades(trades))
        books=pd.read_parquet(HOME/(day+'.books.parquet'),columns=['available_at','bids_json','asks_json'])
        books['mid']=[(float(json.loads(b)[0][0])+float(json.loads(a)[0][0]))/2 for b,a in zip(books.bids_json,books.asks_json)]
        quotes=books[['available_at','mid']].rename(columns={'available_at':'book_at'})
        aligned=pd.merge_asof(trades,quotes,left_on='available_at',right_on='book_at',direction='backward',tolerance=3,allow_exact_matches=False)
        side=np.where(aligned.side=='buy',1,-1)
        aligned['effective_spread_bps']=2*side*(aligned.price-aligned.mid)/aligned.mid*10000
        # RPI fills are absent from the published order book: do not attribute them to visible liquidity.
        aligned.loc[aligned.rpi!=0,'effective_spread_bps']=np.nan
        for horizon in [10,60]:
            labels=pd.DataFrame({'target_at':aligned.available_at+horizon})
            future=pd.merge_asof(labels,quotes,left_on='target_at',right_on='book_at',direction='backward',tolerance=3)
            aligned[f'markout{horizon}_bps']=side*(future.mid.to_numpy()-aligned.price)/aligned.price*10000
        if usage()+64_000_000>4_000_000_000: raise ValueError('Historical storage budget')
        aligned.to_parquet(folder/(day+'.trades.parquet'),compression='zstd',index=False)
        visible=aligned[aligned.rpi==0]
        reports.append(dict(day=day,trades=len(trades),rpi_trades=int((trades.rpi!=0).sum()),
            volume_eth=float(trades.volume.sum()),notional_usdc=float((trades.volume*trades.price).sum()),
            outside_window=dropped,visible_mid_coverage=float(visible.mid.notna().mean()),
            median_visible_effective_spread_bps=float(visible.effective_spread_bps.median()),
            mean_taker_markout60_bps=float(visible.markout60_bps.mean()),
            markout60_coverage=float(visible.markout60_bps.notna().mean())))
        print(reports[-1],flush=True)
    pd.concat(hours,ignore_index=True).to_parquet(folder/'hourly_flow.parquet',index=False)
    dump(folder/'report.json',dict(days=reports,total_trades=sum(r['trades'] for r in reports),
        total_volume_eth=sum(r['volume_eth'] for r in reports),total_rpi_trades=sum(r['rpi_trades'] for r in reports),
        provenance='Bybit archived spot tape; side interpreted as taker side per official market API schema',
        limitations=['Feed delay is assumed 250ms for both streams; no measured receipt-time ordering',
            'Hourly aggregates available only at bucket end; future markouts are labels, not features',
            'RPI trades counted separately; excluded from visible effective-spread study',
            'Descriptive supplement after model freeze; not added to the frozen ML experiment']))
