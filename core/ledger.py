"""组件用途：为单一场所维护资产、成本基础、费用与拒单事件；ETH/WETH与gas资产分开，不假设跨场所转移。；独立按成交方向汇总资金流与gas，不调用 Ledger.apply；检测重复和容差内余额差，返回重建账目。。"""
from decimal import Decimal
from .execution import money

D = Decimal


class Ledger:
    """为单一场所维护资产、成本基础、费用与拒单事件；ETH/WETH与gas资产分开，不假设跨场所转移。"""
    def __init__(self, venue, reference):
        """建立 CEX 或 DEX 的演示初始资金及参考成本，记录初始权益、已处理 id 和止损暂停状态。

        输入参数：venue、reference（单位和范围由下方校验及调用方契约限定）。"""
        self.venue = venue
        self.asset = 'ETH' if venue == 'CEX' else 'WETH'
        self.initial = {'USDC': D(10000), self.asset: D(1)}
        if venue == 'DEX':
            self.initial['ETH'] = D('0.02')
        self.balances = self.initial.copy()
        self.cost_basis = {a: D(str(reference)) for a in self.initial if a != 'USDC'}
        self.initial_equity = self.equity(reference)
        self.realized, self.expenses = D(0), D(0)
        self.events, self.seen = [], set()
        self.paused = False

    def equity(self, reference):
        """用参考价估值所有非 USDC 资产并加现金，返回 Decimal 账面权益，不代表已经卖出。

        输入参数：reference（单位和范围由下方校验及调用方契约限定）。"""
        return self.balances['USDC'] + sum(v * D(str(reference)) for a, v in self.balances.items() if a != 'USDC')

    def status(self, reference):
        """基于当前余额和成本基础计算已实现/未实现盈亏、费用及恒等式误差，并输出库存。

        输入参数：reference（单位和范围由下方校验及调用方契约限定）。"""
        p = D(str(reference))
        unrealized = sum(v * (p - self.cost_basis[a]) for a, v in self.balances.items() if a != 'USDC')
        equity = self.equity(p)
        return dict(equity=str(equity), pnl=str(equity - self.initial_equity),
                    realized=str(self.realized), unrealized=str(unrealized), fees=str(self.expenses),
                    pnl_identity_gap=str(equity - self.initial_equity - self.realized - unrealized + self.expenses),
                    exposure_eth=str(sum(v for a, v in self.balances.items() if a != 'USDC')),
                    balances={a: str(v) for a, v in self.balances.items()})

    def apply(self, oid, side, quantity, quote, fee, gas_eth, reference, timestamp, snapshot_id, reason=None):
        """先校验成交和去重，再检查止损、现金底线、资产余额；通过后记费用和资金变化，否则保留拒单事件且库存不变。

        输入参数：oid、side、quantity、quote、fee、gas_eth、reference、timestamp、snapshot_id、reason（单位和范围由下方校验及调用方契约限定）。"""
        q, v, f, g, p = map(lambda x: D(str(x)), (quantity, quote, fee, gas_eth, reference))
        if side not in ('buy', 'sell') or q <= 0 or min(v, f, g) < 0 or p <= 0:
            raise ValueError('invalid fill')
        if oid in self.seen:
            return dict(id=oid, status='duplicate_rejected', reason='duplicate_order_id')
        self.seen.add(oid)
        if reason is None and self.equity(p) <= self.initial_equity * D('0.98'):
            self.paused = True
        reason = reason or ('loss_limit' if self.paused else None)
        if not reason and side == 'buy' and self.balances['USDC'] < 1000:
            reason = 'cash_floor'
        cash_change = -v - f if side == 'buy' else v - f
        base_change = q if side == 'buy' else -q
        changes = {'USDC': cash_change, self.asset: base_change}
        if g:
            changes['ETH'] = changes.get('ETH', D(0)) - g
        if not reason and any(self.balances.get(a, D(0)) + delta < 0 for a, delta in changes.items()):
            reason = 'insufficient_balance'
        if not reason:
            old = self.balances[self.asset]
            if side == 'buy':
                self.cost_basis[self.asset] = (old * self.cost_basis[self.asset] + v) / (old + q)
            else:
                self.realized += v - q * self.cost_basis[self.asset]
            if g:
                self.realized += g * (p - self.cost_basis['ETH'])
            self.expenses += f + g * p
            for a, delta in changes.items():
                self.balances[a] = self.balances.get(a, D(0)) + delta
        event = dict(id=oid, venue=self.venue, timestamp=timestamp, side=side, quantity=str(q),
                     quote=str(v), fee_usdc=str(f), gas_eth=str(g), reference=str(p), snapshot_id=snapshot_id,
                     status='rejected' if reason else 'filled', reason=reason,
                     **self.status(p))
        self.events.append(event)
        return event


def reconcile(initial, fills, reported):
    """独立按成交方向汇总资金流与gas，不调用 Ledger.apply；检测重复和容差内余额差，返回重建账目。

    输入参数：initial、fills、reported（单位和范围由下方校验及调用方契约限定）。

    原始实现说明：
    Independent signed-flow aggregation; never calls Ledger.apply."""
    totals = {a: D(str(v)) for a, v in initial.items()}
    ids, duplicates = set(), []
    for e in fills:
        if e['id'] in ids:
            duplicates.append(e['id'])
            continue
        ids.add(e['id'])
        if e['status'] != 'filled':
            continue
        asset = 'ETH' if e['venue'] == 'CEX' else 'WETH'
        sign = D(1) if e['side'] == 'buy' else D(-1)
        totals[asset] = totals.get(asset, D(0)) + sign * D(e['quantity'])
        totals['USDC'] -= sign * D(e['quote']) + D(e['fee_usdc'])
        if D(e['gas_eth']):
            totals['ETH'] -= D(e['gas_eth'])
    gaps = {a: D(str(reported.get(a, 0))) - totals.get(a, D(0)) for a in set(totals) | set(reported)}
    tolerances = {a: D('0.000001') if a == 'USDC' else D('0.000000000000000001') for a in gaps}
    return dict(ok=not duplicates and all(abs(g) <= tolerances[a] for a, g in gaps.items()),
                differences={a: str(g) for a, g in gaps.items()}, duplicate_ids=duplicates,
                independently_rebuilt={a: str(v) for a, v in totals.items()})
