"""组件用途：维护 Bybit 快照和增量的状态机；缺快照或更新编号断档时停止输出，必须新快照恢复。。

原始说明：Bybit snapshot/delta state shared by historical replay and live ingestion."""
import json
from decimal import Decimal

class OrderBook:
    """维护 Bybit 快照和增量的状态机；缺快照或更新编号断档时停止输出，必须新快照恢复。"""
    def __init__(self, symbol='ETHUSDC', strict_contiguous=True):
        """初始化标的、严格连续编号策略、两侧档位、有效标记及断档/重置/重复计数。

        输入参数：symbol、strict_contiguous（单位和范围由下方校验及调用方契约限定）。"""
        self.symbol, self.strict_contiguous = symbol, strict_contiguous
        self.bids, self.asks = {}, {}
        self.u = self.ts = None
        self.valid = False
        self.gaps = self.resets = self.duplicates = 0

    def apply(self, message):
        """按消息检查标的、时间、更新编号；快照重建，增量替换档位，零数量删除。断档或交叉时失效并返回 False。

        输入参数：message（单位和范围由下方校验及调用方契约限定）。"""
        data = message['data']
        if data['s'] != self.symbol:
            raise ValueError('Wrong instrument')
        ts, u = int(message['ts']), int(data['u'])
        snapshot = message['type'] == 'snapshot'
        if message['type'] not in ('snapshot','delta'):
            raise ValueError('Unknown event type')
        if self.ts is not None and ts < self.ts:
            self.valid = False
            self.gaps += 1
            return False
        if snapshot:
            self.bids, self.asks = {}, {}
            self.valid = True
            self.resets += 1
        elif not self.valid:
            return False
        elif u == self.u:
            self.duplicates += 1
            return False
        elif u < self.u or (self.strict_contiguous and u != self.u+1):
            # Archive policy is deliberately stricter than the API's monotonic-ID guarantee.
            self.valid = False
            self.gaps += 1
            return False
        for key, side in [('b',self.bids),('a',self.asks)]:
            for price, size in data[key]:
                p, q = Decimal(price), Decimal(size)
                if not p.is_finite() or not q.is_finite() or p<=0 or q<0:
                    self.valid = False
                    raise ValueError('Invalid level')
                if q == 0:
                    side.pop(p,None)
                else:
                    side[p] = q
        self.ts, self.u = ts, u
        if not self.bids or not self.asks or max(self.bids)>=min(self.asks):
            self.valid = False
            self.gaps += 1
            return False
        return True

    def row(self, available_at, depth=20):
        """仅从有效簿态生成排序的前 depth 档位及事件/可用时间记录；无有效快照则抛错。

        输入参数：available_at、depth（单位和范围由下方校验及调用方契约限定）。"""
        if not self.valid:
            raise ValueError('No valid snapshot')
        encode = lambda side, reverse: json.dumps([[str(p),str(side[p])] for p in sorted(side,reverse=reverse)[:depth]])
        return dict(id=f'bybit-{self.ts}-{self.u}', available_at=float(available_at),
            exchange_ts=self.ts/1000, update_id=str(self.u), venue='bybit', symbol=self.symbol,
            bids_json=encode(self.bids,True), asks_json=encode(self.asks,False))
