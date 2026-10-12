"""P4：事前有限候选选择，事后按队列情景回放撤改与主动补单。"""
from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR
import json
import uuid
import pandas as pd

from .execution import validate_book
from .io import ROOT, dump, sha, code_hash, utcnow, log
from .mpc import _at, _execute_child
from .passive import simulate_passive_limit, load_bybit_passive_day
from .experiment_engine import _bytes, DATA_CAP

RUN_ROOT = ROOT / 'data' / 'experiments' / 'limit_optimizer' / 'runs'
D = Decimal


def _limit(book, side, offset_ticks, tick):
    """从当前可知最优同侧报价向外偏移整数 tick，生成不会主动穿价的候选限价。"""
    bids, asks = validate_book(book)
    anchor = bids[0][0] if side == 'buy' else asks[0][0]
    price = anchor + (D(-1) if side == 'buy' else D(1)) * D(offset_ticks) * tick
    if price <= 0 or price % tick:
        raise ValueError('Candidate limit is nonpositive or incompatible with the price tick')
    return price


def choose_limit_plan(book, past_trades, *, decision_at, side, quantity, wait_seconds,
                      offsets, maker_bps, taker_bps, tick, risk_weight, quote_balance,
                      base_balance, quantity_step):
    """只用决策前一分钟成交和当前盘口评分；未来成交绝不参与候选选择。

    成交量外推仅是启发式情景，不是已校准概率：全队列/半队列/零队列三种假设。
    以三种估计中的最差成本为目标，等待风险为过去收益标准差乘时间平方根。
    立即成交也是候选；有限集合枚举最优不等于真实市场全局最优。
    """
    q = D(str(quantity))
    immediate = _execute_child(book, side, float(q), float(taker_bps), float(quantity_step),
                               quote_balance, base_balance)
    if immediate['filled'] + 1e-10 < float(q):
        raise ValueError('Current visible depth or starting funds cannot complete the parent order')
    sign = 1 if side == 'buy' else -1
    bids, asks = validate_book(book)
    mid = float((bids[0][0] + asks[0][0]) / 2)
    recent = past_trades[(past_trades.available_at > decision_at - 60) &
                         (past_trades.available_at <= decision_at)].copy()
    if 'rpi' in recent:
        recent = recent[recent.rpi.fillna(0).astype(int) == 0]
    prices = recent.sort_values('available_at').price.astype(float)
    returns = prices.pct_change(fill_method=None).dropna()
    vol = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
    candidates = [dict(kind='immediate', wait_seconds=0, offset_ticks=0, amend=False,
                       estimated_objective=sign * immediate['net_quote'], estimated_fill_range=[float(q)] * 3)]
    for wait in wait_seconds:
        for offset in offsets:
            price = _limit(book, side, offset, tick)
            levels = bids if side == 'buy' else asks
            queue = next((size for p, size in levels if p == price), D(0))
            aggressive = recent[recent.side.str.lower() == ('sell' if side == 'buy' else 'buy')]
            exact = aggressive[aggressive.price.astype(float) == float(price)]
            crossing = aggressive[aggressive.price.astype(float) <= float(price)] if side == 'buy' else aggressive[aggressive.price.astype(float) >= float(price)]
            volumes = [D(str(exact.volume.astype(float).sum())) * D(wait) / 60,
                       D(str(crossing.volume.astype(float).sum())) * D(wait) / 60]
            expected = [min(q, max(D(0), volumes[0] - queue)),
                        min(q, max(D(0), volumes[1] - queue / 2)), min(q, volumes[1])]
            maker_unit = price * (1 + D(str(maker_bps)) / 10000 if side == 'buy' else 1 - D(str(maker_bps)) / 10000)
            taker_unit = D(str(immediate['net_quote'])) / q
            penalty = float(q) * mid * vol * (wait / 60) ** 0.5 * risk_weight
            worst = max(sign * float(f * maker_unit + (q-f) * taker_unit) for f in expected)
            # 撤改价格不可预先看到：预测按初始价持平；重排队的不确定性额外披露。
            for amend in (False, True):
                candidates.append(dict(kind='passive_then_taker', wait_seconds=wait,
                    offset_ticks=offset, amend=amend, initial_limit=str(price),
                    estimated_objective=worst + penalty,
                    estimated_fill_range=[float(x) for x in expected], risk_penalty=penalty))
    # 目标相同则优先立即；其次不撤改和较短等待，避免无理由的额外操作。
    selected = min(candidates, key=lambda c: (c['estimated_objective'], c['wait_seconds'], c['amend']))
    return dict(selected=selected, candidates=candidates, past_trade_count=len(recent),
                latest_feature_at=float(recent.available_at.max()) if len(recent) else None,
                method='finite candidate enumeration; worst of three heuristic queue estimates',
                optimality='best in the declared finite forecast candidate set, not market-global optimal')


