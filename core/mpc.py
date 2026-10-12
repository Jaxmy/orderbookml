"""组件用途：汇总旧历史目录与新市场缓存中的可用 Bybit 盘口日期；只代表本机已有数据，不保证外部所有日期可下载。；通过共用缓存适配器定位日期并强制核验规范化清单摘要；旧目录缺清单也拒绝使用。。

原始说明：Causal receding-horizon execution replay for a prefunded Bybit spot order."""
from __future__ import annotations

import json
import math
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path

import numpy as np
import pandas as pd

from .conditional_model import (FEATURES, live_feature_row, load_conditional_model,
                                predict_with_models)
from .cross_venue import _book_path
from .execution import sweep, validate_book
from .io import ROOT, dump, log, read, sha, utcnow
from .solver import optimize_static_route
from .liquidity import DepthConsumption

RUN_ROOT = ROOT / 'data' / 'experiments' / 'mpc' / 'runs'
HIST_ROOT = ROOT / 'data' / 'historical'


def bybit_days() -> list[str]:
    """汇总旧历史目录与新市场缓存中的可用 Bybit 盘口日期；只代表本机已有数据，不保证外部所有日期可下载。"""
    days = {p.name.removesuffix('.books.parquet') for p in HIST_ROOT.glob('*.books.parquet')}
    market_root = ROOT / 'data' / 'experiments' / 'market' / 'bybit' / 'ETHUSDC'
    if market_root.exists():
        days.update(p.name for p in market_root.iterdir() if p.is_dir() and (p / 'books.parquet').exists())
    return sorted(days)


def _path_for_day(day: str) -> tuple[Path, dict]:
    """通过共用缓存适配器定位日期并强制核验规范化清单摘要；旧目录缺清单也拒绝使用。

    输入参数：day（单位和范围由下方校验及调用方契约限定）。"""
    from .experiment_engine import _resolve_book
    return _resolve_book(day, 'bybit')


def load_bybit_timeline(day: str, latency_ms: int = 250) -> pd.DataFrame:
    """只加载单日盘口并按事件时间排序去重；事件时间加用户延迟形成可用时间，计算中间价并记录来源摘要。完整历史只供模拟器保存。

    输入参数：day、latency_ms（单位和范围由下方校验及调用方契约限定）。

    原始实现说明：
    Load one historical day; strategy helpers still enforce as-of visibility."""
    if not 0 <= latency_ms <= 5000:
        raise ValueError('Latency must be between 0 and 5000 milliseconds')
    path, manifest = _path_for_day(day)
    books = pd.read_parquet(path, columns=['exchange_ts', 'bids_json', 'asks_json'])
    books = books.sort_values('exchange_ts').drop_duplicates('exchange_ts', keep='last').reset_index(drop=True)
    books['available_at'] = books.exchange_ts.astype('float64') + latency_ms / 1000
    mids = np.full(len(books), np.nan)
    for i, row in enumerate(books.itertuples(index=False)):
        try:
            bids = json.loads(row.bids_json)
            asks = json.loads(row.asks_json)
            mids[i] = (float(bids[0][0]) + float(asks[0][0])) / 2
        except (ValueError, TypeError, IndexError, json.JSONDecodeError):
            continue
    books['mid'] = mids
    books = books[np.isfinite(books.mid)].reset_index(drop=True)
    books.attrs['source_sha256'] = sha(path)
    books.attrs['source_manifest'] = manifest
    books.attrs['source_path'] = str(path)
    return books


def _at(books: pd.DataFrame, timestamp: float, max_book_age_ms: int) -> dict | None:
    """二分找目标时点已可知的最后盘口并检查簿龄；返回决策时刻标记或 None，不用最近未来盘口补缺。

    输入参数：books、timestamp、max_book_age_ms（单位和范围由下方校验及调用方契约限定）。"""
    times = books.available_at.to_numpy(dtype='float64')
    index = int(np.searchsorted(times, timestamp, side='right') - 1)
    if index < 0 or (timestamp - times[index]) * 1000 > max_book_age_ms:
        return None
    row = books.iloc[index].to_dict()
    row['evaluation_at'] = float(timestamp)
    return row


