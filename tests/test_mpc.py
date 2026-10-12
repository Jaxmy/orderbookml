import pandas as pd
import pytest

from core.conditional_model import live_feature_row
from core.mpc import _at, _history_asof, _plan, _run_replay


def _book(ts, mid='100'):
    """构造指定时刻及中间价的有效盘口，供因果和成本测试。

    输入参数：ts、mid（单位和范围由下方校验及调用方契约限定）。"""
    mid = float(mid)
    return dict(exchange_ts=ts, available_at=float(ts), mid=mid,
                bids_json=f'[["{mid - 0.1}","10"]]',
                asks_json=f'[["{mid + 0.1}","10"]]')


def test_mpc_plan_respects_child_cap_and_completes_by_deadline():
    """验证MPC子单上限及截止完成要求；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    rows = [_book(t) for t in range(100, 201)]
    frame = pd.DataFrame(rows)
    current = _at(frame, 120, 1500)
    history = _history_asof(frame, 120)
    result = _plan(current, history, 'buy', remaining_units=4, quantity_step=0.1,
                   fee_bps=10, slots_left=2, interval_seconds=10, max_child_units=2,
                   risk_aversion=0, models=None)
    assert result['status'] == 'planned'
    assert result['schedule'][0]['quantity'] <= 0.2
    assert [row['quantity'] for row in result['schedule']] == [0.2, 0.2]


def test_mpc_first_decision_does_not_depend_on_future_book_rows():
    """验证未来盘口修改不改变过去MPC首步；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    base = pd.DataFrame([_book(t, '100') for t in range(0, 121)])
    changed = base.copy()
    changed.loc[changed.available_at > 100, 'mid'] = 150.0
    changed.loc[changed.available_at > 100, 'bids_json'] = '[["149.9","10"]]'
    changed.loc[changed.available_at > 100, 'asks_json'] = '[["150.1","10"]]'

    def first_plan(frame):
        """对指定时间序列只取决策时可知簿和过去历史，再计算首步动作。

        输入参数：frame（单位和范围由下方校验及调用方契约限定）。"""
        decision = _at(frame, 100, 1500)
        history = _history_asof(frame, 100)
        return _plan(decision, history, 'buy', remaining_units=4, quantity_step=0.1,
                     fee_bps=10, slots_left=3, interval_seconds=10, max_child_units=2,
                     risk_aversion=0.5, models=None)['first_action_units']

    assert first_plan(base) == first_plan(changed)


def test_conditional_ml_features_are_invariant_to_future_market_rows():
    """验证条件特征不受未来行修改影响；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    base = pd.DataFrame([_book(t) for t in range(0, 121)])
    changed = base.copy()
    changed.loc[changed.available_at > 100, 'mid'] = 150.0
    changed.loc[changed.available_at > 100, 'bids_json'] = '[["149.9","10"]]'
    changed.loc[changed.available_at > 100, 'asks_json'] = '[["150.1","10"]]'

    def features(frame):
        """以当前时点已知盘口和历史构建条件特征，验证未来数据修改不影响输入。

        输入参数：frame（单位和范围由下方校验及调用方契约限定）。"""
        book = _at(frame, 100, 1500)
        return live_feature_row(book, _history_asof(frame, 100), 'buy', 0.1, 30)

    assert features(base) == features(changed)


def test_mpc_replay_replans_and_accounts_for_actual_fills():
    """验证MPC重规划、实际成交费用与资金更新；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    frame = pd.DataFrame([_book(t) for t in range(100, 201)])
    report = _run_replay(frame, start_at=110, side='buy', quantity=0.3,
        quantity_step=0.1, horizon_seconds=30, interval_seconds=10, fee_bps=10,
        latency_ms=0, max_book_age_ms=1500, quote_balance=1000, base_balance=0,
        policy='mpc', models=None, max_child_units=1, risk_aversion=0.5)
    assert report['status'] == 'complete'
    assert report['filled_quantity'] == pytest.approx(0.3)
    assert len(report['fills']) == 3
    assert report['ending_base_balance'] == pytest.approx(0.3)
    assert report['fee_quote'] > 0
