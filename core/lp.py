"""组件用途：单一未跨初始化tick区间的浮点兑换公式；先扣池费再更新平方根价格，不适用于跨区间执行。；把价格夹在给定LP区间，计算流动性对应两种资产数量；区间外仓位变为单一资产。。"""
import math


def single_range_swap(sqrt_price, liquidity, amount_in, zero_for_one, fee=0.0005):
    """单一未跨初始化tick区间的浮点兑换公式；先扣池费再更新平方根价格，不适用于跨区间执行。

    输入参数：sqrt_price、liquidity、amount_in、zero_for_one、fee（单位和范围由下方校验及调用方契约限定）。

    原始实现说明：
    Raw token units, ONLY while the next initialized tick is not crossed."""
    if min(sqrt_price, liquidity, amount_in) <= 0 or not 0 <= fee < 1:
        raise ValueError('invalid range swap')
    dx = amount_in * (1 - fee)
    if zero_for_one:
        after = 1 / (1 / sqrt_price + dx / liquidity)
        output = liquidity * (sqrt_price - after)
    else:
        after = sqrt_price + dx / liquidity
        output = liquidity * (1 / sqrt_price - 1 / after)
    return after, output


def inventory(price, lower, upper, liquidity):
    """把价格夹在给定LP区间，计算流动性对应两种资产数量；区间外仓位变为单一资产。

    输入参数：price、lower、upper、liquidity（单位和范围由下方校验及调用方契约限定）。"""
    if not 0 < lower < upper or price <= 0 or liquidity < 0:
        raise ValueError('invalid position')
    a, b = math.sqrt(lower), math.sqrt(upper)
    s = math.sqrt(min(max(price, lower), upper))
    return liquidity * (1 / s - 1 / b), liquidity * (s - a)


def scenario(anchor, spacing=10, gas_cost=0):
    # Ethereum pool token0 USDC (6), token1 WETH (18): raw ratio = 1e12 / human ETH price.
    """以参考价生成对齐tick的固定宽度演示仓位，按价格冲击计算资产、持币对照和手续费盈亏平衡；不声称历史手续费收益。

    输入参数：anchor、spacing、gas_cost（单位和范围由下方校验及调用方契约限定）。"""
    low_tick = math.floor(math.log(1e12 / (anchor * 1.02), 1.0001) / spacing) * spacing
    high_tick = math.ceil(math.log(1e12 / (anchor * .98), 1.0001) / spacing) * spacing
    lower, upper = 1e12 / 1.0001**high_tick, 1e12 / 1.0001**low_tick
    x, y = inventory(anchor, lower, upper, 1)
    liquidity = 1000 / (x * anchor + y)
    x0, y0 = inventory(anchor, lower, upper, liquidity)
    rows = []
    for shock in (-.05, -.02, 0, .02, .05):
        p = anchor * (1 + shock)
        x, y = inventory(p, lower, upper, liquidity)
        lp, hodl = x*p+y, x0*p+y0
        rows.append(dict(shock=shock, price=p, weth=x, usdc=y, lp_value=lp, hodl_value=hodl,
                         inventory_difference=lp-hodl, gas_cost=gas_cost,
                         fee_to_break_even=max(0, hodl-lp+gas_cost), in_range=lower <= p <= upper))
    return dict(anchor=anchor, lower=lower, upper=upper, tick_lower=low_tick, tick_upper=high_tick,
                liquidity_human=liquidity, initial_weth=x0, initial_usdc=y0, scenarios=rows,
                fee_income_assumed=0, historical_fee_reconstruction=False)
