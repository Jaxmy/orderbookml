"""组件用途：把金额按既定精度量化，统一吃单报价和手续费的舍入规则。；将指定方向的 JSON 档位转成 Decimal 价格/数量列表；合法性和二十档上限由 validate_book 检查。。

原始说明：Price calculations use Decimal; float conversion is for charts/features only."""
import json
from decimal import Decimal, ROUND_HALF_EVEN

D = Decimal
USDC = D('0.000001')


def money(x):
    """把金额按既定精度量化，统一吃单报价和手续费的舍入规则。

    输入参数：x（单位和范围由下方校验及调用方契约限定）。"""
    return D(x).quantize(USDC, rounding=ROUND_HALF_EVEN)


def levels(row, side):
    """将指定方向的 JSON 档位转成 Decimal 价格/数量列表；合法性和二十档上限由 validate_book 检查。

    输入参数：row、side（单位和范围由下方校验及调用方契约限定）。"""
    value = row['asks_json' if side == 'buy' else 'bids_json']
    return [(D(str(p)), D(str(q))) for p, q in json.loads(value)]


def validate_book(row):
    """解析买卖盘，检查排序及买一低于卖一，拒绝空簿、非法量价和交叉盘口；返回两侧 Decimal 档位。

    输入参数：row（单位和范围由下方校验及调用方契约限定）。"""
    bids, asks = levels(row, 'sell'), levels(row, 'buy')
    if not bids or not asks or len(bids) > 20 or len(asks) > 20:
        raise ValueError('empty or oversized book')
    if any(not p.is_finite() or not q.is_finite() or p <= 0 or q <= 0 for p, q in bids + asks):
        raise ValueError('non-positive level')
    if any(bids[i][0] <= bids[i+1][0] for i in range(len(bids)-1)):
        raise ValueError('unsorted/duplicate bids')
    if any(asks[i][0] >= asks[i+1][0] for i in range(len(asks)-1)):
        raise ValueError('unsorted/duplicate asks')
    if bids[0][0] >= asks[0][0]:
        raise ValueError('crossed book')
    return bids, asks


def mid(row):
    """校验盘口后计算买一与卖一的算术平均，作为成本比较参考价，不是可成交价。

    输入参数：row（单位和范围由下方校验及调用方契约限定）。"""
    bids, asks = validate_book(row)
    return (bids[0][0] + asks[0][0]) / 2


def sweep(row, side, quantity, fee_bps='10'):
    """按买入吃卖盘、卖出吃买盘逐档撮合，累计金额和费率，输出明细、均价和缺量；深度不足不外推成交。

    输入参数：row、side、quantity、fee_bps（单位和范围由下方校验及调用方契约限定）。"""
    if side not in ('buy', 'sell') or D(str(quantity)) <= 0 or D(str(fee_bps)) < 0:
        raise ValueError('invalid order')
    reference = mid(row)
    wanted, amount, value = D(str(quantity)), D(0), D(0)
    steps = []
    for price, available in levels(row, side):
        take = min(wanted - amount, available)
        if take <= 0:
            break
        amount += take
        value += take * price
        steps.append({'price': str(price), 'quantity': str(take), 'quote': str(take * price)})
    vwap = value / amount if amount else D(0)
    fee = money(value * D(str(fee_bps)) / 10000)
    quote = money(value)
    return dict(side=side, quantity=str(wanted), filled=str(amount), complete=amount == wanted,
                quote=str(quote), fee=str(fee), vwap=str(vwap), mid=str(reference),
                price_cost_bps=str((vwap / reference - 1) * (1 if side == 'buy' else -1) * 10000),
                net_quote=str(quote + fee if side == 'buy' else quote - fee), steps=steps)


def dex_cost(row, reference, units=200000, priority_gwei='1'):
    """读取已含池费的链上兑换报价，按 gas 用量、基础费及优先费折算 ETH/USDC 成本；不重复扣池费。

    输入参数：row、reference、units、priority_gwei（单位和范围由下方校验及调用方契约限定）。"""
    gas_eth = D(units) * (D(str(row['base_fee_wei'])) + D(str(priority_gwei)) * 10**9) / 10**18
    gas_usdc = money(gas_eth * D(str(reference)))
    quote = D(str(row['quote_usdc']))  # Pool fee already included by Quoter.
    net = quote + gas_usdc if row['side'] == 'buy' else quote - gas_usdc
    return dict(quote=str(quote), gas_eth=str(gas_eth), gas_usdc=str(gas_usdc), net_quote=str(net))
