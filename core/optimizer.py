"""组件用途：读取经哈希校验的 Bybit/OKX 同日盘口，根据事件时间加假设延迟向后查找并拒绝陈旧簿；返回两所快照和时序审计。；取得因果双所快照后调用静态分配，将配置、数据依据和结果保存到新的不可变实验目录。。

原始说明：Snapshot routing and causal market-view helpers used by dashboard solvers."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .cross_venue import _book_path
from .io import ROOT, dump, utcnow
from .solver import optimize_static_route

RUN_ROOT = ROOT / 'data' / 'experiments' / 'optimizer' / 'runs'


def causal_snapshot(day: str, utc_time: str, latency_ms: int = 250,
                    max_age_ms: int = 1500) -> tuple[dict, dict]:
    """读取经哈希校验的 Bybit/OKX 同日盘口，根据事件时间加假设延迟向后查找并拒绝陈旧簿；返回两所快照和时序审计。

    输入参数：day、utc_time、latency_ms、max_age_ms（单位和范围由下方校验及调用方契约限定）。

    原始实现说明：
    Return latest already-available Bybit/OKX books at a selected UTC instant."""
    if not 0 <= latency_ms <= 5000 or max_age_ms < 1:
        raise ValueError('Latency or maximum book age is invalid')
    naive = datetime.fromisoformat(f'{day}T{utc_time}')
    if naive.tzinfo is not None:
        raise ValueError('Enter a UTC wall-clock time without a timezone suffix')
    evaluation_at = naive.replace(tzinfo=timezone.utc).timestamp() + latency_ms / 1000
    books, audit = {}, {}
    for venue in ('bybit', 'okx'):
        path, manifest = _book_path(venue, day)
        frame = pd.read_parquet(path, columns=['exchange_ts', 'bids_json', 'asks_json'])
        # Apply the explicit event-to-available assumption uniformly. It is not
        # a measured local receive timestamp.
        frame['available_at'] = frame.exchange_ts.astype('float64') + latency_ms / 1000
        frame = frame[frame.available_at <= evaluation_at].sort_values('available_at')
        if frame.empty:
            raise ValueError(f'No {venue} book was available at the selected UTC time')
        row = frame.iloc[-1]
        age_ms = (evaluation_at - float(row.available_at)) * 1000
        if age_ms > max_age_ms:
            raise ValueError(f'{venue} book is stale at selected time ({age_ms:.0f} ms)')
        books[venue] = dict(bids_json=row.bids_json, asks_json=row.asks_json)
        audit[venue] = dict(exchange_ts=float(row.exchange_ts), available_at=float(row.available_at),
                            age_ms=age_ms, archive_sha256=manifest.get('archive_sha256'),
                            books_sha256=manifest.get('books_sha256'))
    return books, dict(day_utc=day, evaluation_at=evaluation_at,
                       evaluation_at_utc=datetime.fromtimestamp(evaluation_at, timezone.utc).isoformat(),
                       assumed_latency_ms=latency_ms, max_age_ms=max_age_ms,
                       local_receive_time_measured=False, books=audit)


def run_static_snapshot(day: str, utc_time: str, side: str, amount_mode: str,
                        amount: str | float, fees_bps: dict,
                        quantity_step: str | float = '0.00000001',
                        quote_balances: dict | None = None,
                        base_balances: dict | None = None,
                        latency_ms: int = 250, max_age_ms: int = 1500) -> dict:
    """取得因果双所快照后调用静态分配，将配置、数据依据和结果保存到新的不可变实验目录。

    输入参数：day、utc_time、side、amount_mode、amount、fees_bps、quantity_step、quote_balances、base_balances、latency_ms、max_age_ms（单位和范围由下方校验及调用方契约限定）。"""
    books, data_audit = causal_snapshot(day, utc_time, latency_ms, max_age_ms)
    result = optimize_static_route(books, side, amount_mode, amount, fees_bps,
                                   quantity_step, quote_balances, base_balances)
    run_id = uuid.uuid4().hex
    folder = RUN_ROOT / run_id
    folder.mkdir(parents=True, exist_ok=False)
    report = dict(schema_version=1, run_id=run_id, created_at=utcnow(),
                  objective=('maximize net ETH under quote budget' if amount_mode == 'quote_budget'
                              else 'minimize all-in quote outlay for fixed ETH amount' if side == 'buy'
                              else 'maximize net quote proceeds for fixed ETH amount'),
                  data=data_audit, config=dict(day=day, utc_time=utc_time, side=side,
                                               amount_mode=amount_mode, amount=str(amount),
                                               fees_bps={k: str(v) for k, v in fees_bps.items()},
                                               quantity_step=str(quantity_step),
                                               quote_balances=quote_balances or {},
                                               base_balances=base_balances or {}),
                  result=result)
    dump(folder / 'report.json', report)
    report['report_path'] = str(folder / 'report.json')
    return report
