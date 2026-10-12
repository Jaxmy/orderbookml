"""组件用途：固定区块兑换数学与报价核对。

原始说明：Verify the FIRST fixed historical sell quote against local tick-crossing math."""
import os
import argparse
from decimal import Decimal as D
from core.io import ROOT,read,dump
from core.defi import v3_exact_input
from history_dex import Archive,sqrt_tick,TICK_TYPES
from download_history import HOME

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--quantity',choices=['0.5','20'],default='0.5')
    quantity=parser.parse_args().quantity; amount=int(D(quantity)*10**18)
    os.environ.setdefault('ETH_RPC_URL','https://eth.drpc.org/')
    d=Archive(read(ROOT/'config.json')); d.verify()
    row=read(HOME/'dex'/'1788220800.json'); block=row['block_number']
    quote=next(q for q in row['quotes'] if q['side']=='sell')
    if quantity!='0.5':
        cfg=d.config
        args=(cfg['weth'],cfg['usdc'],amount,cfg['fee'],0)
        raw,after,crossed,gas=d.call(cfg['quoter'],'quoteExactInputSingle((address,address,uint256,uint24,uint160))',
            ['(address,address,uint256,uint24,uint160)'],[args],['uint256','uint160','uint32','uint256'],block)
        quote=dict(quote_usdc=str(D(raw)/10**6),sqrt_price_after=str(after),ticks_crossed=crossed)
    current=row['tick']//10+1; boundaries=[]; evidence=[]
    after=int(quote['sqrt_price_after'])
    # Deterministic upward initialized-tick search, bounded to 10 bitmap words.
    for _ in range(10):
        word=current>>8; bit=current&255
        bitmap=d.call(d.pool,'tickBitmap(int16)',['int16'],[word],['uint256'],block)[0]
        masked=bitmap&(((1<<256)-1)^((1<<bit)-1))
        if not masked: current=(word+1)<<8; continue
        while masked:
            index=(masked&-masked).bit_length()-1; tick=((word<<8)+index)*10
            state=d.call(d.pool,'ticks(int24)',['int24'],[tick],TICK_TYPES,block)
            ratio=sqrt_tick(tick)
            boundaries.append((ratio,state[1])); evidence.append(dict(tick=tick,sqrt_price=str(ratio),liquidity_net=str(state[1])))
            if ratio>after: break
            masked &= masked-1
        if boundaries and boundaries[-1][0]>after: break
        current=(word+1)<<8
    else: raise ValueError('Bounded bitmap search exhausted')
    local=v3_exact_input(int(row['sqrt_price_x96']),int(row['liquidity']),amount,False,boundaries,500)
    expected=int(D(quote['quote_usdc'])*10**6)
    error=local['amount_out']-expected
    if d.w3.eth.get_block(block)['hash'].hex()!=row['block_hash']: raise ValueError('Block changed')
    result=dict(block=block,quantity_eth=quantity,block_hash=row['block_hash'],boundaries=evidence,local=local,
        quoter_amount_out=expected,quoter_ticks_crossed=quote['ticks_crossed'],raw_usdc_error=error,
        tolerance_raw_usdc=1,passed=local['complete'] and abs(error)<=1,
        note='First fixed snapshot, not selected for agreement; mathematical tick ratio can differ from Solidity by sub-unit rounding')
    filename='historical_swap_math.json' if quantity=='0.5' else 'historical_swap_math_20.json'
    dump(HOME/'dex'/filename,result)
    print(result)
    if not result['passed']: raise ValueError('Historical swap mismatch')