def _history_asof(books: pd.DataFrame, timestamp: float) -> pd.DataFrame:
    # This cut is the information boundary passed to every feature calculation.
    """截断至决策时刻的历史中间价序列，形成传给特征/预测模块的信息边界。

    输入参数：books、timestamp（单位和范围由下方校验及调用方契约限定）。"""
    return books.loc[books.available_at <= timestamp, ['available_at', 'mid']].copy()


def _past_volatility_bps(history: pd.DataFrame) -> float:
    """在过去一分钟中间价变动上计算收益标准差，换为 bps；样本不足返回零，是透明历史风险基线。

    输入参数：history（单位和范围由下方校验及调用方契约限定）。"""
    if len(history) < 2:
        return 0.0
    tail = history[history.available_at >= history.available_at.iloc[-1] - 60]
    returns = tail.mid.astype('float64').pct_change(fill_method=None).dropna()
    return float(returns.std(ddof=1) * 10000) if len(returns) > 1 else 0.0


def _expected_action_cost(book: dict, history: pd.DataFrame, side: str, quantity: float,
                          fee_bps: float, offset_seconds: int, risk_aversion: float,
                          models: dict | None) -> tuple[float, dict]:
    """当前动作按真实可见簿吃单；未来动作使用适用范围内的冻结条件预测，否则持平基线。加入手续费和波动风险罚项；卖出目标取收入负值以统一最小化。

    输入参数：book、history、side、quantity、fee_bps、offset_seconds、risk_aversion、models（单位和范围由下方校验及调用方契约限定）。"""
    immediate = sweep(book, side, str(quantity), str(fee_bps))
    if not immediate['complete']:
        return math.inf, {'feasible': False, 'reason': 'visible depth is insufficient for this child'}
    sign = 1.0 if side == 'buy' else -1.0
    if offset_seconds <= 0:
        objective = float(immediate['net_quote']) * sign
        return objective, dict(feasible=True, forecast='current visible sweep',
                               estimated_net_quote=immediate['net_quote'],
                               risk_penalty_quote=0.0, offset_seconds=0)

    current_vol = _past_volatility_bps(history)
    prediction = None
    if models is not None and 0.01 <= quantity <= 1.0 and 10 <= offset_seconds <= 60:
        try:
            row = live_feature_row(book, history, side, quantity,
                                   int(offset_seconds))
            values = predict_with_models(models, [row])
            prediction = {name: float(vector[0]) for name, vector in values.items()}
        except (ValueError, KeyError, IndexError):
            prediction = None

    if prediction is None:
        adverse_bps = 0.0
        cost_bps = float(immediate['price_cost_bps'])
        vol_bps = current_vol * math.sqrt(max(1, offset_seconds) / 60)
        forecast_name = 'persistence fallback; ML unavailable or out of support'
    else:
        horizon = min(60, max(10, int(offset_seconds)))
        baseline = dict(adverse_mid_bps=0.0,
                        future_execution_cost_bps=float(immediate['price_cost_bps']),
                        future_volatility_bps=current_vol * math.sqrt(horizon / 60))
        baseline.update(prediction)
        adverse_bps = baseline['adverse_mid_bps']
        cost_bps = baseline['future_execution_cost_bps']
        vol_bps = max(0.0, baseline['future_volatility_bps'])
        forecast_name = 'frozen conditional model with per-target persistence fallback'
    _, asks = validate_book(book)
    bids, _ = validate_book(book)
    mid = float((bids[0][0] + asks[0][0]) / 2)
    projected_vwap = mid * (1 + sign * adverse_bps / 10000) * (1 + sign * cost_bps / 10000)
    gross = quantity * projected_vwap
    fee = gross * fee_bps / 10000
    net = gross + fee if side == 'buy' else gross - fee
    risk_penalty = quantity * mid * vol_bps / 10000 * risk_aversion
    return net * sign + risk_penalty, dict(feasible=True, forecast=forecast_name,
        adverse_mid_bps=adverse_bps, execution_cost_bps=cost_bps, volatility_bps=vol_bps,
        projected_vwap=projected_vwap, estimated_net_quote=net,
        risk_penalty_quote=risk_penalty, offset_seconds=offset_seconds)


