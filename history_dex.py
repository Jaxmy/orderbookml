"""组件用途：以九十位Decimal计算tick平方根价边界；是数学近似而非Solidity逐位TickMath实现。；在只读DexReader上加入调用节流和历史区块查找，供四小时状态采样。。

原始说明：Bounded four-hour archive-state research; all eth_calls pin a canonical block.

Fee growth supports a hypothetical small LP position, not a real wallet claim.
Only public read-only RPC methods are used. Checkpointed after every complete group."""
import os
import time
from decimal import Decimal as D,localcontext
from datetime import datetime
from web3 import Web3
from core.io import ROOT,read,dump,sha,utcnow
from core.network import DexReader
from core.defi import Q96,amount0_delta,amount1_delta,fee_growth_inside,accrued_fees
from download_history import HOME

TICK_TYPES=['uint128','int128','uint256','uint256','int56','uint160','uint32','bool']
SLOT_TYPES=['uint160','int24','uint16','uint16','uint16','uint8','bool']

def sqrt_tick(tick):
    # High precision mathematical boundary, not a byte-for-byte Solidity TickMath port.
    """以九十位Decimal计算tick平方根价边界；是数学近似而非Solidity逐位TickMath实现。

    输入参数：tick（单位和范围由下方校验及调用方契约限定）。"""
    with localcontext() as ctx:
        ctx.prec=90
        return int(D('1.0001')**(D(tick)/2)*Q96)

class Archive(DexReader):
    """在只读DexReader上加入调用节流和历史区块查找，供四小时状态采样。"""
    def call(self,*args):
        """历史RPC调用前短暂停顿以限制请求速率，随后沿用固定区块ABI调用。"""
        time.sleep(.15)
        return super().call(*args)

    def block_at(self,target,guess):
        """先扩大区块范围再二分，找时间戳不晚于目标的最后区块；不伪造逐交易毫秒时间。

        输入参数：target、guess（单位和范围由下方校验及调用方契约限定）。"""
        low=max(1,guess-100); high=guess+100
        while self.w3.eth.get_block(low)['timestamp']>target: low=max(1,low-500)
        while self.w3.eth.get_block(high)['timestamp']<=target: high+=500
        while low<high:
            mid=(low+high+1)//2
            if self.w3.eth.get_block(mid)['timestamp']<=target: low=mid
            else: high=mid-1
        return low

