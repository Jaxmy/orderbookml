"""组件入口：核验四小时池状态摘要，重建假设LP资产及手续费，逐点对比链上和CEX报价；不是全周逐事件回放。"""
import bisect
from decimal import Decimal as D
import pandas as pd
from core.io import read,dump,sha
from core.defi import Q96,amount0_delta,amount1_delta,accrued_fees,v3_exact_input
from core.arbitrage import opportunity
from download_history import HOME
from history_dex import sqrt_tick

def analyze():
    """核验四小时池状态摘要，重建假设LP资产及手续费，逐点对比链上和CEX报价；不是全周逐事件回放。"""
    folder=HOME/'dex'; manifest=read(folder/'manifest.json')
    for name,digest in manifest['files'].items():
        if sha(folder/name)!=digest: raise ValueError('DEX source changed')
    position=read(folder/'position.json'); L=int(position['liquidity'])
    low,high=sqrt_tick(position['lower']),sqrt_tick(position['upper'])
    states=[read(p) for p in sorted(folder.glob('[0-9]*.json'))]
    if len(states)!=43: raise ValueError('Expected 43 fixed four-hour boundary states')
    first=states[0]; lp=[]; comp=[]; checks=[]; cache={}; fee0,fee1=map(int,first['fee_growth_inside'])
    x0=y0=None
    for row in states:
        s=int(row['sqrt_price_x96']); clamp=min(high,max(low,s)); price=D(10)**12/(D(s)/Q96)**2
        x=D(amount0_delta(clamp,high,L,False))/10**6
        y=D(amount1_delta(low,clamp,L,False))/10**18
        if x0 is None: x0,y0,initial=x,y,x+y*price
        f0=D(accrued_fees(L,fee0,int(row['fee_growth_inside'][0])))/10**6
        f1=D(accrued_fees(L,fee1,int(row['fee_growth_inside'][1])))/10**18
        value=x+y*price; hodl=x0+y0*price; fees=f0+f1*price
        start_price=D(10)**12/(D(first['sqrt_price_x96'])/Q96)**2
        mint_gas=(D(first['base_fee_wei'])+10**9)*200000/D(10)**18*start_price
        exit_gas=(D(row['base_fee_wei'])+10**9)*200000/D(10)**18*price
        lp.append(dict(t=row['available_at'],block=row['block_number'],price=float(price),usdc=float(x),weth=float(y),
            lp_value=float(value),hodl_value=float(hodl),fees_usdc=float(f0),fees_weth=float(f1),fees_marked_usdc=float(fees),
            hypothetical_mint_exit_gas=float(mint_gas+exit_gas),pnl=float(value-initial+fees-mint_gas-exit_gas),
            excess_vs_hodl=float(value-hodl+fees-mint_gas-exit_gas),
            in_range=position['lower']<=row['tick']<position['upper'],
            hypothetical_active_liquidity_share=float(D(L)/(int(row['liquidity'])+L)) if position['lower']<=row['tick']<position['upper'] else 0))
        sell=next(q for q in row['quotes'] if q['side']=='sell'); buy=next(q for q in row['quotes'] if q['side']=='buy')
        if sell['ticks_crossed']==0:
            local=v3_exact_input(s,int(row['liquidity']),5*10**17,False,[(s*2,0)],500)
            quote_raw=int(D(sell['quote_usdc'])*10**6)
            checks.append(dict(block=row['block_number'],quote_raw=quote_raw,local_raw=local['amount_out'],
                raw_error=local['amount_out']-quote_raw,complete=local['complete']))
        day=pd.to_datetime(row['available_at'],unit='s',utc=True).strftime('%Y-%m-%d')
        path=HOME/(day+'.books.parquet')
        if not path.exists():
            comp.append(dict(t=row['available_at'],status='rejected',reason='outside_cex_window')); continue
        if day not in cache:
            cache.clear(); b=pd.read_parquet(path); cache[day]=(b.available_at.tolist(),b.to_dict('records'))
        times,books=cache[day]; i=bisect.bisect_right(times,row['available_at'])-1
        if i<0:
            comp.append(dict(t=row['available_at'],status='rejected',reason='no_previous_cex')); continue
        gas=(D(row['base_fee_wei'])+10**9)*200000/D(10)**18*price
        result=opportunity(books[i],sell,buy,'.5',row['available_at'],gas_usdc=str(gas))
        item=dict(t=row['available_at'],status=result['status'],reason=result.get('reason'),block=row['block_number'])
        if result['status']=='quoted': item.update({k:float(v) for k,v in result['net_usdc'].items()})
        comp.append(item)
    pd.DataFrame(lp).to_parquet(folder/'lp_path.parquet',index=False)
    pd.DataFrame(comp).to_parquet(folder/'opportunities.parquet',index=False)
    dump(folder/'quote_math_checks.json',checks)
    if any(abs(c['raw_error'])>1 for c in checks): raise ValueError('Real Quoter/non-crossing math mismatch')
    quoted=[r for r in comp if r['status']=='quoted']
    report=dict(states=len(states),valid_cross_venue_points=len(quoted),rejected_points=len(comp)-len(quoted),
        positive_snapshot_routes=sum(r[k]>0 for r in quoted for k in ['buy_cex_sell_dex','buy_dex_sell_cex']),
        noncrossing_quote_checks=len(checks),max_raw_quote_error=max((abs(c['raw_error']) for c in checks),default=None),
        lp_final=lp[-1],max_virtual_liquidity_share=max(r['hypothetical_active_liquidity_share'] for r in lp),
        limitations=['Four-hour snapshot opportunities are not realized arbitrage PnL',
            'Fee growth from real initialized boundaries; counterfactual small LP ignores own impact on pool liquidity',
            'Position math uses high-precision mathematical tick ratios, not Solidity bit-exact TickMath',
            'One-block confirmation plus 250ms is an assumption, not measured historical receipt time'])
    dump(folder/'report.json',report)
    print(report)

if __name__=='__main__': analyze()
