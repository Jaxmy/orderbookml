"""组件用途：用 Decimal 向下取整，将可用数量换为整数步长，保证成交不超数量精度或余额。；校验盘口、方向、目标和各所余额；按含费边际价格排序逐档分配并扣减资金。返回成交分配、费用及缺量。精确性限于独立档位和线性费率，不模拟排队、gas或市场冲击。。

原始说明：Exact static CEX routing over the visible piecewise-constant L2 ladders."""
from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR

from .execution import validate_book

D = Decimal


def _floor_units(value: D, step: D) -> int:
    """用 Decimal 向下取整，将可用数量换为整数步长，保证成交不超数量精度或余额。

    输入参数：value、step（单位和范围由下方校验及调用方契约限定）。"""
    return int((value / step).to_integral_value(rounding=ROUND_FLOOR))


def optimize_static_route(books: dict[str, dict], side: str, amount_mode: str,
                          amount: str | float, fees_bps: dict[str, str | float],
                          quantity_step: str | float = '0.00000001',
                          quote_balances: dict[str, str | float] | None = None,
                          base_balances: dict[str, str | float] | None = None) -> dict:
    """校验盘口、方向、目标和各所余额；按含费边际价格排序逐档分配并扣减资金。返回成交分配、费用及缺量。精确性限于独立档位和线性费率，不模拟排队、gas或市场冲击。

    输入参数：books、side、amount_mode、amount、fees_bps、quantity_step、quote_balances、base_balances（单位和范围由下方校验及调用方契约限定）。

    原始实现说明：
    Route a one-shot order across venues by sorting net marginal prices.
    
        With separable linear level costs and a shared quantity/budget constraint,
        sorting fee-adjusted levels is an exact greedy solution. Balances and visible
        depth cap each venue. This is a snapshot solver, not a queue or impact model."""
    if not books or side not in ('buy', 'sell') or amount_mode not in ('base_quantity', 'quote_budget'):
        raise ValueError('Invalid venues, side or amount mode')
    if amount_mode == 'quote_budget' and side != 'buy':
        raise ValueError('Quote-budget mode is only defined for buys')
    target = D(str(amount))
    step = D(str(quantity_step))
    if not target.is_finite() or target <= 0 or not step.is_finite() or step <= 0:
        raise ValueError('Amount and quantity step must be finite and positive')

    fee_map = {venue: D(str((fees_bps or {}).get(venue, 0))) for venue in books}
    if any(not x.is_finite() or x < 0 or x > 10000 for x in fee_map.values()):
        raise ValueError('Taker fees must be finite and between 0 and 10000 bps')
    quote_left = {venue: D(str((quote_balances or {}).get(venue, 'Infinity')))
                  for venue in books}
    base_left = {venue: D(str((base_balances or {}).get(venue, 'Infinity')))
                 for venue in books}
    for values in (quote_left, base_left):
        if any(x.is_nan() or x < 0 for x in values.values()):
            raise ValueError('Venue balances must be nonnegative')

    levels = []
    for venue, row in books.items():
        bids, asks = validate_book(row)
        source = asks if side == 'buy' else bids
        fee_rate = fee_map[venue] / D(10000)
        for price, available in source:
            adjusted = price * (D(1) + fee_rate if side == 'buy' else D(1) - fee_rate)
            levels.append(dict(venue=venue, price=price, capacity=available,
                               adjusted_price=adjusted, fee_rate=fee_rate))
    levels.sort(key=lambda x: (x['adjusted_price'] if side == 'buy' else -x['adjusted_price'],
                               x['venue'], x['price']))

    requested_units = _floor_units(target, step) if amount_mode == 'base_quantity' else None
    if amount_mode == 'base_quantity' and step * requested_units != target:
        raise ValueError('Base quantity must be an exact multiple of the configured quantity step')
    remaining_units = requested_units
    budget_left = target if amount_mode == 'quote_budget' else None
    spent_by_venue = {venue: D(0) for venue in books}
    filled_by_venue = {venue: D(0) for venue in books}
    gross_by_venue = {venue: D(0) for venue in books}
    fee_by_venue = {venue: D(0) for venue in books}
    fills = []

    for item in levels:
        venue, price = item['venue'], item['price']
        capacity_units = _floor_units(item['capacity'], step)
        if side == 'buy' and quote_left[venue].is_finite():
            capacity_units = min(capacity_units, _floor_units(quote_left[venue] / (price * (1 + item['fee_rate'])), step))
        elif side == 'sell' and base_left[venue].is_finite():
            capacity_units = min(capacity_units, _floor_units(base_left[venue], step))
        if amount_mode == 'base_quantity':
            take_units = min(capacity_units, remaining_units)
        else:
            cost_per_unit = step * price * (1 + item['fee_rate'])
            take_units = min(capacity_units, _floor_units(budget_left / cost_per_unit, D(1)))
        if take_units <= 0:
            continue
        quantity = step * take_units
        gross = quantity * price
        fee = gross * item['fee_rate']
        net = gross + fee if side == 'buy' else gross - fee
        if side == 'buy' and net > quote_left[venue] + D('1e-24'):
            continue
        item['remaining_capacity_units'] = capacity_units - take_units
        spent_by_venue[venue] += net if side == 'buy' else gross
        filled_by_venue[venue] += quantity
        gross_by_venue[venue] += gross
        fee_by_venue[venue] += fee
        fills.append(dict(venue=venue, price=str(price), quantity=str(quantity),
                          gross_quote=str(gross), fee_quote=str(fee), net_quote=str(net)))
        if side == 'buy':
            quote_left[venue] -= net
            if amount_mode == 'quote_budget':
                budget_left -= net
        else:
            base_left[venue] -= quantity
        if remaining_units is not None:
            remaining_units -= take_units
            if remaining_units == 0:
                break

    filled = sum(filled_by_venue.values(), D(0))
    gross = sum(gross_by_venue.values(), D(0))
    fee = sum(fee_by_venue.values(), D(0))
    net_quote = gross + fee if side == 'buy' else gross - fee
    complete = (remaining_units == 0) if requested_units is not None else budget_left is not None
    # A quote budget can leave a precision/depth remainder; completion means no
    # additional quantity step is affordable at any remaining eligible level.
    if amount_mode == 'quote_budget':
        next_cost = min((step * x['price'] * (1 + x['fee_rate']) for x in levels
                         if x.get('remaining_capacity_units', 0) > 0 and
                         quote_left[x['venue']] >= step * x['price'] * (1 + x['fee_rate'])),
                        default=None)
        complete = budget_left is not None and (next_cost is None or budget_left < next_cost)
    avg = gross / filled if filled else None
    reference_rows = [validate_book(row) for row in books.values()]
    mids = {venue: (bids[0][0] + asks[0][0]) / 2
            for venue, (bids, asks) in zip(books, reference_rows)}
    shortfall = sum(
        ((gross_by_venue[v] + fee_by_venue[v] - filled_by_venue[v] * mids[v]
          if side == 'buy' else filled_by_venue[v] * mids[v] - gross_by_venue[v] + fee_by_venue[v])
         for v in books), D(0))
    return dict(status='optimal' if complete else ('partial' if filled else 'infeasible'),
                solver='piecewise-linear marginal-level greedy',
                optimality='exact for this model: independent venue ladders, linear fees, visible depth and stated balances',
                side=side, amount_mode=amount_mode, requested=str(target),
                requested_quantity=str(target) if amount_mode == 'base_quantity' else None,
                requested_budget=str(target) if amount_mode == 'quote_budget' else None,
                quantity_step=str(step), filled_base=str(filled), gross_quote=str(gross),
                fee_quote=str(fee), net_quote=str(net_quote),
                remaining_base=str(max(D(0), target - filled)) if amount_mode == 'base_quantity' else None,
                unspent_quote=str(max(D(0), target - net_quote)) if amount_mode == 'quote_budget' else None,
                average_price=str(avg) if avg is not None else None,
                reference_mid_by_venue={v: str(mids[v]) for v in books},
                all_in_shortfall_vs_each_venue_mid=str(shortfall),
                allocation={venue: dict(base=str(filled_by_venue[venue]),
                                        gross_quote=str(gross_by_venue[venue]),
                                        fee_quote=str(fee_by_venue[venue]),
                                        net_quote=str(gross_by_venue[venue] + fee_by_venue[venue]
                                                      if side == 'buy' else gross_by_venue[venue] - fee_by_venue[venue]))
                            for venue in books},
                fills=fills,
                assumptions=['Only the displayed L2 levels are available; no queue position or market impact.',
                              'Balances are isolated by venue; this model does not transfer assets between venues.',
                              'No gas/DEX routes are included.'])