def main():
    """按固定历史配置确定LP边界并采样四小时池状态、费用增长和报价；每组核验hash后落盘，支持检查点缓存。"""
    os.environ.setdefault('ETH_RPC_URL','https://eth.drpc.org/')
    cfg=read(ROOT/'config.json'); history=read(ROOT/'history.json')
    out=HOME/'dex'; out.mkdir(exist_ok=True)
    d=Archive(cfg); meta=d.verify()
    start=int(datetime.fromisoformat(history['dates'][0]+'T00:00:00+00:00').timestamp())
    end=int(datetime.fromisoformat(history['test_end']).timestamp())
    specification=dict(start=start,end=end,interval_seconds=14400,quantity_eth='0.5',
        source='https://eth.drpc.org/',pool=d.pool,fee=cfg['fee'],confirmation_blocks=1,
        assumed_rpc_delay_seconds=.25,lp_initial_usdc=1000,lp_target_width_pct=2,
        note='Four-hour checkpoints, not continuous arbitrage; no private keys; hypothetical infinitesimal LP approximation')
    if (out/'specification.json').exists():
        if read(out/'specification.json')!=specification: raise ValueError('DEX specification changed')
    else: dump(out/'specification.json',specification)
    first=d.block_at(start-12,25878704)
    position=read(out/'position.json') if (out/'position.json').exists() else None
    if position is None:
        slot=d.call(d.pool,'slot0()',[],[],SLOT_TYPES,first)
        center=slot[1]; lower=(center-200)//10*10; upper=(center+200)//10*10
        # Fixed ex-ante rule: nearest OUTWARD initialized boundary, at most 100 ticks.
        for name,direction in [('lower',-1),('upper',1)]:
            tick=lower if name=='lower' else upper
            for _ in range(11):
                state=d.call(d.pool,'ticks(int24)',['int24'],[tick],TICK_TYPES,first)
                if state[-1] and state[0]>0: break
                tick+=direction*10
            else: raise ValueError('No initialized LP boundary within fixed search range')
            if name=='lower': lower=tick
            else: upper=tick
        price=D(10)**12/(D(slot[0])/Q96)**2
        probeL=10**18
        v=D(amount0_delta(slot[0],sqrt_tick(upper),probeL,False))/10**6+D(amount1_delta(sqrt_tick(lower),slot[0],probeL,False))/10**18*price
        L=int(D(1000)*probeL/v)
        position=dict(lower=lower,upper=upper,liquidity=str(L),initial_block=first,
            interpretation='Counterfactual tiny LP; unchanged historical pool fee growth; excludes own effect on pool liquidity',
            tick_math='90-digit Decimal mathematical ratio; not Solidity bit-exact')
        dump(out/'position.json',position)
    for t in range(start,end+1,14400):
        path=out/(str(t)+'.json')
        if path.exists(): print('cached',t,flush=True); continue
        block=d.block_at(t-12,first+(t-start)//12)
        header=d.w3.eth.get_block(block); next_header=d.w3.eth.get_block(block+1)
        slot=d.call(d.pool,'slot0()',[],[],SLOT_TYPES,block)
        liq=d.call(d.pool,'liquidity()',[],[],['uint128'],block)[0]
        fg=[d.call(d.pool,f'feeGrowthGlobal{i}X128()',[],[],['uint256'],block)[0] for i in [0,1]]
        low=d.call(d.pool,'ticks(int24)',['int24'],[position['lower']],TICK_TYPES,block)
        high=d.call(d.pool,'ticks(int24)',['int24'],[position['upper']],TICK_TYPES,block)
        if not low[-1] or not high[-1]: raise ValueError('Position boundary became uninitialized; cannot infer fee history')
        inside=[fee_growth_inside(fg[i],low[2+i],high[2+i],slot[1],position['lower'],position['upper']) for i in [0,1]]
        available=next_header['timestamp']+.25
        quotes=[]
        for buy in [False,True]:
            sig=('quoteExactOutputSingle' if buy else 'quoteExactInputSingle')+'((address,address,uint256,uint24,uint160))'
            args=(cfg['usdc'] if buy else cfg['weth'],cfg['weth'] if buy else cfg['usdc'],5*10**17,cfg['fee'],0)
            q,after,crossed,gas=d.call(cfg['quoter'],sig,['(address,address,uint256,uint24,uint160)'],[args],['uint256','uint160','uint32','uint256'],block)
            quotes.append(dict(side='buy' if buy else 'sell',quantity='0.5',quote_usdc=str(D(q)/10**6),
                sqrt_price_after=str(after),ticks_crossed=crossed,quoter_gas_estimate=gas,
                available_at=available,block_hash=header['hash'].hex()))
        if d.w3.eth.get_block(block)['hash']!=header['hash']: raise ValueError('Historical block hash changed')
        row=dict(target_time=t,block_number=block,block_hash=header['hash'].hex(),block_time=header['timestamp'],
            available_at=available,confirmation_block=block+1,confirmation_hash=next_header['hash'].hex(),
            sqrt_price_x96=str(slot[0]),tick=slot[1],liquidity=str(liq),base_fee_wei=str(header['baseFeePerGas']),
            fee_growth_inside=list(map(str,inside)),quotes=quotes)
        dump(path,row); print('archived',t,block,'tick',slot[1],flush=True)
    dump(out/'manifest.json',dict(created_at=utcnow(),specification=specification,metadata=meta,
        files={p.name:sha(p) for p in out.glob('*.json') if p.stem.isdigit() or p.name in ('specification.json','position.json')}))

if __name__=='__main__': main()
