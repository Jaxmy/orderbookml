"""组件用途：用冻结预测和盘口运行早期纸面策略/立即基线，记资金风险与费用；不发送真实订单。。

原始说明：Fixed parent orders: compare immediate execution against frozen ML timing.

No signal chooses direction. Full arrival-price IS includes waiting price movement.
This evaluates execution policy, not an alpha strategy or historical DEX arbitrage."""
import bisect
import joblib
import pandas as pd
import numpy as np
from threadpoolctl import threadpool_limits
from core.execution import mid,sweep
from core.ledger import Ledger,reconcile
from core.io import ROOT,read,dump,sha
from core.model import FEATURES,features
from research import OUT,stamp
from download_history import HOME

def replay():
    """用冻结预测和盘口运行早期纸面策略/立即基线，记资金风险与费用；不发送真实订单。"""
    if not (OUT/'test_metrics.json').exists(): raise ValueError('Complete sealed model test first')
    if (OUT/'paper_metrics.json').exists(): raise ValueError('Paper experiment already evaluated')
    frozen=read(OUT/'frozen.json')
    if frozen['model_sha256']!=sha(OUT/'models.joblib'): raise ValueError('Model changed')
    models=joblib.load(OUT/'models.joblib')
    cfg=read(ROOT/'history.json')
    books=pd.concat([pd.read_parquet(HOME/(day+'.books.parquet')) for day in cfg['dates'][-2:]],ignore_index=True)
    rows=books.to_dict('records'); times=books.available_at.tolist()
    start,end=stamp(cfg['validation_end']),stamp(cfg['test_end'])
    # Fixed clock orders, not selected using availability of future labels. A missing
    # current feature causes a rejection, never a shift to a favorable observation.
    frame=features(books,start,end,include_unlabeled=True)
    schedule=pd.DataFrame({'t':np.arange(start+120,end-60,1800,dtype=float)})
    orders=schedule.merge(frame,on='t',how='left',validate='one_to_one')
    results={}; evidence=[]
    with threadpool_limits(limits=1):
        valid=orders[FEATURES].notna().all(axis=1)
        forecast=np.full(len(orders),np.nan)
        forecast[valid]=models['execution_cost'].predict(orders.loc[valid,FEATURES])
    for policy in ('immediate','frozen_ml'):
        for latency in (0,.25,1):
            ledger=Ledger('CEX',mid(rows[0])); total_is=0.; count=0; rejects=0
            for index,(_,order) in enumerate(orders.iterrows()):
                if not valid.iloc[index]:
                    rejects+=1
                    evidence.append(dict(policy=policy,latency_seconds=latency,decision_t=order.t,
                        execution_t=None,wait_seconds=0,side='buy' if index%2==0 else 'sell',
                        arrival_mid=None,all_in_is_bps=None,status='rejected',reason='missing_causal_features'))
                    continue
                side='buy' if index%2==0 else 'sell'
                # ML target was buy-side execution cost: never apply it to sell-side timing.
                wait=60 if policy=='frozen_ml' and side=='buy' and frozen['tasks']['execution_cost']['selected']!='persistence' and forecast[index]+.5<order.cost_now else 0
                target=order.t+wait+latency
                i=bisect.bisect_left(times,target)
                decision=bisect.bisect_right(times,order.t)-1
                if decision<0 or i>=len(rows) or times[i]-target>3 or order.t-times[decision]>3:
                    rejects+=1; continue
                arrival=float(mid(rows[decision])); quote=sweep(rows[i],side,'.5',cfg['fee_bps'])
                if not quote['complete']: rejects+=1; continue
                event=ledger.apply(f'{policy}-{latency}-{index}',side,'.5',quote['quote'],quote['fee'],0,
                    quote['mid'],times[i],rows[i]['id'])
                cost=((float(quote['vwap'])-arrival)*(1 if side=='buy' else -1)/arrival*10000+cfg['fee_bps'])
                if event['status']=='filled': total_is+=cost; count+=1
                else: rejects+=1
                evidence.append(dict(policy=policy,latency_seconds=latency,decision_t=order.t,execution_t=times[i],
                    wait_seconds=wait,side=side,arrival_mid=arrival,all_in_is_bps=cost,status=event['status'],reason=event['reason']))
            status=ledger.status(mid(rows[-1]))
            audit=reconcile(ledger.initial,ledger.events,ledger.balances)
            results[f'{policy}_{latency}']=dict(fills=count,rejections=rejects,mean_is_bps=total_is/count if count else None,
                ledger=status,audit=audit,assumptions='taker fee 10bps; .5 ETH fixed clock alternating parents matching ML target size; missing features rejected; next observed book after order delay; no queue model')
    pd.DataFrame(evidence).to_parquet(OUT/'paper_orders.parquet',index=False)
    dump(OUT/'paper_metrics.json',results)
    print(results)

if __name__=='__main__': replay()
