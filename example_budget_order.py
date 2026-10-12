"""组件用途：在预定历史时点二分求含费五千USDC可买最大数量，独立重算逐档金额；未来markout只作事后估值。。

原始说明：One illustrative historical budget order; leaves frozen experiments unchanged."""
import json
from decimal import Decimal as D
import pandas as pd
from core.execution import sweep, validate_book, mid
from core.io import ROOT, dump

def main():
    """在预定历史时点二分求含费五千USDC可买最大数量，独立重算逐档金额；未来markout只作事后估值。"""
    books=pd.read_parquet(ROOT/'data/historical/2026-09-03.books.parquet')
    t=pd.Timestamp('2026-09-03T04:00:00Z').timestamp()
    row=books[books.available_at<=t].iloc[-1].to_dict()
    assert 0 <= t-row['available_at'] <= 3
    bids,asks=validate_book(row)
    budget=D('5000'); unit=D('0.00000001')
    # Integer binary search includes the existing engine's rounded quote and fee.
    low,high=0,int(sum(q for _,q in asks)/unit)
    while low<high:
        test=(low+high+1)//2
        q=sweep(row,'buy',str(test*unit),'10')
        if D(q['net_quote'])<=budget: low=test
        else: high=test-1
    quote=sweep(row,'buy',str(low*unit),'10')
    assert quote['complete'] and D(quote['net_quote'])<=budget
    # Independent arithmetic check of all depth fills.
    total=sum(D(s['price'])*D(s['quantity']) for s in quote['steps'])
    assert abs(total-D(quote['quote']))<=D('0.0000005')
    assert sum(D(s['quantity']) for s in quote['steps'])==D(quote['filled'])
    reference=mid(row)
    price_cost=total-D(quote['filled'])*reference
    future=[]
    for seconds in (10,60):
        r=books[books.available_at<=t+seconds].iloc[-1].to_dict()
        age=t+seconds-r['available_at']
        future.append(dict(seconds=seconds,age_seconds=age,
            mid=str(mid(r)) if age<=3 else None,
            marked_value_minus_total_spend=str(D(quote['filled'])*mid(r)-D(quote['net_quote'])) if age<=3 else None))
    result=dict(decision_beijing='2026-09-03 12:00:00',decision_utc='2026-09-03 04:00:00',
        currency='USDC',budget=str(budget),source_id=row['id'],book_age_seconds=t-row['available_at'],
        mode='Decision-time visible-book estimate; zero additional order latency; not guaranteed fill',
        fee_assumption='10 bps in USDC; not verified account fee tier',quantity_precision='1e-8 research assumption, not exchange lot validation',
        quote=quote,remaining_budget=str(budget-D(quote['net_quote'])),
        price_cost_usdc=str(price_cost),all_in_cost_vs_mid_usdc=str(price_cost+D(quote['fee'])),
        best_bid=str(bids[0][0]),best_ask=str(asks[0][0]),spread_usdc=str(asks[0][0]-bids[0][0]),
        bid_depth5_eth=str(sum(q for _,q in bids[:5])),ask_depth5_eth=str(sum(q for _,q in asks[:5])),
        ask_depth20_eth=str(sum(q for _,q in asks)),future_observation=future,
        limitations=['No USDT conversion','No queue, market response or permanent impact model',
                      'Future observations are post-trade marks, not liquidation proceeds or model inputs',
                      'No ML prediction: fixed .5 ETH buy model does not match budget order; date is in training period'])
    out=ROOT/'reports'/'single-order-example';out.mkdir(parents=True,exist_ok=True)
    dump(out/'result.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