def replay_limit_plan(books, trades, plan, *, decision_at, side, quantity, maker_bps,
                      taker_bps, tick, quantity_step, quote_balance, base_balance,
                      latency_ms, cancel_latency_ms, max_book_age_ms, scenario):
    """执行已选方案：挂单→可选撤改→撤单确认→补单；完整轨迹只供事后核验。

    撤单延迟内成交仍计入，确认后才释放余量并发主动单；每段交易窗口不重叠。
    每次改价只读取改价时可知盘口，剩余数量和资金随成交更新，不允许负余额。
    """
    remaining = D(str(quantity)); quote = D(str(quote_balance)); base = D(str(base_balance))
    fills, events = [], []
    start = float(decision_at)
    order_delay, cancel_delay = latency_ms / 1000, cancel_latency_ms / 1000
    active_at = start
    wait = plan['wait_seconds']
    if plan['kind'] != 'immediate':
        segments = [wait / 2, wait / 2] if plan['amend'] else [wait]
        for index, duration in enumerate(segments):
            if remaining <= 0:
                break
            known = _at(books, start, max_book_age_ms)
            if known is None:
                events.append(dict(at=start, status='no_fresh_book_for_limit'))
                active_at = start
                break
            price = _limit(known, side, plan['offset_ticks'], tick)
            arrival = start + order_delay
            cancel_request = arrival + duration
            cancel_ack = cancel_request + cancel_delay
            events.extend([dict(at=start, status='submit_limit', price=str(price), quantity=str(remaining)),
                           dict(at=cancel_request, status='cancel_requested'), dict(at=cancel_ack, status='cancel_confirmed')])
            try:
                simulation = simulate_passive_limit(books, trades, decision_at=start, side=side,
                    quantity=str(remaining), limit_price=str(price), horizon_seconds=duration+cancel_delay,
                    cancel_after_seconds=None, price_tick=str(tick), latency_ms=latency_ms,
                    max_book_age_ms=max_book_age_ms)
                # 模拟器仅消费撤单确认前的成交；更晚数据不得影响此段累计结果。
                selected = next(x for x in simulation['scenarios'] if x['name'] == scenario)
                eligible = [x for x in selected['fill_events'] if x['available_at'] <= cancel_ack]
                maker_unit = price * (1 + D(str(maker_bps))/10000)
                for fill in eligible:
                    qty = min(remaining, D(fill['quantity']))
                    affordable = quote / maker_unit if side == 'buy' else base
                    qty = min(qty, affordable)
                    qty = (qty / quantity_step).to_integral_value(rounding=ROUND_FLOOR) * quantity_step
                    if qty <= 0:
                        continue
                    gross = qty * price; fee = gross * D(str(maker_bps)) / 10000
                    net = gross + fee if side == 'buy' else gross - fee
                    quote += -net if side == 'buy' else net
                    base += qty if side == 'buy' else -qty
                    remaining -= qty
                    fills.append(dict(kind='maker', at=fill['available_at'], quantity=str(qty),
                                      price=str(price), gross_quote=str(gross), fee_quote=str(fee), net_quote=str(net)))
            except ValueError as exc:
                events.append(dict(at=arrival, status='passive_rejected', reason=str(exc)))
            active_at = cancel_ack
            start = cancel_ack  # 改价订单必须在旧单确认取消后才能发出。
    if remaining > 0:
        arrival = active_at + order_delay
        book = _at(books, arrival, max_book_age_ms)
        if book:
            child = _execute_child(book, side, float(remaining), float(taker_bps),
                                   float(quantity_step), float(quote), float(base))
            for fill in child['fills']:
                fills.append(dict(kind='taker', at=arrival, **fill))
            remaining -= D(str(child['filled']))
            quote += -D(str(child['net_quote'])) if side == 'buy' else D(str(child['net_quote']))
            base += D(str(child['filled'])) if side == 'buy' else -D(str(child['filled']))
        else:
            events.append(dict(at=arrival, status='no_fresh_book_for_completion'))
    # 独立重算现金与资产流，不复用逐段更新逻辑，检查漏记费用和方向符号。
    filled = sum((D(x['quantity']) for x in fills), D(0))
    gross = sum((D(x['gross_quote']) for x in fills), D(0))
    fees = sum((D(x['fee_quote']) for x in fills), D(0))
    net = gross + fees if side == 'buy' else gross - fees
    expected_quote = D(str(quote_balance)) + (-net if side == 'buy' else net)
    expected_base = D(str(base_balance)) + (filled if side == 'buy' else -filled)
    audit = dict(ok=abs(quote - expected_quote) < D('0.000001') and abs(base - expected_base) < D('1e-8') and min(quote, base) >= 0,
                 quote_gap=str(quote - expected_quote), base_gap=str(base - expected_base))
    return dict(status='complete' if remaining < quantity_step / 2 else 'partial', scenario=scenario,
        filled_quantity=str(filled), unfilled_quantity=str(max(D(0), remaining)),
        gross_quote=str(gross), fee_quote=str(fees), net_quote=str(net),
        completion_pct=float(filled / D(str(quantity)) * 100), ending_quote=str(quote), ending_base=str(base),
        execution_seconds=max((x['at'] for x in fills), default=decision_at)-decision_at,
        reconciliation=audit, fills=fills, events=events)


