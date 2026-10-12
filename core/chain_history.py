"""Uniswap V3 历史逐事件提取和固定区块成本比较，区块内顺序不伪造成秒级时间。"""
from decimal import Decimal as D
import json
import uuid
import pandas as pd
from .io import ROOT,read,dump,utcnow,code_hash
from .network import DexReader
from .execution import sweep

SWAP='Swap(address,address,int256,int256,uint160,uint128,int24)'
MINT='Mint(address,address,int24,int24,uint128,uint256,uint256)'
BURN='Burn(address,int24,int24,uint128,uint256,uint256)'


def block_at(reader,target):
    """二分查找时间戳不晚于指定 UTC 秒的最后区块；仅访问公共区块，不插值交易时间。"""
    low,high=1,reader.w3.eth.block_number
    if target>reader.w3.eth.get_block(high)['timestamp']:raise ValueError('Historical time exceeds latest available block')
    while low<high:
        middle=(low+high+1)//2
        if reader.w3.eth.get_block(middle)['timestamp']<=target:low=middle
        else:high=middle-1
    return reader.w3.eth.get_block(low)


def decode_event(reader,item,header):
    """解码一次 Swap/Mint/Burn，保存交易与日志顺序；Swap 数量是池资金变化，不冒充用户净钱包变化。"""
    topic=bytes(item['topics'][0])
    common=dict(block=int(item['blockNumber']),block_time_utc=pd.Timestamp(header['timestamp'],unit='s',tz='UTC').isoformat(),
        block_hash=item['blockHash'].hex(),transaction_hash=item['transactionHash'].hex(),transaction_index=int(item['transactionIndex']),log_index=int(item['logIndex']))
    if topic==bytes(reader.w3.keccak(text=SWAP)):
        amount0,amount1,sqrt_price,liquidity,tick=reader.w3.codec.decode(['int256','int256','uint160','uint128','int24'],bytes(item['data']))
        return dict(**common,event='Swap',usdc_pool_delta=str(D(amount0)/D(10)**6),weth_pool_delta=str(D(amount1)/D(10)**18),sqrt_price_x96=str(sqrt_price),liquidity=str(liquidity),tick=tick)
    mint=topic==bytes(reader.w3.keccak(text=MINT))
    if not mint and topic!=bytes(reader.w3.keccak(text=BURN)):
        raise ValueError('Unsupported pool event signature')
    types=['address','uint128','uint256','uint256'] if mint else ['uint128','uint256','uint256']
    values=reader.w3.codec.decode(types,bytes(item['data']))
    amount,amount0,amount1=values[-3:]
    lower=reader.w3.codec.decode(['int24'],bytes(item['topics'][-2]))[0]
    upper=reader.w3.codec.decode(['int24'],bytes(item['topics'][-1]))[0]
    return dict(**common,event='Mint' if mint else 'Burn',tick_lower=lower,tick_upper=upper,liquidity_delta=str(amount if mint else -amount),usdc_amount=str(D(amount0)/D(10)**6),weth_amount=str(D(amount1)/D(10)**18))


