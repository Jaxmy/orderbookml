"""组件用途：统计现有数据总大小，过滤并发消失文件，用于规范化和存储预留。；流式读取官方 tar.gz 内唯一数据流，应用快照和增量并检验有效盘口，保存每秒首个前二十档；假设接收延迟明确记录而非实测。。

原始说明：Normalize OKX's public historical L2 archive into the project's causal book schema."""
from __future__ import annotations

import json
import tarfile
import threading
from decimal import Decimal as D
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .io import ROOT, dump, log, sha, utcnow

DATA_ROOT = ROOT / 'data'
MARKET_ROOT = DATA_ROOT / 'experiments' / 'market'
EXPERIMENT_ROOT = DATA_ROOT / 'experiments'
DATA_CAP = 5_000_000_000
ARCHIVE_CAP = 1_000_000_000


def _tree_bytes(path: Path) -> int:
    """统计现有数据总大小，过滤并发消失文件，用于规范化和存储预留。

    输入参数：path（单位和范围由下方校验及调用方契约限定）。"""
    total = 0
    if path.exists():
        for item in path.rglob('*'):
            try:
                if item.is_file():
                    total += item.stat().st_size
            except FileNotFoundError:
                continue
    return total


def normalize_okx_archive(day: str, progress=None,
                          cancelled: threading.Event | None = None,
                          assumed_latency_ms: int = 250) -> tuple[Path, dict]:
    """流式读取官方 tar.gz 内唯一数据流，应用快照和增量并检验有效盘口，保存每秒首个前二十档；假设接收延迟明确记录而非实测。

    输入参数：day、progress、cancelled、assumed_latency_ms（单位和范围由下方校验及调用方契约限定）。

    原始实现说明：
    Apply OKX snapshot/update messages and retain the first valid view per second.
    
        The source carries exchange timestamps but no local receive timestamps. The
        latency offset is therefore an explicit simulation assumption, not measured."""
    if assumed_latency_ms < 0 or assumed_latency_ms > 5000:
        raise ValueError('Assumed latency must be within 0–5000 ms')
    folder = MARKET_ROOT / 'okx' / 'ETH-USDC' / day
    source = folder / 'source.tar.gz'
    target = folder / 'books.parquet'
    manifest_path = folder / 'manifest.json'
    if target.exists() and manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if manifest.get('books_sha256') == sha(target):
            return target, manifest
        raise ValueError('Existing OKX normalized data failed its manifest hash check')
    if not source.exists():
        raise FileNotFoundError(f'Upload the official OKX ETH-USDC L2 archive for {day} in the dashboard first')
    if source.stat().st_size > ARCHIVE_CAP:
        raise ValueError('OKX archive exceeds the 1 GB per-file guard')
    if _tree_bytes(DATA_ROOT) + 128_000_000 > DATA_CAP:
        raise ValueError('Insufficient disk reservation under the 5 GB data budget')

    expected_name = f'ETH-USDC-L2orderbook-400lv-{day}.data'
    output_part = target.with_suffix('.parquet.part')
    if output_part.exists():
        raise ValueError('A previous partial OKX normalization file exists; it was preserved for inspection')
    start = __import__('datetime').datetime.fromisoformat(day).replace(
        tzinfo=__import__('datetime').timezone.utc).timestamp()
    end = start + 86400
    bids: dict[D, D] = {}
    asks: dict[D, D] = {}
    valid = False
    previous_ts = None
    previous_second = None
    writer = None
    batch: list[dict] = []
    count = updates = snapshots = emitted = invalid = out_of_order = duplicate_ts = 0
    first_ts = last_ts = None

    def update_side(book: dict[D, D], levels: list) -> None:
        """按价格替换数量，零量删除，并校验价量合法；更新当前买侧或卖侧字典。

        输入参数：book、levels（单位和范围由下方校验及调用方契约限定）。"""
        for raw_price, raw_size, *_ in levels:
            price, size = D(str(raw_price)), D(str(raw_size))
            if not price.is_finite() or not size.is_finite() or price <= 0 or size < 0:
                raise ValueError('OKX archive contains an invalid price or size')
            if size == 0:
                book.pop(price, None)
            else:
                book[price] = size

    def encode(book: dict[D, D], reverse: bool) -> str:
        """对当前侧按买降卖升排序，取前二十档转 JSON，输出标准视图。

        输入参数：book、reverse（单位和范围由下方校验及调用方契约限定）。"""
        values = sorted(book, reverse=reverse)[:20]
        return json.dumps([[format(price, 'f'), format(book[price], 'f')] for price in values],
                          separators=(',', ':'))

    if progress:
        progress(dict(stage='normalize_okx', events=0,
                      message=f'Rebuilding OKX ETH-USDC L2 book for {day}'))
    try:
        with tarfile.open(source, mode='r:gz') as archive:
            members = [item for item in archive.getmembers() if item.isfile()]
            if len(members) != 1 or members[0].name != expected_name or members[0].size > DATA_CAP:
                raise ValueError('OKX tar.gz must contain only the matching 400-level ETH-USDC daily data file')
            stream = archive.extractfile(members[0])
            if stream is None:
                raise ValueError('OKX archive data member cannot be read')
            with stream:
                for line in stream:
                    count += 1
                    if count % 20000 == 0 and cancelled and cancelled.is_set():
                        raise InterruptedError('OKX normalization cancelled')
                    message = json.loads(line)
                    if message.get('instId') != 'ETH-USDC':
                        raise ValueError('OKX archive instrument does not match ETH-USDC')
                    action = message.get('action')
                    if action not in ('snapshot', 'update'):
                        raise ValueError(f'Unsupported OKX order-book action: {action}')
                    ts = int(message['ts'])
                    if previous_ts is not None and ts < previous_ts:
                        out_of_order += 1
                        valid = False
                        previous_ts = ts
                        continue
                    if previous_ts == ts:
                        duplicate_ts += 1
                    previous_ts = ts
                    first_ts = ts if first_ts is None else first_ts
                    last_ts = ts
                    if action == 'snapshot':
                        bids.clear()
                        asks.clear()
                        valid = True
                        snapshots += 1
                    else:
                        updates += 1
                        if not valid:
                            continue
                    try:
                        update_side(bids, message.get('bids', []))
                        update_side(asks, message.get('asks', []))
                    except (ValueError, KeyError, TypeError):
                        invalid += 1
                        valid = False
                        continue
                    if not bids or not asks or max(bids) >= min(asks):
                        invalid += 1
                        valid = False
                        continue
                    available_at = ts / 1000 + assumed_latency_ms / 1000
                    if not start <= available_at < end:
                        continue
                    second = int(available_at)
                    if second == previous_second:
                        continue
                    previous_second = second
                    batch.append(dict(
                        id=f'okx-{ts}-{count}', available_at=available_at,
                        exchange_ts=ts / 1000, update_id=str(count),
                        venue='okx', symbol='ETHUSDC', native_symbol='ETH-USDC',
                        bids_json=encode(bids, True), asks_json=encode(asks, False)))
                    emitted += 1
                    if len(batch) >= 2000:
                        table = pa.Table.from_pylist(batch)
                        if writer is None:
                            writer = pq.ParquetWriter(output_part, table.schema, compression='zstd')
                        writer.write_table(table)
                        batch.clear()
                    if progress and count % 50000 == 0:
                        progress(dict(stage='normalize_okx', events=count, views=emitted,
                                      message=f'Rebuilding OKX book: {count:,} source updates'))
            if batch:
                table = pa.Table.from_pylist(batch)
                if writer is None:
                    writer = pq.ParquetWriter(output_part, table.schema, compression='zstd')
                writer.write_table(table)
    finally:
        if writer is not None:
            writer.close()
        if cancelled and cancelled.is_set():
            output_part.unlink(missing_ok=True)
            raise InterruptedError('OKX normalization cancelled')

    if emitted == 0 or not output_part.exists():
        output_part.unlink(missing_ok=True)
        raise ValueError(f'No valid OKX ETH-USDC book views could be reconstructed for {day}')
    output_part.replace(target)
    manifest = dict(
        day=day, venue='okx', market='spot', symbol='ETHUSDC', native_symbol='ETH-USDC',
        source_url='https://www.okx.com/en-us/historical-data',
        source_file=source.name, archive_bytes=source.stat().st_size,
        archive_sha256=sha(source), books_bytes=target.stat().st_size,
        books_sha256=sha(target), source_depth=400, view_depth=20,
        source_events=count, updates=updates, snapshots=snapshots,
        out_of_order_events=out_of_order, duplicate_timestamps=duplicate_ts,
        invalid_book_states=invalid, views=emitted, gaps=None,
        first_exchange_ts_ms=first_ts, last_exchange_ts_ms=last_ts,
        view_frequency='first valid event per second', assumed_latency_ms=assumed_latency_ms,
        timestamp_semantics='OKX exchange event timestamp plus explicit assumed latency; local receive time unavailable',
        created_at=utcnow())
    dump(manifest_path, manifest)
    log('okx_l2_normalized', day=day, source_events=count, views=emitted,
        snapshots=snapshots, out_of_order=out_of_order, invalid=invalid,
        archive_sha256=manifest['archive_sha256'], books_sha256=manifest['books_sha256'])
    return target, manifest