def _plan(book: dict, history: pd.DataFrame, side: str, remaining_units: int,
          quantity_step: float, fee_bps: float, slots_left: int, interval_seconds: int,
          max_child_units: int, risk_aversion: float, models: dict | None) -> dict:
    """枚举每时段整数数量动作，反向动态规划：剩余量为状态，阶段成本加后续最优值；终端必须完成。返回首步、计划和预测目标；同目标优先早执行，不代表市场全局最优。

    输入参数：book、history、side、remaining_units、quantity_step、fee_bps、slots_left、interval_seconds、max_child_units、risk_aversion、models（单位和范围由下方校验及调用方契约限定）。"""
    if remaining_units <= 0:
        return dict(status='complete', first_action_units=0, schedule=[], estimated_objective_quote=0.0)
    stage_costs: list[dict[int, tuple[float, dict]]] = []
    for stage in range(slots_left):
        offset = stage * interval_seconds
        costs = {}
        for units in range(min(remaining_units, max_child_units) + 1):
            if units == 0:
                costs[0] = (0.0, {'feasible': True, 'forecast': 'wait', 'offset_seconds': offset})
                continue
            costs[units] = _expected_action_cost(book, history, side, units * quantity_step,
                                                 fee_bps, offset, risk_aversion, models)
        stage_costs.append(costs)
    # Backward finite-horizon dynamic programming. The final slot must complete
    # the parent quantity; non-completion is never rewarded as lower cost.
    values: dict[int, tuple[float, list[int]]] = {0: (0.0, [])}
    for stage in range(slots_left - 1, -1, -1):
        updated = {}
        for remaining in range(remaining_units + 1):
            best = (math.inf, None)
            max_action = min(remaining, max_child_units)
            for action in range(max_action, -1, -1):
                rest = remaining - action
                tail = values.get(rest)
                if tail is None:
                    continue
                action_cost = stage_costs[stage][action][0]
                total = action_cost + tail[0]
                if total < best[0]:
                    best = (total, [action, *tail[1]])
            if best[1] is not None:
                updated[remaining] = best
        values = updated
    if remaining_units not in values:
        return dict(status='infeasible', first_action_units=0, schedule=[],
                    estimated_objective_quote=None,
                    reason='Deadline, visible child depth, or per-step cap cannot complete this quantity under the forecast model.')
    objective, schedule = values[remaining_units]
    selected = []
    for stage, units in enumerate(schedule):
        selected.append(dict(slot=stage, offset_seconds=stage * interval_seconds,
                             quantity=units * quantity_step,
                             forecast=stage_costs[stage][units][1]))
    return dict(status='planned', first_action_units=schedule[0], schedule=selected,
                estimated_objective_quote=objective)


def _execute_child(book: dict, side: str, requested: float, fee_bps: float,
                   step: float, quote_balance: float, base_balance: float) -> dict:
    """把单个 Bybit 子单交给静态吃单计算，按当前 USDC/ETH 余额限额执行；返回真实模拟成交量、金额、费用和逐档明细。

    输入参数：book、side、requested、fee_bps、step、quote_balance、base_balance（单位和范围由下方校验及调用方契约限定）。"""
    balances = ({'bybit': str(max(0.0, quote_balance))} if side == 'buy'
                else {'bybit': str(max(0.0, base_balance))})
    result = optimize_static_route({'bybit': book}, side, 'base_quantity',
                                   str(Decimal(str(requested)).quantize(Decimal('0.00000001'))),
                                   {'bybit': fee_bps}, str(step),
                                   quote_balances=balances if side == 'buy' else None,
                                   base_balances=balances if side == 'sell' else None)
    allocation = result['allocation']['bybit']
    return dict(requested=requested, filled=float(allocation['base']),
                gross_quote=float(allocation['gross_quote']), fee_quote=float(allocation['fee_quote']),
                net_quote=float(allocation['net_quote']), fills=result['fills'],
                status=result['status'])