def run_limit_optimization(day, utc_time, side, quantity, waits=(10, 30), offsets=(0, 1, 2),
                           maker_bps=2, taker_bps=10, risk_weight=0.5, tick='0.01',
                           quantity_step='0.00000001', quote_balance=5000, base_balance=1,
                           latency_ms=250, cancel_latency_ms=250, max_book_age_ms=3000,
                           reference_plan=None):
    """看板服务入口：校验参数→读同日簿/成交→事前选方案→三情景回放→保存不可变报告。

    day/utc_time 是 UTC 日期和墙上时间；quantity/quantity_step 是 ETH，tick 是 USDC/ETH。
    waits 为挂单实际等待秒数，撤改后的累计下单与确认延迟另计；fees 用 bps，10bps=0.1%。
    reference_plan 是用户原方案，必须属于同一候选集合，只参与事后对比，不影响选择。
    返回配置、因果选型依据、成交和撤改轨迹、独立对账；失败、缺量和存储超限不得隐藏。
    """
    q, step, price_tick = D(str(quantity)), D(str(quantity_step)), D(str(tick))
    if side not in ('buy', 'sell') or not all(x.is_finite() and x > 0 for x in (q, step, price_tick)) or q % step:
        raise ValueError('Invalid side, quantity, quantity step or tick')
    if not waits or len(waits)>6 or any(not isinstance(w,int) or w<2 or w>300 for w in waits):
        raise ValueError('Use up to six waiting candidates, each 2–300 seconds')
    if not offsets or len(offsets)>5 or any(not isinstance(o,int) or o<0 or o>100 for o in offsets):
        raise ValueError('Use up to five nonnegative integer tick offsets')
    if not 0<=maker_bps<=100 or not 0<=taker_bps<=100 or not 0<=risk_weight<=5:
        raise ValueError('Fees or risk weight outside supported range')
    if not 0<=latency_ms<=5000 or not 0<=cancel_latency_ms<=5000 or max_book_age_ms<1 or min(quote_balance,base_balance)<0:
        raise ValueError('Invalid latency, freshness or starting balance')
    start = pd.Timestamp(f'{day}T{utc_time}', tz='UTC').timestamp()
    books, trades = load_bybit_passive_day(day)
    # 同一延迟假设同时应用于盘口和成交；不能混用旧缓存中的默认 250ms。
    books['available_at'] = books.exchange_ts.astype(float) + latency_ms/1000
    trades['available_at'] = trades.available_at.astype(float) - 0.250 + latency_ms/1000
    latest_end = start + max(waits) + 3*latency_ms/1000 + 2*cancel_latency_ms/1000
    if start-60 < max(books.available_at.min(),trades.available_at.min()) or latest_end > min(books.available_at.max(),trades.available_at.max()):
        raise ValueError('History must cover the previous minute and the full waiting/cancellation/completion window')
    current = _at(books,start,max_book_age_ms)
    if current is None:
        raise ValueError('No fresh causal book at decision time')
    past = trades[(trades.available_at<=start)&(trades.available_at>start-60)]
    selection = choose_limit_plan(current,past,decision_at=start,side=side,quantity=str(q),
        wait_seconds=waits,offsets=offsets,maker_bps=maker_bps,taker_bps=taker_bps,tick=price_tick,
        risk_weight=risk_weight,quote_balance=quote_balance,base_balance=base_balance,quantity_step=step)
    replay_args=dict(decision_at=start,side=side,quantity=str(q),maker_bps=maker_bps,taker_bps=taker_bps,
        tick=price_tick,quantity_step=step,quote_balance=quote_balance,base_balance=base_balance,
        latency_ms=latency_ms,cancel_latency_ms=cancel_latency_ms,max_book_age_ms=max_book_age_ms)
    results={name:replay_limit_plan(books,trades,selection['selected'],scenario=name,**replay_args)
             for name in ('conservative','middle','optimistic')}
    baseline=replay_limit_plan(books,trades,dict(kind='immediate',wait_seconds=0),scenario='conservative',**replay_args)
    reference_results = None
    if reference_plan is not None:
        matches = [c for c in selection['candidates'] if all(c.get(k) == reference_plan.get(k)
                   for k in ('kind', 'wait_seconds', 'offset_ticks', 'amend'))]
        if not matches:
            raise ValueError('Reference plan must belong to the declared candidate set')
        reference_results = {name: replay_limit_plan(books,trades,matches[0],scenario=name,**replay_args)
                             for name in ('conservative','middle','optimistic')}
    run_id=uuid.uuid4().hex
    report=dict(schema_version=1,run_id=run_id,created_at=utcnow(),config=dict(day=day,utc_time=utc_time,
        side=side,quantity=str(q),waits=list(waits),offsets=list(offsets),maker_bps=maker_bps,taker_bps=taker_bps,
        risk_weight=risk_weight,tick=str(price_tick),quantity_step=str(step),quote_balance=quote_balance,
        base_balance=base_balance,latency_ms=latency_ms,cancel_latency_ms=cancel_latency_ms,max_book_age_ms=max_book_age_ms,
        reference_plan=reference_plan),
        selection=selection,results=results,reference_results=reference_results,immediate_baseline=baseline,code_sha256=code_hash(),
        data_sha256=dict(books=sha(ROOT/'data'/'historical'/f'{day}.books.parquet') if (ROOT/'data'/'historical'/f'{day}.books.parquet').exists() else sha(ROOT/'data'/'experiments'/'market'/'bybit'/'ETHUSDC'/day/'books.parquet'),
                         trades=sha(ROOT/'data'/'historical'/'trades'/f'{day}.trades.parquet')),
        assumptions=['Only Bybit ETHUSDC fixed-base quantity; no DEX or cross-venue passive routing.',
          'Selection uses only current book and prior one-minute trade volume; no future-based best-plan selection.',
          'Queue ranges and constant-rate forecasts are heuristic assumptions, not calibrated probabilities.',
          'Cancellation is confirmed before replacement or taker completion; cancellation latency fills count.',
          'Full completion is attempted, not guaranteed; insufficient funds, stale quotes and residual quantities are reported.',
          'Own maker order has no feedback on historical market; an amendment resets its queue.',
          'Conditional ML is not used in this S3 heuristic; the MPC page retains frozen ML capability.'])
    if _bytes(ROOT/'data')+5_000_000>DATA_CAP:
        raise ValueError('Insufficient global data budget for the experiment report')
    folder=RUN_ROOT/run_id;folder.mkdir(parents=True,exist_ok=False)
    dump(folder/'report.json',report);report['report_path']=str(folder/'report.json')
    log('limit_optimization_completed',run_id=run_id,selected=selection['selected'],reconciled=all(x['reconciliation']['ok'] for x in results.values()))
    return report
