"""组件用途：把链上报价向后匹配新鲜CEX簿，对比含费成本并生成费率/gas敏感性；markout只供事后观察不参与选择。；按预设历史意图在隔离CEX/DEX账本模拟成交，扫描期间止损并保留拒单；独立对账后生成逐分钟因果权益轨迹。。"""
import json
from pathlib import Path
from decimal import Decimal
import numpy as np
import pandas as pd
from .execution import sweep, mid, dex_cost
from .quality import asof_index
from .ledger import Ledger, reconcile
from .lp import scenario, inventory
from .io import dump
from .risk import reduction_proposal


def comparisons(books, dex, config):
    """把链上报价向后匹配新鲜CEX簿，对比含费成本并生成费率/gas敏感性；markout只供事后观察不参与选择。

    输入参数：books、dex、config（单位和范围由下方校验及调用方契约限定）。"""
    rows=[];invalid=[];sensitivity=[]
    times=books.available_at.to_numpy()
    for d in dex.to_dict('records'):
        i=asof_index(times,d['available_at'],config['max_cex_age'])
        if i is None or not 0<=d['available_at']-d['block_time']<=config['max_block_age']:
            invalid.append(dict(id=d['id'],reason='stale_or_missing',available_at=d['available_at']));continue
        b=books.iloc[i].to_dict()
        c=sweep(b,d['side'],d['quantity'],config['cex_fee_bps'])
        if not c['complete']:
            invalid.append(dict(id=d['id'],reason='insufficient_depth',available_at=d['available_at']));continue
        dc=dex_cost(d,c['mid'],config['gas_units'],config['priority_fee_gwei'])
        buy=d['side']=='buy'
        best='CEX' if (Decimal(c['net_quote'])<Decimal(dc['net_quote']))==buy else 'DEX'
        raw_best='CEX' if (Decimal(c['quote'])<Decimal(dc['quote']))==buy else 'DEX'
        r=dict(available_at=d['available_at'],cex_id=b['id'],dex_id=d['id'],group_id=d['group_id'],
               quantity=float(d['quantity']),side=d['side'],mid=float(c['mid']),
               cex_quote=float(c['quote']),dex_quote=float(dc['quote']),cex_fee=float(c['fee']),
               gas_usdc=float(dc['gas_usdc']),gas_eth=dc['gas_eth'],cex_net=float(c['net_quote']),dex_net=float(dc['net_quote']),
               best=best,before_extra_fees_best=raw_best,ticks_crossed=int(d.get('ticks_crossed',0)),
               block_number=d['block_number'],block_hash=d['block_hash'],
               cex_cost_bps=(float(c['net_quote'])/float(d['quantity'])/float(c['mid'])-1)*(1 if buy else -1)*10000,
               dex_cost_bps=(float(dc['net_quote'])/float(d['quantity'])/float(c['mid'])-1)*(1 if buy else -1)*10000)
        for h in (10,60):
            j=asof_index(times,d['available_at']+h,3)
            r[f'cex_markout_{h}s_bps']=(float(mid(books.iloc[j]))/float(c['vwap'])-1)*(1 if buy else -1)*10000 if j is not None and d['available_at']+h<=times[-1] else None
        rows.append(r)
        for fee in (0,5,10,20):
            for gas in (150000,200000,300000):
                cc=sweep(b,d['side'],d['quantity'],str(fee));dd=dex_cost(d,c['mid'],gas,config['priority_fee_gwei'])
                sensitivity.append(dict(dex_id=d['id'],side=d['side'],quantity=float(d['quantity']),fee_bps=fee,gas_units=gas,
                                        cex_net=float(cc['net_quote']),dex_net=float(dd['net_quote'])))
    return pd.DataFrame(rows),invalid,pd.DataFrame(sensitivity)