def _run_replay(books: pd.DataFrame, *, start_at: float, side: str, quantity: float,
                quantity_step: float, horizon_seconds: int, interval_seconds: int,
                fee_bps: float, latency_ms: int, max_book_age_ms: int,
                quote_balance: float, base_balance: float, policy: str,
                models: dict | None = None, max_child_units: int | None = None,
                risk_aversion: float = 0.0, cancelled=None, progress=None) -> dict:
    """按时间推进决策，仅把当前簿和过去价格传给规划器；到达时重新取簿成交，扣自有深度和更新余额。三个策略遵守同一子单上限，完成或截止后汇总。

    输入参数：books、start_at、side、quantity、quantity_step、horizon_seconds、interval_seconds、fee_bps、latency_ms、max_book_age_ms、quote_balance、base_balance、policy、models、max_child_units、risk_aversion（单位和范围由下方校验及调用方契约限定）。"""
    total_units = int((Decimal(str(quantity)) / Decimal(str(quantity_step))).to_integral_value())
    slots = horizon_seconds // interval_seconds
    remaining = total_units
    quote_left, base_left = quote_balance, base_balance
    fills, decisions = [], []
    filled_units = 0
    depth = DepthConsumption()
    for index in range(slots):
        if cancelled is not None and cancelled.is_set():raise InterruptedError('MPC replay cancelled')
        if progress:progress(dict(stage='replay',completed=index,total=slots))
        decision_at = start_at + index * interval_seconds
        book = _at(books, decision_at, max_book_age_ms)
        book = depth.available(book) if book else None
        history = _history_asof(books, decision_at)
        if policy == 'mpc':
            if book is None:
                plan = dict(status='infeasible', first_action_units=0, schedule=[],
                            reason='No fresh causal book is available at this decision point.')
            else:
                plan = _plan(book, history, side, remaining, quantity_step, fee_bps,
                             slots - index, interval_seconds,
                             max_child_units or total_units, risk_aversion, models)
            action_units = plan.get('first_action_units', 0)
        elif policy == 'immediate':
            plan = {'status': 'baseline', 'schedule': []}
            action_units = min(remaining, max_child_units or total_units)
        else:  # equal-slice baseline, rebalanced for any earlier partial fill
            plan = {'status': 'baseline', 'schedule': []}
            slots_after = slots - index
            action_units = min(max_child_units or total_units, math.ceil(remaining / slots_after) if slots_after else remaining)
        decision = dict(index=index, decision_at_utc=datetime.fromtimestamp(decision_at, timezone.utc).isoformat(),
                        available_book_at=book.get('available_at') if book else None,
                        action_units=action_units, planned_quantity=action_units * quantity_step,
                        plan=plan)
        if action_units > 0 and remaining > 0:
            arrival = decision_at + latency_ms / 1000
            execution_book = _at(books, arrival, max_book_age_ms)
            execution_book = depth.available(execution_book) if execution_book else None
            if execution_book is None:
                decision['execution_status'] = 'no_fresh_book_at_arrival'
            else:
                requested = min(action_units, remaining) * quantity_step
                child = _execute_child(execution_book, side, requested, fee_bps, quantity_step,
                                       quote_left, base_left)
                actual_units = min(remaining, int((Decimal(str(child['filled'])) /
                                                   Decimal(str(quantity_step))).to_integral_value(rounding=ROUND_FLOOR)))
                child['decision_at_utc'] = decision['decision_at_utc']
                child['execution_at_utc'] = datetime.fromtimestamp(arrival, timezone.utc).isoformat()
                child['book_exchange_ts'] = float(execution_book['exchange_ts'])
                child['side'] = side
                fills.append(child)
                depth.consume(side, child['fills'])
                filled_units += actual_units
                remaining -= actual_units
                if side == 'buy':
                    quote_left -= child['net_quote']
                    base_left += child['filled']
                else:
                    base_left -= child['filled']
                    quote_left += child['net_quote']
                decision['execution_status'] = child['status']
                decision['actual_filled_quantity'] = child['filled']
        decisions.append(decision)
        if remaining <= 0:
            break
    filled = sum(x['filled'] for x in fills)
    gross = sum(x['gross_quote'] for x in fills)
    fee = sum(x['fee_quote'] for x in fills)
    net = gross + fee if side == 'buy' else gross - fee
    # 从实际逐档明细独立重建，而非把运行中的余额变量视为正确答案。
    raw_fills = [level for child in fills for level in child['fills']]
    rebuilt_base = sum((Decimal(x['quantity']) for x in raw_fills), Decimal(0))
    rebuilt_net = sum((Decimal(x['net_quote']) for x in raw_fills), Decimal(0))
    expected_quote = Decimal(str(quote_balance)) + (-rebuilt_net if side == 'buy' else rebuilt_net)
    expected_base = Decimal(str(base_balance)) + (rebuilt_base if side == 'buy' else -rebuilt_base)
    quote_gap = Decimal(str(quote_left)) - expected_quote
    base_gap = Decimal(str(base_left)) - expected_base
    reconciliation = dict(ok=abs(quote_gap) <= Decimal('0.000001') and abs(base_gap) <= Decimal('1e-8')
                          and min(quote_left, base_left) >= -1e-10,
                          quote_gap=str(quote_gap), base_gap=str(base_gap))
    return dict(status='complete' if remaining == 0 else 'partial', requested_quantity=quantity,
                filled_quantity=filled, unfilled_quantity=max(0.0, quantity - filled),
                completion_pct=filled / quantity * 100, gross_quote=gross, fee_quote=fee,
                net_quote=net, average_price=(gross / filled if filled else None),
                ending_quote_balance=quote_left, ending_base_balance=base_left,
                decisions=decisions, fills=fills, reconciliation=reconciliation)


