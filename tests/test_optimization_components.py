import pandas as pd
import pytest

from core.passive import simulate_passive_limit
from core.solver import optimize_static_route


def book(bid='99', ask='101', bid_size='2', ask_size='2'):
    """构造可控的买卖档位测试输入，允许价格和数量变化，避免依赖网络行情。

    输入参数：bid、ask、bid_size、ask_size（单位和范围由下方校验及调用方契约限定）。"""
    return {'bids_json': f'[["{bid}","{bid_size}"]]',
            'asks_json': f'[["{ask}","{ask_size}"]]'}


def test_static_router_sorts_fee_adjusted_marginal_levels():
    """验证静态路由按含费边际价格分配；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    books = {
        'bybit': {'bids_json': '[ ["99","2"] ]', 'asks_json': '[["100","1"]]'},
        'okx': {'bids_json': '[["98","2"]]', 'asks_json': '[["99.9","0.3"],["101","1"]]'},
    }
    result = optimize_static_route(books, 'buy', 'base_quantity', '0.6',
                                   {'bybit': '10', 'okx': '20'}, '0.1')
    assert result['status'] == 'optimal'
    assert result['allocation']['okx']['base'] == '0.3'
    assert result['allocation']['bybit']['base'] == '0.3'
    assert result['optimality'].startswith('exact')


def test_static_router_obeys_local_quote_balances_and_budget():
    """验证各所余额隔离和总预算约束；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    books = {'a': book(ask='100'), 'b': book(ask='101')}
    fixed = optimize_static_route(books, 'buy', 'base_quantity', '0.6',
                                 {'a': 0, 'b': 0}, '0.1', quote_balances={'a': '20', 'b': '1000'})
    assert fixed['status'] == 'optimal'
    assert fixed['allocation']['a']['base'] == '0.2'
    assert fixed['allocation']['b']['base'] == '0.4'
    budget = optimize_static_route(books, 'buy', 'quote_budget', '60',
                                   {'a': 0, 'b': 0}, '0.1')
    assert budget['status'] == 'optimal'
    assert budget['filled_base'] == '0.6'
    assert float(budget['net_quote']) <= 60


def test_passive_order_reports_queue_scenarios_and_excludes_future_and_rpi():
    """验证限价队列上下界、未来与RPI排除；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    books = pd.DataFrame([dict(available_at=100.0, exchange_ts=100.0,
                               bids_json='[["99.9","2"],["99.8","1"]]',
                               asks_json='[["100.1","2"],["100.2","1"]]')])
    trades = pd.DataFrame([
        dict(available_at=101.0, price=99.9, volume=1.5, side='sell', rpi=0),
        dict(available_at=102.0, price=99.9, volume=10.0, side='sell', rpi=1),
        dict(available_at=116.0, price=99.8, volume=10.0, side='sell', rpi=0),
    ])
    result = simulate_passive_limit(books, trades, decision_at=100, side='buy',
                                    quantity='0.5', limit_price='99.9', horizon_seconds=15,
                                    latency_ms=0, price_tick='0.1')
    conservative, middle, optimistic = result['scenarios']
    assert conservative['filled_quantity'] == '0'
    assert middle['filled_quantity'] == '0.5'
    assert optimistic['filled_quantity'] == '0.5'
    assert middle['eligible_aggressor_volume'] == '1.5'
    assert result['end_reason'] == 'expiry'


def test_passive_order_rejects_marketable_limit_and_bad_tick():
    """验证被动模块拒绝可成交限价和非法价格步长；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    books = pd.DataFrame([dict(available_at=100.0, bids_json='[["99","1"]]',
                               asks_json='[["101","1"]]')])
    trades = pd.DataFrame([dict(available_at=101.0, price=100, volume=1, side='sell', rpi=0)])
    with pytest.raises(ValueError, match='marketable'):
        simulate_passive_limit(books, trades, decision_at=100, side='buy', quantity=1,
                               limit_price=101, horizon_seconds=10, latency_ms=0)
    with pytest.raises(ValueError, match='multiple'):
        simulate_passive_limit(books, trades, decision_at=100, side='buy', quantity=1,
                               limit_price='99.05', horizon_seconds=10, latency_ms=0,
                               price_tick='0.1')