def replay(books,dex,m):
    """按预设历史意图在隔离CEX/DEX账本模拟成交，扫描期间止损并保留拒单；独立对账后生成逐分钟因果权益轨迹。

    输入参数：books、dex、m（单位和范围由下方校验及调用方契约限定）。"""
    c=m['config'];times=books.available_at.to_numpy();start=m['start']
    p0=mid(books.iloc[0]);accounts={v:Ledger(v,p0) for v in ['CEX','DEX']}
    checked={v:start for v in accounts}
    risk_events=[]
    for n in range(12):
        intent=start+900+n*1800;side='buy' if n%2==0 else 'sell'
        if intent>=m['end']:break
        for venue,account in accounts.items():
            t=intent;reason=None;quote=fee=gas='0';snap='missing'
            if venue=='DEX':
                matches=dex[(dex.side==side)&(dex.quantity.astype(str)=='0.05')&(dex.available_at>=intent)&(dex.available_at<=intent+90)]
                if len(matches):
                    d=matches.sort_values('available_at').iloc[0].to_dict();t=float(d['available_at']);snap=d['id']
                    if t-d['block_time']>c['max_block_age']:reason='stale_dex'
                else:reason='dex_timeout'
            i=asof_index(times,t,c['max_cex_age'])
            if i is None:reason=reason or 'stale_cex';ref=p0
            else:ref=mid(books.iloc[i])
            if not reason:
                if venue=='CEX':
                    q=sweep(books.iloc[i],side,'.05',c['cex_fee_bps']);quote,fee=q['quote'],q['fee'];snap=books.iloc[i]['id']
                    if not q['complete']:reason='insufficient_depth'
                else:
                    q=dex_cost(d,ref,c['gas_units'],c['priority_fee_gwei']);quote,gas=q['quote'],q['gas_eth']
            # Scan intervening minute marks before the next order, so a recovered
            # price does not erase a previously triggered loss pause.
            for rt in np.arange(checked[venue],t,60):
                ri=asof_index(times,rt,c['max_cex_age'])
                if ri is None:continue
                rp=mid(books.iloc[ri])
                if account.equity(rp)<=account.initial_equity*Decimal('.98') and not account.paused:
                    account.paused=True
                    risk_events.append(dict(venue=venue,t=float(rt),rule='loss_limit',action='pause subsequent orders'))
            checked[venue]=t
            e=account.apply(f'{venue}-{n:02}',side,'.05',quote,fee,gas,ref,t,snap,reason)
            e['intent_at']=intent;e['valuation_stale']=i is None
            proposal=reduction_proposal(venue,account.balances,books.iloc[i].to_dict() if i is not None else None,t,c['cex_fee_bps'])
            if proposal['status']!='within_limit':
                risk_events.append(dict(t=t,rule='inventory_limit',**proposal))
    audits={v:reconcile(a.initial,a.events,a.balances) for v,a in accounts.items()}
    events=[e for a in accounts.values() for e in a.events]
    # Mark all portfolio states each minute; never look ahead to future events.
    equity=[]
    for venue,a in accounts.items():
        for t in np.arange(start,m['end'],60):
            i=asof_index(times,t,c['max_cex_age'])
            if i is None:
                equity.append(dict(venue=venue,t=t,equity=None,pnl=None,stale=True));continue
            past=[e for e in a.events if e['timestamp']<=t]
            balances=past[-1]['balances'] if past else {k:str(v) for k,v in a.initial.items()}
            p=mid(books.iloc[i]);val=Decimal(balances['USDC'])+sum(Decimal(v)*p for k,v in balances.items() if k!='USDC')
            equity.append(dict(venue=venue,t=t,equity=float(val),pnl=float(val-a.initial_equity),stale=False))
    return accounts,events,audits,pd.DataFrame(equity),risk_events


def decisions(comps, events, out, kind):
    """从场所规模、费用排序、拒单风险提取可核查决策说明；真实案例不足时明确标合成压力，不冒充市场收益。

    输入参数：comps、events、out、kind（单位和范围由下方校验及调用方契约限定）。"""
    prefix='SYNTHETIC SOFTWARE DEMO' if kind=='synthetic' else 'READ-ONLY MARKET RESEARCH'
    records=[]
    if len(comps):
        ordered=comps.sort_values(['available_at','side','quantity'])
        candidates=[]
        for (_,side),g in ordered.groupby(['group_id','side'],sort=False):
            small=g[g.quantity==.05];large=g[g.quantity==2]
            if len(small) and len(large):
                candidates.append((small.iloc[0]['best']!=large.iloc[0]['best'],g))
        if candidates:
            changed,g=next((x for x in candidates if x[0]),candidates[0])
            records.append(dict(case='规模与场所',event_present=bool(changed),evidence=g.to_dict('records'),
                                 decision='按完整成本排序；另核验指定场所现金与库存。0.05/0.5/2 ETH 不是所有账户均可成交。'))
        flips=ordered[ordered.best!=ordered.before_extra_fees_best]
        row=(flips if len(flips) else ordered).iloc[0]
        records.append(dict(case='费用是否改变排序',event_present=bool(len(flips)),evidence=[row.to_dict()],
                            decision=f"在当前费用假设下优先 {row['best']}；DEX 报价已内含池费，不能再次扣除。"))
    else:
        records.extend([dict(case=n,event_present=False,evidence=[],decision='没有可比较报价，不能得出场所选择结论。') for n in ['规模与场所','费用是否改变排序']])
    rejected=next((e for e in events if e['status']=='rejected'),None)
    if rejected:
        records.append(dict(case='拒单与剩余风险',stress=False,evidence=rejected,
                             decision='停止该笔；保留原库存，先恢复有效报价或核对场所余额。'))
    else:
        a=Ledger('CEX',3000);a.balances['ETH']=Decimal('1.5')
        before={k:str(v) for k,v in a.balances.items()}
        e=a.apply('stress-stale','sell','.5',1500,'1.5',0,3000,0,'synthetic-expired',reason='stale_cex')
        records.append(dict(case='拒单与剩余风险',stress=True,evidence=e,before=before,
                             remaining_exposure_eth='1.5',reduction_to_target_eth='0.5',
                             decision='合成压力情景：拒绝过期报价，库存仍为 1.5 ETH；待有效深度后估算卖出 0.5 ETH，不能认为风险已解除。'))
        fresh={'id':'SYNTHETIC_RECOVERY_BOOK','available_at':1,
               'bids_json':'[["2999","0.3"],["2998","0.3"]]','asks_json':'[["3001","1"]]'}
        records[-1]['labelled_recovery_scenario']=reduction_proposal('CEX',a.balances,fresh,1)
    for record in records[:2]:
        for item in record['evidence']:
            t=item['available_at'];context={}
            for venue in ['CEX','DEX']:
                prior=[e for e in events if e['venue']==venue and e['timestamp']<=t]
                initial={'USDC':'10000','ETH':'1'} if venue=='CEX' else {'USDC':'10000','WETH':'1','ETH':'.02'}
                balances=prior[-1]['balances'] if prior else initial
                asset='ETH' if venue=='CEX' else 'WETH'
                qty=Decimal(str(item['quantity']))
                cash_needed=Decimal(str(item['cex_net'] if venue=='CEX' else item['dex_quote']))
                gas_needed=Decimal(item['gas_eth']) if venue=='DEX' else Decimal(0)
                feasible=(Decimal(balances['USDC'])>=cash_needed if item['side']=='buy' else Decimal(balances[asset])>=qty)
                feasible=feasible and (venue=='CEX' or Decimal(balances['ETH'])>=gas_needed)
                context[venue]={'balances':balances,'inventory_cash_feasible':bool(feasible),
                                'note':'假设费率与现有报价；仍需新鲜度、交易权限/授权与实际成交条件。'}
            item['venue_inventory_context']=context
    dump(out/'decisions.json',records)
    text=f'# 三份交易决策记录\n\n数据属性：{prefix}。后见 markout 不参与决策。\n'
    for r in records:
        text+=f"\n## {r['case']}\n\n{r['decision']}\n\n```json\n{json.dumps(r,ensure_ascii=False,indent=2,default=str)}\n```\n"
    text+='\n报价到成交仍有区块状态变化、gas、余额/授权、交易纳入区块条件。本项目未提交交易。\n'
    (out/'decisions.md').write_text(text,encoding='utf-8')


