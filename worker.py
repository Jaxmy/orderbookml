"""组件用途：在给定期限内并行只读采集与推断，写有界缓存和心跳，退出记录停止；不发送交易。。

原始说明：Restartable public-market worker. Exchange accounts and signing are not used."""
import argparse
import asyncio
import json
import os
import time
from collections import deque
from websockets.asyncio.client import connect
from core.orderbook import OrderBook
from core.network import DexReader
from core.store import Store
from core.io import ROOT,read,log,sha
from core.arbitrage import opportunity

async def run(seconds, disconnect_after=None):
    """在给定期限内并行只读采集与推断，写有界缓存和心跳，退出记录停止；不发送交易。

    输入参数：seconds（单位和范围由下方校验及调用方契约限定）。"""
    store=Store(); started=time.monotonic();stop=started+seconds; latest={}; cfg=read(ROOT/'config.json'); recent=deque(maxlen=240)
    disconnected=False
    store.heartbeat('worker',dict(status='running',received_at=time.time(),duration=seconds,pid=os.getpid()))
    async def cex():
        """订阅公开Bybit盘口，应用快照/增量并保存有效视图；断开后重连且等待有效簿恢复。"""
        nonlocal disconnected
        delay=1
        while time.monotonic()<stop:
            book=OrderBook(); last_second=None
            try:
                async with connect('wss://stream.bybit.com/v5/public/spot',open_timeout=15,ping_interval=20) as ws:
                    await ws.send(json.dumps({'op':'subscribe','args':['orderbook.200.ETHUSDC']}))
                    while time.monotonic()<stop:
                        msg=json.loads(await asyncio.wait_for(ws.recv(),20))
                        if 'data' not in msg: continue
                        now=time.time()
                        # 验收专用：只断开本进程的公开行情连接，不修改主机网络或交易账户。
                        if disconnect_after is not None and not disconnected and time.monotonic()-started>=disconnect_after:
                            disconnected=True
                            store.heartbeat('audit_disconnect',dict(received_at=now,status='injected'))
                            await ws.close()
                            raise ConnectionError('Controlled public-feed disconnection')
                        if not book.apply(msg):
                            if book.gaps: raise ValueError('Gap: reconnect for fresh snapshot')
                            continue
                        delay=1
                        if int(now)==last_second: continue
                        last_second=int(now); row=book.row(now)
                        latest['book']=row; recent.append(row); store.put('book',row)
                        store.heartbeat('cex',dict(status='connected',received_at=now,update_id=book.u))
            except Exception as e:
                latest.pop('book',None)
                recent.clear()
                store.heartbeat('cex',dict(status='reconnecting',received_at=time.time(),error=type(e).__name__))
                log('bybit_reconnect',error=type(e).__name__)
                await asyncio.sleep(min(delay,max(0,stop-time.monotonic()))); delay=min(30,delay*2)
    async def dex():
        """循环在后台线程读取同区块链上报价，写状态及成本机会；异常只记录类型，不暴露RPC凭据。"""
        reader=DexReader(cfg)
        while time.monotonic()<stop:
            try:
                rows=await asyncio.to_thread(reader.sample)
                for row in rows: store.put('dex',row)
                store.heartbeat('dex',dict(status='connected',received_at=time.time(),block=rows[0]['block_number']))
                book=latest.get('book')
                if book:
                    for size in cfg['sizes']:
                        sell=next(r for r in rows if r['side']=='sell' and r['quantity']==size)
                        buy=next(r for r in rows if r['side']=='buy' and r['quantity']==size)
                        from decimal import Decimal as D
                        price=D(10)**12/(D(sell['sqrt_price_x96'])/D(2**96))**2
                        gas=(D(sell['base_fee_wei'])+D(10)**9)*D(cfg['gas_units'])/D(10)**18*price
                        now=time.time()
                        result=opportunity(book,sell,buy,size,now,gas_usdc=str(gas))
                        result.update(id=f'opportunity-{sell["block_number"]}-{size}',available_at=now,quantity=size)
                        store.put('opportunity',result)
            except Exception as e:
                store.heartbeat('dex',dict(status='error',received_at=time.time(),error=type(e).__name__))
                log('dex_worker_error',error=type(e).__name__)
            await asyncio.sleep(min(30,max(0,stop-time.monotonic())))
    async def infer():
        """从运行缓存截取因果历史并调用冻结模型，写只读预测；不足时标明模型/历史未就绪。"""
        from core.live_model import LiveModel
        try:
            model=LiveModel()
        except Exception as e:
            store.heartbeat('ml',dict(status='model_unavailable',received_at=time.time(),error=type(e).__name__))
            return
        while time.monotonic()<stop:
            rows=list(recent); decision=int(time.time()//10)*10
            try:
                result=await asyncio.to_thread(model.predict,rows,decision)
                if result:
                    store.put('prediction',result)
                    store.heartbeat('ml',dict(status='predicting',received_at=time.time(),feature_time=decision))
                else:
                    store.heartbeat('ml',dict(status='warming_up_or_stale',received_at=time.time(),books_in_window=len(rows)))
            except Exception as e:
                store.heartbeat('ml',dict(status='error',received_at=time.time(),error=type(e).__name__))
            await asyncio.sleep(min(10,max(0,stop-time.monotonic())))
    await asyncio.gather(cex(),dex(),infer())
    store.heartbeat('worker',dict(status='stopped',received_at=time.time(),duration=seconds))

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--seconds',type=int,default=21600)
    p.add_argument('--disconnect-after',type=int)
    args=p.parse_args();seconds=args.seconds
    if not 1<=seconds<=21600: raise ValueError('Bounded runs: 1..21600 seconds')
    if args.disconnect_after is not None and not 1<=args.disconnect_after<seconds:raise ValueError('Disconnect must occur within the bounded run')
    asyncio.run(run(seconds,args.disconnect_after))