def run_mpc_replay(day: str, utc_time: str, side: str, quantity: str | float,
                   horizon_seconds: int = 60, interval_seconds: int = 10,
                   max_child_pct: float = 50, fee_bps: float = 10,
                   risk_aversion: float = 0.5, quote_balance: float = 5000,
                   base_balance: float = 1, latency_ms: int = 250,
                   max_book_age_ms: int = 1500, quantity_step: str | float = '0.01',
                   model_id: str | None = None, cancelled=None, progress=None) -> dict:
    """校验数量精度、期限、资源上限和数据覆盖；阻止训练截止前使用冻结模型。隔离回放 MPC/尽早/等额方案，保存配置、来源和不可变报告。

    输入参数：day、utc_time、side、quantity、horizon_seconds、interval_seconds、max_child_pct、fee_bps、risk_aversion、quote_balance、base_balance、latency_ms、max_book_age_ms、quantity_step、model_id（单位和范围由下方校验及调用方契约限定）。

    原始实现说明：
    Re-plan from causal Bybit snapshots; execute only each first action."""
    qty, step = Decimal(str(quantity)), Decimal(str(quantity_step))
    if side not in ('buy', 'sell') or qty <= 0 or step <= 0 or qty % step:
        raise ValueError('Choose a positive ETH quantity exactly divisible by the quantity step')
    if horizon_seconds < 10 or horizon_seconds > 300 or interval_seconds < 5 or horizon_seconds % interval_seconds:
        raise ValueError('Horizon must be 10–300s and divisible by the decision interval (at least 5s)')
    if not 0 < max_child_pct <= 100 or not 0 <= risk_aversion <= 5:
        raise ValueError('Child-size cap or risk-aversion setting is outside its supported range')
    if not 0 <= fee_bps <= 1000 or not 0 <= latency_ms <= 5000 or max_book_age_ms < 100:
        raise ValueError('Fee, latency, or freshness limit is outside its supported range')
    if side == 'buy' and quote_balance < 0 or side == 'sell' and base_balance < 0:
        raise ValueError('Starting balances cannot be negative')
    start_dt = datetime.fromisoformat(f'{day}T{utc_time}')
    if start_dt.tzinfo:
        raise ValueError('Enter a UTC time without a timezone suffix')
    start_at = start_dt.replace(tzinfo=timezone.utc).timestamp()
    books = load_bybit_timeline(day, latency_ms)
    models, model_manifest = (load_conditional_model(model_id) if model_id else (None, None))
    if model_manifest:
        validation_cutoff = model_manifest['training'].get('validation_label_end_utc')
        if not validation_cutoff or start_at <= pd.Timestamp(validation_cutoff).timestamp():
            raise ValueError('Frozen model can only be applied after its validation-label cutoff; use persistence fallback for earlier dates.')
    units = int(qty / step)
    if units > 500:
        raise ValueError('At most 500 planning units are supported; increase the quantity step')
    if start_at < float(books.available_at.min()) or start_at + horizon_seconds > float(books.available_at.max()):
        raise ValueError('Execution window must be fully covered by the selected historical day')
    max_child_units = max(1, math.floor(units * max_child_pct / 100))
    optimized = _run_replay(books, start_at=start_at, side=side, quantity=float(qty),
        quantity_step=float(step), horizon_seconds=horizon_seconds, interval_seconds=interval_seconds,
        fee_bps=fee_bps, latency_ms=latency_ms, max_book_age_ms=max_book_age_ms,
        quote_balance=quote_balance, base_balance=base_balance, policy='mpc', models=models,
        max_child_units=max_child_units, risk_aversion=risk_aversion, cancelled=cancelled, progress=progress)
    immediate = _run_replay(books, start_at=start_at, side=side, quantity=float(qty),
        quantity_step=float(step), horizon_seconds=horizon_seconds, interval_seconds=interval_seconds,
        fee_bps=fee_bps, latency_ms=latency_ms, max_book_age_ms=max_book_age_ms,
        quote_balance=quote_balance, base_balance=base_balance, policy='immediate', max_child_units=max_child_units, cancelled=cancelled, progress=progress)
    equal = _run_replay(books, start_at=start_at, side=side, quantity=float(qty),
        quantity_step=float(step), horizon_seconds=horizon_seconds, interval_seconds=interval_seconds,
        fee_bps=fee_bps, latency_ms=latency_ms, max_book_age_ms=max_book_age_ms,
        quote_balance=quote_balance, base_balance=base_balance, policy='equal', max_child_units=max_child_units, cancelled=cancelled, progress=progress)
    run_id = uuid.uuid4().hex
    report = dict(schema_version=2, run_id=run_id, created_at=utcnow(), venue='Bybit',
        symbol='ETHUSDC', day_utc=day, input_start_utc=datetime.fromtimestamp(start_at, timezone.utc).isoformat(),
        config=dict(side=side, quantity=str(qty), quantity_step=str(step), horizon_seconds=horizon_seconds,
                    interval_seconds=interval_seconds, max_child_pct=max_child_pct, fee_bps=fee_bps,
                    risk_aversion=risk_aversion, quote_balance=quote_balance, base_balance=base_balance,
                    latency_ms=latency_ms, max_book_age_ms=max_book_age_ms, model_id=model_id),
        source=dict(path=books.attrs.get('source_path'), sha256=books.attrs.get('source_sha256'),
                    availability_assumption='exchange timestamp + user-selected fixed latency; local receive timestamps are unavailable'),
        model=(dict(model_id=model_manifest['model_id'], selected=model_manifest['selected'],
                    validation_day=model_manifest['training']['validation_day'],
                    validation_cutoff=model_manifest['training']['validation_label_end_utc'])
               if model_manifest else dict(status='persistence fallback; no frozen model selected')),
        results=dict(mpc=optimized, immediate=immediate, equal_slice=equal),
        assumptions=['All policies obey the same per-child cap; immediate means earliest feasible capped execution, not an unrestricted parent sweep.',
                     'Identical unchanged book contents retain own consumed depth; external content changes reset the ledger under an exogenous-market approximation.',
                     'ML is used only for child sizes 0.01–1 ETH and offsets 10–60 seconds; other actions explicitly use persistence.',
                     'MPC plans a short horizon but submits only the first child, then re-reads the market and replans.',
                     'Planner forecasts hold visible depth at the decision snapshot and use conditional ML or persistence fallback.',
                     'Historical executions use later public L2 only when each replay step is reached; those future rows are not passed to its forecast.',
                     'One venue is modeled here. Cross-venue snapshot allocation is available in the static router, but joint multi-venue dynamic MPC is not yet included.',
                     'Counterfactual orders do not alter subsequent public order flow; no market impact or queue probability is inferred.'])
    folder = RUN_ROOT / run_id
    folder.mkdir(parents=True, exist_ok=False)
    dump(folder / 'report.json', report)
    report['report_path'] = str(folder / 'report.json')
    log('mpc_execution_replay_completed', run_id=run_id, day=day, side=side,
        requested_quantity=str(qty), model_id=model_id, status=optimized['status'])
    return report