def extract_events(start_utc,end_utc,progress=None,cancelled=None):
    """下载最多一小时的单池 Swap/Mint/Burn 和起始池状态；分批读日志，区块 hash 对照，受全局容量限制。

    返回事件文件和摘要。这不是完整 tick 状态重建：Mint/Burn 改变的历史所有 tick 仍需初始化。
    """
    start=pd.Timestamp(start_utc);end=pd.Timestamp(end_utc)
    if start.tzinfo is None or end.tzinfo is None:raise ValueError('Specify UTC offsets for chain window')
    if not 0<(end-start).total_seconds()<=3600:raise ValueError('Chain event window must be between 1 second and 1 hour')
    if end>=pd.Timestamp.now(tz='UTC')-pd.Timedelta(minutes=3):raise ValueError('Use a completed historical window at least three minutes old')
    reader=DexReader(read(ROOT/'config.json'));reader.verify()
    initial=block_at(reader,int(start.timestamp())-1);last=block_at(reader,int(end.timestamp())-1)
    begin=initial['number']+1;finish=last['number']
    slot=reader.call(reader.pool,'slot0()',[],[],['uint160','int24','uint16','uint16','uint16','uint8','bool'],initial['number'])
    liquidity=reader.call(reader.pool,'liquidity()',[],[],['uint128'],initial['number'])[0]
    headers={};events=[]
    topics=[reader.w3.to_hex(reader.w3.keccak(text=signature)) for signature in (SWAP,MINT,BURN)]
    for first in range(begin,finish+1,100):
        if cancelled is not None and cancelled.is_set():raise InterruptedError('Chain event download cancelled')
        if progress:progress(dict(stage='chain_events',completed=first-begin,total=max(1,finish-begin+1)))
        try:
            logs=reader.w3.eth.get_logs(dict(address=reader.pool,fromBlock=first,toBlock=min(finish,first+99),topics=[topics]))
        except Exception as error:
            # 不把 RPC 密钥或 HTML 错误页保存进看板；历史事件能力与历史报价能力分别验收。
            raise ValueError('Historical pool events are unavailable from this RPC; use an archive RPC supporting eth_getLogs or supply an event file') from error
        for item in logs:
            number=int(item['blockNumber'])
            if number not in headers:headers[number]=reader.w3.eth.get_block(number)
            if item.get('removed') or item['blockHash']!=headers[number]['hash']:raise ValueError('Chain block changed during event extraction')
            events.append(decode_event(reader,item,headers[number]))
            if len(events)>10000:raise ValueError('Event count exceeds bounded one-hour extraction limit')
    if reader.w3.eth.get_block(initial['number'])['hash']!=initial['hash'] or reader.w3.eth.get_block(finish)['hash']!=last['hash']:
        raise ValueError('Historical block changed during download')
    events.sort(key=lambda row:(row['block'],row['transaction_index'],row['log_index']))
    folder=ROOT/'data'/'experiments'/'chain_events'/uuid.uuid4().hex
    from .experiment_engine import _bytes,DATA_CAP
    payload=json.dumps(events,ensure_ascii=False).encode('utf-8')
    if _bytes(ROOT/'data')+len(payload)+2_000_000>DATA_CAP:raise ValueError('Chain events exceed the 5 GB data budget')
    folder.mkdir(parents=True,exist_ok=False);(folder/'events.json').write_bytes(payload)
    report=dict(created_at=utcnow(),code_sha256=code_hash(),pool=reader.pool,start_utc=start.isoformat(),end_utc=end.isoformat(),event_count=len(events),
        counts={name:sum(row['event']==name for row in events) for name in ('Swap','Mint','Burn')},preview=events[:100],events_path=str(folder/'events.json'),
        initial_state=dict(block=initial['number'],block_hash=initial['hash'].hex(),sqrt_price_x96=str(slot[0]),tick=slot[1],liquidity=str(liquidity)),
        last_block=finish,state_reconstruction_complete=False,time_semantics='Block timestamp and transaction/log order; not per-event second timestamps')
    dump(folder/'report.json',report)
    return report