def report(books,dex,m,out):
    """串联成本比较、回放、风控、LP演示和手算明细，写各报告并返回质量统计和对账结果。

    输入参数：books、dex、m、out（单位和范围由下方校验及调用方契约限定）。"""
    out=Path(out);c=m['config']
    comps,invalid,sens=comparisons(books,dex,c)
    comps.to_parquet(out/'comparisons.parquet',index=False)
    sens.to_parquet(out/'fee_sensitivity.parquet',index=False)
    dump(out/'invalid_comparisons.json',invalid)
    accounts,events,audits,equity,risk_events=replay(books,dex,m)
    dump(out/'ledger.json',events);dump(out/'reconciliation.json',audits)
    dump(out/'risk_events.json',risk_events)
    equity.to_parquet(out/'equity.parquet',index=False)
    decisions(comps,events,out,m['kind'])
    if len(dex):
        first=dex.sort_values('available_at').iloc[0]
        anchor=1e12/(int(first.sqrt_price_x96)/2**96)**2
        gas_price=(int(first.base_fee_wei)+1e9)/1e18
        lp=scenario(anchor,gas_cost=500000*gas_price*anchor)
        lp['gas_sensitivity']=[{'multiplier':k,'scenarios':scenario(anchor,gas_cost=500000*gas_price*anchor*k)['scenarios']} for k in [.5,2]]
        dump(out/'lp.json',lp)
        path=[]
        for d in dex.drop_duplicates('group_id').to_dict('records'):
            p=1e12/(int(d['sqrt_price_x96'])/2**96)**2
            x,y=inventory(p,lp['lower'],lp['upper'],lp['liquidity_human'])
            path.append(dict(t=d['available_at'],price=p,lp_value=x*p+y,hodl_value=lp['initial_weth']*p+lp['initial_usdc'],in_range=lp['lower']<=p<=lp['upper']))
        pd.DataFrame(path).to_parquet(out/'lp_path.parquet',index=False)
    # Export raw levels and every intermediate value for first-book manual checking.
    hand={'source_id':books.iloc[0]['id'],'bids':json.loads(books.iloc[0].bids_json),'asks':json.loads(books.iloc[0].asks_json),
          'buy':sweep(books.iloc[0],'buy','.5',c['cex_fee_bps']),'sell':sweep(books.iloc[0],'sell','.5',c['cex_fee_bps']),
          'note':'These are implementation outputs; independent fixed answers are in docs/INDEPENDENT_CHECKS.md and tests.'}
    dump(out/'first_book_working.json',hand)
    return dict(comparison_rows=len(comps),valid_groups=int(comps.group_id.nunique()) if len(comps) else 0,
                all_reconciled=all(a['ok'] for a in audits.values()),orders=len(events),
                pnl_identity_ok=all(abs(Decimal(e['pnl_identity_gap']))<=Decimal('0.000001') for e in events),
                filled=sum(e['status']=='filled' for e in events))
