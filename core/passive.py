"""组件用途：检查限价是否为价格最小跳动的整数倍，不通过舍入偷偷改变用户限价。；在订单到达时取可见盘口并检查非主动穿价；通过反向主动成交量推进三种假设队列，输出成交轨迹及未成交量。触价不等于成交，结果不是真实成交概率。。

原始说明：Historical passive-limit scenarios bounded by public L2 and trade prints."""
from __future__ import annotations

from decimal import Decimal

import pandas as pd

from .execution import validate_book
from .io import ROOT
from .experiment_engine import _resolve_book

D = Decimal
HIST = ROOT / 'data' / 'historical'


def _is_tick_multiple(price: D, tick: D) -> bool:
    """检查限价是否为价格最小跳动的整数倍，不通过舍入偷偷改变用户限价。

    输入参数：price、tick（单位和范围由下方校验及调用方契约限定）。"""
    return (price / tick) == (price / tick).to_integral_value()


def simulate_passive_limit(books: pd.DataFrame, trades: pd.DataFrame, *,
                           decision_at: float, side: str, quantity: str | float,
                           limit_price: str | float, horizon_seconds: int,
                           price_tick: str | float = '0.01', latency_ms: int = 250,
                           max_book_age_ms: int = 3000,
                           cancel_after_seconds: int | None = None) -> dict:
    """在订单到达时取可见盘口并检查非主动穿价；通过反向主动成交量推进三种假设队列，输出成交轨迹及未成交量。触价不等于成交，结果不是真实成交概率。

    输入参数：books、trades、decision_at、side、quantity、limit_price、horizon_seconds、price_tick、latency_ms、max_book_age_ms、cancel_after_seconds（单位和范围由下方校验及调用方契约限定）。

    原始实现说明：
    Return strict/central/optimistic fills; never convert touch into a fill.
    
        Strict assumes every displayed unit at the limit is ahead and only prints at
        exactly that price advance the queue. The optimistic bound assumes no queue
        ahead and credits trade-through volume. Neither is a calibrated fill probability."""
    qty, price, tick = D(str(quantity)), D(str(limit_price)), D(str(price_tick))
    if side not in ('buy', 'sell') or qty <= 0 or price <= 0 or tick <= 0:
        raise ValueError('Side, quantity, price or tick is invalid')
    if horizon_seconds < 1 or horizon_seconds > 86400:
        raise ValueError('Passive order horizon must be between one second and one day')
    if not 0 <= latency_ms <= 5000 or max_book_age_ms < 1:
        raise ValueError('Invalid latency or maximum book age')
    if not _is_tick_multiple(price, tick):
        raise ValueError('Limit price must be a multiple of the selected price tick')
    if books.empty or trades.empty:
        raise ValueError('Both historical L2 and trade prints are required')
    if 'available_at' not in books or 'available_at' not in trades:
        raise ValueError('Inputs must include causal available_at timestamps')

    arrival = float(decision_at) + latency_ms / 1000
    ordered_books = books.sort_values('available_at')
    observed = ordered_books[ordered_books.available_at <= arrival]
    if observed.empty:
        raise ValueError('No book was available at or before order arrival')
    book = observed.iloc[-1].to_dict()
    age_ms = (arrival - float(book['available_at'])) * 1000
    if age_ms > max_book_age_ms:
        raise ValueError('Book is stale at order arrival; no queue estimate is reported')
    bids, asks = validate_book(book)
    best_bid, best_ask = bids[0][0], asks[0][0]
    if (side == 'buy' and price >= best_ask) or (side == 'sell' and price <= best_bid):
        raise ValueError('Limit would be marketable at arrival; this module only models passive orders')
    same_side = bids if side == 'buy' else asks
    queue_ahead = next((size for level_price, size in same_side if level_price == price), D(0))

    horizon_end = arrival + horizon_seconds
    if cancel_after_seconds is not None:
        if cancel_after_seconds < 1 or cancel_after_seconds > horizon_seconds:
            raise ValueError('Cancel timer must be within the selected order horizon')
        cancel_at = arrival + cancel_after_seconds
        end_at = min(horizon_end, cancel_at)
        end_reason = 'user_cancel_timer' if cancel_at <= horizon_end else 'expiry'
    else:
        end_at, end_reason = horizon_end, 'expiry'
    available_trades = trades[(trades.available_at > arrival) & (trades.available_at <= end_at)].copy()
    if 'rpi' in available_trades:
        available_trades = available_trades[available_trades.rpi.fillna(0).astype(int) == 0]
    available_trades = available_trades.sort_values('available_at')

    def run_scenario(name: str, ahead: D, allow_trade_through: bool) -> dict:
        """按时间累积符合方向和价格条件的主动成交，先扣前方队列再计自身成交，记录每笔新增量并在完成时停止。

        输入参数：name、ahead、allow_trade_through（单位和范围由下方校验及调用方契约限定）。"""
        eligible_volume = D(0)
        fill = D(0)
        first_fill_at = None
        fill_events = []
        for trade in available_trades.itertuples(index=False):
            trade_side = str(trade.side).lower()
            trade_price = D(str(trade.price))
            aggressive = (trade_side == 'sell' if side == 'buy' else trade_side == 'buy')
            crosses = trade_price <= price if side == 'buy' else trade_price >= price
            exact = trade_price == price
            if not aggressive or not crosses or (not allow_trade_through and not exact):
                continue
            before = eligible_volume
            eligible_volume += D(str(trade.volume))
            newly_available = max(D(0), eligible_volume - ahead) - max(D(0), before - ahead)
            if newly_available > 0 and first_fill_at is None:
                first_fill_at = float(trade.available_at)
            next_fill = min(qty, max(D(0), eligible_volume - ahead))
            if next_fill > fill:
                fill_events.append(dict(available_at=float(trade.available_at),
                                        quantity=str(next_fill - fill), price=str(price)))
            fill = next_fill
            if fill >= qty:
                break
        return dict(name=name, queue_ahead=str(ahead), eligible_aggressor_volume=str(eligible_volume),
                    filled_quantity=str(fill), unfilled_quantity=str(qty - fill),
                    completion_pct=float(fill / qty * 100),
                    fill_events=fill_events,
                    estimated_fill_at=(pd.Timestamp(first_fill_at, unit='s', tz='UTC').isoformat()
                                       if first_fill_at is not None else None),
                    fill_at_limit_quote=str(fill * price))

    scenarios = [run_scenario('conservative', queue_ahead, False),
                 run_scenario('middle', queue_ahead / 2, True),
                 run_scenario('optimistic', D(0), True)]
    return dict(status='scenario_range', venue='Bybit', side=side,
                decision_at_utc=pd.Timestamp(decision_at, unit='s', tz='UTC').isoformat(),
                order_arrival_at_utc=pd.Timestamp(arrival, unit='s', tz='UTC').isoformat(),
                end_at_utc=pd.Timestamp(end_at, unit='s', tz='UTC').isoformat(),
                end_reason=end_reason, requested_quantity=str(qty), limit_price=str(price),
                price_tick=str(tick), initial_best_bid=str(best_bid), initial_best_ask=str(best_ask),
                initial_queue_ahead=str(queue_ahead), book_age_ms=age_ms,
                eligible_trade_count=len(available_trades), scenarios=scenarios,
                limitations=['L2 does not reveal order identity, exact queue order, or cancellations ahead.',
                             'A historical replay is counterfactual; the simulated order did not change public depth or subsequent order flow.',
                             'Scenario endpoints are assumptions, not statistically calibrated fill probabilities.',
                             'No maker fee/rebate is assumed; add the actual account fee outside this fill-only model.'])


def load_bybit_passive_day(day: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """按日期读取 Bybit 同日盘口和成交 Parquet，任一文件缺失直接拒绝；不把只有成交数据的场所冒充有盘口。

    输入参数：day（单位和范围由下方校验及调用方契约限定）。"""
    day = str(day)
    books_path, _ = _resolve_book(day, 'bybit')
    trades_path = HIST / 'trades' / f'{day}.trades.parquet'
    if not books_path.exists() or not trades_path.exists():
        raise FileNotFoundError(f'Bybit L2 and trade history are both required for {day}')
    return (pd.read_parquet(books_path, columns=['available_at', 'exchange_ts', 'bids_json', 'asks_json']),
            pd.read_parquet(trades_path, columns=['available_at', 'price', 'volume', 'side', 'rpi']))