def compare_channels(day,utc_time,side,quantity,fees_bps,gas_units=200000,priority_fee_gwei=1,
                     block_delay_seconds=12,max_chain_age_seconds=60,max_book_age_ms=1500,latency_ms=250,
                     weth_accepted=False,progress=None,cancelled=None):
    """比较固定数量的 CEX 主动成交和 Uniswap WETH 兑换含 gas 成本；固定过去区块，不把历史未来区块当已知。

    链上结果是 WETH，不隐含包装或解包；gas 使用用户给定单位与过去区块基础费，非实际回执。
    """
    if side not in ('buy','sell') or not D(str(quantity)).is_finite() or D(str(quantity))<=0:raise ValueError('Use a positive ETH/WETH quantity and buy/sell direction')
    if not weth_accepted:raise ValueError('Explicitly accept WETH settlement to compare Uniswap; ETH wrapping is not included')
    for venue in ('bybit','okx'):
        fee=D(str(fees_bps.get(venue,'NaN')))
        if not fee.is_finite() or not 0<=fee<=1000:raise ValueError('Specify valid exchange fees in basis points')
    if not 21000<=gas_units<=1000000 or not 0<=priority_fee_gwei<=100 or not 1<=block_delay_seconds<=300 or not 12<=max_chain_age_seconds<=600:
        raise ValueError('Gas or block availability assumption is outside supported bounds')
    if not 0<=latency_ms<=5000 or not 1<=max_book_age_ms<=60000:raise ValueError('Invalid exchange latency or freshness assumption')
    at=pd.Timestamp(f'{day}T{utc_time}',tz='UTC').timestamp()
    if at>pd.Timestamp.now(tz='UTC').timestamp()-180:raise ValueError('Choose a completed historical time')
    reader=DexReader(read(ROOT/'config.json'));reader.verify()
    header=block_at(reader,int(at-block_delay_seconds))
    age=at-header['timestamp']
    if age>max_chain_age_seconds:raise ValueError('Historical chain state is older than the permitted age')
    c=reader.config;block=header['number'];amount=int(D(str(quantity))*D(10)**18)
    if D(amount)/D(10)**18!=D(str(quantity)):raise ValueError('Quantity exceeds WETH precision')
    sig=('quoteExactOutputSingle' if side=='buy' else 'quoteExactInputSingle')+'((address,address,uint256,uint24,uint160))'
    args=(c['usdc'] if side=='buy' else c['weth'],c['weth'] if side=='buy' else c['usdc'],amount,c['fee'],0)
    quoted,after,crossed,estimate=reader.call(c['quoter'],sig,['(address,address,uint256,uint24,uint160)'],[args],['uint256','uint160','uint32','uint256'],block)
    slot=reader.call(reader.pool,'slot0()',[],[],['uint160','int24','uint16','uint16','uint16','uint8','bool'],block)
    mid_price=D(10)**12/(D(slot[0])/D(2**96))**2
    gas_eth=(D(header['baseFeePerGas'])+D(str(priority_fee_gwei))*D(10)**9)*D(gas_units)/D(10)**18
    gas_quote=gas_eth*mid_price;quote=D(quoted)/D(10)**6
    rows=[dict(channel='Uniswap V3',asset='WETH',status='quoted',quantity=str(quantity),trade_quote=str(quote),gas_usdc=str(gas_quote),fee_usdc=None,
        total_quote=str(quote+gas_quote if side=='buy' else quote-gas_quote),state_time=pd.Timestamp(header['timestamp'],unit='s',tz='UTC').isoformat())]
    from .experiment_engine import _resolve_book
    for venue in ('bybit','okx'):
        if cancelled is not None and cancelled.is_set():raise InterruptedError('Channel comparison cancelled')
        try:
            path,manifest=_resolve_book(day,venue)
            frame=pd.read_parquet(path,columns=['exchange_ts','bids_json','asks_json'])
            frame['available_at']=frame.exchange_ts.astype(float)+latency_ms/1000
            available=frame[frame.available_at<=at].sort_values('available_at')
            if available.empty or (at-float(available.iloc[-1].available_at))*1000>max_book_age_ms:raise ValueError('No fresh order book at decision time')
            current=available.iloc[-1]
            # 比较决策时可见报价；不用未来到达盘口替换报价，否则会给场所选择提供未来信息。
            filled=sweep(current.to_dict(),side,str(quantity),str(fees_bps[venue]))
            rows.append(dict(channel=venue.upper(),asset='ETH',status='quoted' if filled['complete'] else 'partial',quantity=filled['filled'],trade_quote=filled['quote'],fee_usdc=filled['fee'],gas_usdc='0',
                total_quote=str(D(filled['quote'])+D(filled['fee']) if side=='buy' else D(filled['quote'])-D(filled['fee'])),state_time=pd.Timestamp(float(current.exchange_ts),unit='s',tz='UTC').isoformat(),books_sha256=manifest.get('books_sha256'),assumed_available_at=float(current.available_at)))
        except (FileNotFoundError,ValueError) as exc:rows.append(dict(channel=venue.upper(),status='unavailable',reason=str(exc)))
    if reader.w3.eth.get_block(block)['hash']!=header['hash']:raise ValueError('Chain block changed during cost comparison')
    report=dict(created_at=utcnow(),code_sha256=code_hash(),day=day,utc_time=utc_time,side=side,quantity=str(quantity),rows=rows,
        config=dict(day=day,utc_time=utc_time,side=side,quantity=str(quantity),fees_bps=fees_bps,gas_units=gas_units,priority_fee_gwei=priority_fee_gwei,block_delay_seconds=block_delay_seconds,max_chain_age_seconds=max_chain_age_seconds,max_book_age_ms=max_book_age_ms,latency_ms=latency_ms,weth_accepted=weth_accepted),
        block=block,block_hash=header['hash'].hex(),chain_state_age_seconds=age,gas_eth=str(gas_eth),gas_units=gas_units,quoter_internal_gas_estimate=int(estimate),ticks_crossed=int(crossed),
        weth_settlement=True,atomic_execution=False,latency_ms=latency_ms,latency_effect_included=False,mode='decision-time indicative cost comparison, not multi-venue optimal allocation',
        gas_assumption='User specified total swap gas; pool fee is already included in Quoter amount, not charged twice; approvals, wrapping and failed-transaction costs must be separately specified')
    folder=ROOT/'data'/'experiments'/'channel_comparison'/uuid.uuid4().hex;dump(folder/'report.json',report)
    return report
