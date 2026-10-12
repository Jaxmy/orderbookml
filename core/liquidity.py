"""历史模拟的自有深度消耗：同一未变盘口不能被多个子单反复吃掉。"""
from decimal import Decimal
import json


class DepthConsumption:
    """为一个方案隔离深度账本；外生盘口内容改变后才重新建立可用深度。"""

    def __init__(self):
        """初始化最近簿态签名和逐方向、逐价格已消耗量，不与其他方案共享。"""
        self.signature = None
        self.used = {}

    def available(self, book):
        """扣掉本方案在同一簿态吃掉的量，返回副本；任一侧耗尽时返回 None。

        签名采用完整买卖档位内容，而不是时间戳：仅更新时间且数量不变不补回深度。
        外部簿态变化时重置是一种外生市场近似，并不模拟订单对未来市场的冲击。
        """
        signature = (book['bids_json'], book['asks_json'])
        if signature != self.signature:
            self.signature, self.used = signature, {}
        result = dict(book)
        for field in ('bids_json', 'asks_json'):
            levels = []
            for price, quantity in json.loads(book[field]):
                left = Decimal(str(quantity)) - self.used.get((field, Decimal(str(price))), Decimal(0))
                if left > 0:
                    levels.append([str(price), str(left)])
            if not levels:
                return None
            result[field] = json.dumps(levels)
        return result

    def consume(self, side, fills):
        """按真实模拟成交明细扣减买单所吃的卖盘或卖单所吃的买盘，不扣计划量。"""
        field = 'asks_json' if side == 'buy' else 'bids_json'
        for fill in fills:
            key = (field, Decimal(str(fill['price'])))
            self.used[key] = self.used.get(key, Decimal(0)) + Decimal(str(fill['quantity']))
