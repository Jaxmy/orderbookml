"""组件用途：分块计算文件 SHA-256，用于下载、上传和规范化来源核验。；将标准 ETHUSDC 映射为各所原生目录名称，OKX 使用 ETH-USDC；按场所和日期隔离。。

原始说明：Same-window CEX data preparation and causal Bybit/OKX book-arbitrage analysis."""
from __future__ import annotations

import csv
import hashlib
import json
import threading
import uuid
import zipfile
import concurrent.futures
from datetime import timedelta
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests

from .execution import sweep
from .experiment_engine import DATA_CAP, EXPERIMENT_ROOT, HIST_ROOT, _bytes, _prepare_day
from .io import ROOT, dump, log, read, sha, utcnow
from .okx_orderbook import MARKET_ROOT, normalize_okx_archive

BINANCE_TRADE_BASE = 'https://data.binance.vision/data/spot/daily/trades/ETHUSDC'
ARCHIVE_CAP = 1_000_000_000
CROSS_ROOT = ROOT / 'data' / 'experiments' / 'cross_venue'
CROSS_JOB_ROOT = CROSS_ROOT / 'jobs'
_cross_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix='cross-venue')
_cross_jobs: dict[str, dict] = {}
_cross_cancel: dict[str, threading.Event] = {}
_cross_lock = threading.RLock()


def _digest(path: Path) -> str:
    """分块计算文件 SHA-256，用于下载、上传和规范化来源核验。

    输入参数：path（单位和范围由下方校验及调用方契约限定）。"""
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def _market_dir(venue: str, day: str) -> Path:
    """将标准 ETHUSDC 映射为各所原生目录名称，OKX 使用 ETH-USDC；按场所和日期隔离。

    输入参数：venue、day（单位和范围由下方校验及调用方契约限定）。"""
    native = 'ETH-USDC' if venue == 'okx' else 'ETHUSDC'
    return MARKET_ROOT / venue / native / day


def download_binance_trade_archive(day: str, progress=None,
                                   cancelled: threading.Event | None = None) -> tuple[Path, dict]:
    """有界下载 Binance 官方逐笔成交 ZIP，预留存储并支持取消；不声称此档案含历史 L2。

    输入参数：day、progress、cancelled（单位和范围由下方校验及调用方契约限定）。"""
    folder = _market_dir('binance', day)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / 'trades.zip'
    if target.exists():
        return target, dict(day=day, venue='binance', symbol='ETHUSDC',
                            source_url=f'{BINANCE_TRADE_BASE}/ETHUSDC-trades-{day}.zip',
                            archive_bytes=target.stat().st_size, archive_sha256=_digest(target),
                            note='existing local archive')
    url = f'{BINANCE_TRADE_BASE}/ETHUSDC-trades-{day}.zip'
    partial = target.with_suffix('.zip.part')
    if partial.exists():
        raise ValueError('Partial Binance archive exists; it was preserved for inspection')
    with requests.get(url, stream=True, timeout=(10, 60)) as response:
        response.raise_for_status()
        expected = int(response.headers.get('Content-Length', 0))
        if expected <= 0 or expected > ARCHIVE_CAP:
            raise ValueError('Binance archive has unknown or over-limit announced size')
        if _bytes(HIST_ROOT) + _bytes(EXPERIMENT_ROOT) + expected > DATA_CAP:
            raise ValueError('Binance download would exceed the 5 GB project data budget')
        written = 0
        h = hashlib.sha256()
        with partial.open('xb') as stream:
            for block in response.iter_content(1024 * 1024):
                if cancelled and cancelled.is_set():
                    raise InterruptedError('Binance download cancelled from dashboard')
                if not block:
                    continue
                written += len(block)
                if written > expected or written > ARCHIVE_CAP:
                    raise ValueError('Binance archive exceeded its announced size')
                h.update(block)
                stream.write(block)
                if progress:
                    progress(dict(stage='download_binance', bytes=written,
                                  expected_bytes=expected,
                                  message=f'Downloading Binance ETH-USDC trades for {day}'))
        if written != expected:
            raise ValueError(f'Truncated Binance file: received {written} of {expected} bytes')
    try:
        with zipfile.ZipFile(partial) as archive:
            if archive.testzip() is not None:
                raise ValueError('Binance ZIP CRC validation failed')
            names = [item.filename for item in archive.infolist() if not item.is_dir()]
            if names != [f'ETHUSDC-trades-{day}.csv']:
                raise ValueError('Binance archive does not match the requested spot instrument/date')
        partial.replace(target)
    except Exception:
        # Keep the downloaded bytes available for diagnosis; never silently replace them.
        raise
    manifest = dict(day=day, venue='binance', market='spot', symbol='ETHUSDC',
                    source_url=url, archive_bytes=written, archive_sha256=h.hexdigest(),
                    file_kind='tick-level public trades; no historical L2 book in this adapter',
                    created_at=utcnow())
    dump(folder / 'download_manifest.json', manifest)
    log('binance_trade_archive_downloaded', day=day, bytes=written,
        sha256=manifest['archive_sha256'], source=url)
    return target, manifest


def normalize_binance_trades(day: str, progress=None,
                             cancelled: threading.Event | None = None) -> tuple[Path, dict]:
    """流式清洗官方成交日档，识别时间单位、重复和乱序，批量写 Parquet 与清单；保留主动方向，不生成盘口。

    输入参数：day、progress、cancelled（单位和范围由下方校验及调用方契约限定）。"""
    folder = _market_dir('binance', day)
    source = folder / 'trades.zip'
    target = folder / 'trades.parquet'
    manifest_path = folder / 'trades_manifest.json'
    if target.exists() and manifest_path.exists():
        manifest = read(manifest_path)
        if manifest.get('trades_sha256') == sha(target) and manifest.get('source_sha256') == _digest(source):
            return target, manifest
        raise ValueError('Existing Binance trades failed the manifest integrity check')
    if not source.exists():
        source, _ = download_binance_trade_archive(day, progress, cancelled)
    if source.stat().st_size > ARCHIVE_CAP:
        raise ValueError('Binance source archive exceeds its file-size guard')
    if _bytes(HIST_ROOT) + _bytes(EXPERIMENT_ROOT) + 128_000_000 > DATA_CAP:
        raise ValueError('Insufficient disk reservation under the 5 GB project data budget')
    partial = target.with_suffix('.parquet.part')
    if partial.exists():
        raise ValueError('Partial Binance normalization file exists; it was preserved for inspection')
    start = datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()
    end = start + 86400
    writer = None
    batch: list[dict] = []
    count = out_of_order = duplicate_id = outside = 0
    previous_ts = None
    seen_id = set()
    first_ts = last_ts = None
    with zipfile.ZipFile(source) as archive:
        if archive.testzip() is not None:
            raise ValueError('Binance ZIP CRC validation failed')
        member = f'ETHUSDC-trades-{day}.csv'
        if member not in archive.namelist():
            raise ValueError('Binance ZIP does not contain the requested daily ETHUSDC trades file')
        with archive.open(member) as byte_stream:
            import io
            rows = csv.reader(io.TextIOWrapper(byte_stream, encoding='utf-8', newline=''))
            for raw in rows:
                count += 1
                if count % 25000 == 0 and cancelled and cancelled.is_set():
                    raise InterruptedError('Binance trade normalization cancelled')
                if len(raw) != 7:
                    raise ValueError(f'Unexpected Binance trade schema at row {count}')
                trade_id, price, quantity, quote, timestamp, buyer_maker, best_match = raw
                stamp = int(timestamp)
                # Binance Spot archive timestamps switched to microseconds from 2025.
                unit = 'us' if stamp >= 100_000_000_000_000 else 'ms'
                exchange_ts = stamp / (1_000_000 if unit == 'us' else 1000)
                if previous_ts is not None and exchange_ts < previous_ts:
                    out_of_order += 1
                previous_ts = exchange_ts
                first_ts = exchange_ts if first_ts is None else first_ts
                last_ts = exchange_ts
                if not start <= exchange_ts < end:
                    outside += 1
                    continue
                if trade_id in seen_id:
                    duplicate_id += 1
                seen_id.add(trade_id)
                is_buyer_maker = buyer_maker.lower() == 'true'
                batch.append(dict(trade_id=trade_id, exchange_ts=exchange_ts,
                                  timestamp_unit=unit, price=price, quantity=quantity,
                                  quote_quantity=quote, buyer_is_maker=is_buyer_maker,
                                  aggressor_side='sell' if is_buyer_maker else 'buy',
                                  best_match=best_match.lower() == 'true',
                                  venue='binance', symbol='ETHUSDC'))
                if len(batch) >= 50000:
                    table = pa.Table.from_pylist(batch)
                    if writer is None:
                        writer = pq.ParquetWriter(partial, table.schema, compression='zstd')
                    writer.write_table(table)
                    batch.clear()
                if progress and count % 100000 == 0:
                    progress(dict(stage='normalize_binance', events=count,
                                  message=f'Normalizing Binance trades: {count:,} records'))
        if batch:
            table = pa.Table.from_pylist(batch)
            if writer is None:
                writer = pq.ParquetWriter(partial, table.schema, compression='zstd')
            writer.write_table(table)
    if writer is not None:
        writer.close()
    if cancelled and cancelled.is_set():
        partial.unlink(missing_ok=True)
        raise InterruptedError('Binance trade normalization cancelled')
    if count == 0 or outside:
        partial.unlink(missing_ok=True)
        raise ValueError('Binance archive contains no valid rows for the selected UTC day')
    partial.replace(target)
    manifest = dict(day=day, venue='binance', market='spot', symbol='ETHUSDC',
                    source_url=f'{BINANCE_TRADE_BASE}/ETHUSDC-trades-{day}.zip',
                    source_file=source.name, source_sha256=_digest(source),
                    source_bytes=source.stat().st_size, trades_bytes=target.stat().st_size,
                    trades_sha256=sha(target), trades=count, out_of_order_timestamps=out_of_order,
                    duplicate_ids=duplicate_id, outside_window=outside,
                    timestamp_unit='microseconds (Spot archive schema from 2025 onward)',
                    capabilities=dict(tick_trades=True, historical_l2=False,
                                      execution_replay=False, indicative_trade_price_comparison=True),
                    created_at=utcnow())
    dump(manifest_path, manifest)
    log('binance_trades_normalized', day=day, trades=count,
        out_of_order=out_of_order, duplicates=duplicate_id,
        source_sha256=manifest['source_sha256'], trades_sha256=manifest['trades_sha256'])
    return target, manifest


def ingest_okx_upload(day: str, filename: str, uploaded, max_bytes: int = ARCHIVE_CAP) -> Path:
    """校验看板上传的官方日档文件名和容量，流式写项目缓存，已有档案按摘要判断复用或拒绝覆盖。

    输入参数：day、filename、uploaded、max_bytes（单位和范围由下方校验及调用方契约限定）。

    原始实现说明：
    Store one dashboard-uploaded official OKX daily tar.gz without extracting it."""
    expected = f'ETH-USDC-L2orderbook-400lv-{day}.tar.gz'
    if filename != expected:
        raise ValueError(f'Expected official archive name {expected}')
    folder = _market_dir('okx', day)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / 'source.tar.gz'
    partial = target.with_suffix('.tar.gz.part')
    if target.exists():
        raise FileExistsError('An OKX archive already exists for this day; existing research data was preserved')
    size = int(getattr(uploaded, 'size', -1))
    if size <= 0 or size > max_bytes:
        raise ValueError('OKX archive must be non-empty and no larger than 1 GB')
    if _bytes(HIST_ROOT) + _bytes(EXPERIMENT_ROOT) + size > DATA_CAP:
        raise ValueError('OKX upload would exceed the 5 GB project data budget')
    digest = hashlib.sha256()
    with partial.open('xb') as output:
        view = uploaded.getbuffer() if hasattr(uploaded, 'getbuffer') else memoryview(uploaded)
        for offset in range(0, len(view), 1024 * 1024):
            chunk = view[offset:offset + 1024 * 1024]
            digest.update(chunk)
            output.write(chunk)
    try:
        with zipfile.ZipFile(partial) as _:
            raise ValueError('Expected the official OKX .tar.gz, received a ZIP archive')
    except zipfile.BadZipFile:
        pass
    # Opening and reading the tar header verifies gzip integrity and the expected payload path.
    import tarfile
    try:
        with tarfile.open(partial, 'r:gz') as archive:
            members = [item for item in archive.getmembers() if item.isfile()]
            if len(members) != 1 or members[0].name != f'ETH-USDC-L2orderbook-400lv-{day}.data':
                raise ValueError('OKX archive contents do not match the selected ETH-USDC UTC date')
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    partial.replace(target)
    dump(folder / 'upload_manifest.json', dict(day=day, venue='okx', native_symbol='ETH-USDC',
         source_file=target.name, source_bytes=size, source_sha256=digest.hexdigest(),
         source_url='https://www.okx.com/en-us/historical-data', created_at=utcnow()))
    log('okx_l2_archive_uploaded_from_dashboard', day=day, bytes=size,
        sha256=digest.hexdigest())
    return target


def prepare_cross_venue_data(day: str, progress=None,
                             cancelled: threading.Event | None = None) -> dict:
    """依次取得 Bybit L2、OKX L2及 Binance 成交的已验证同日文件和清单。

    输入参数：day、progress、cancelled（单位和范围由下方校验及调用方契约限定）。"""
    bybit_path, bybit_manifest = _prepare_day(day, progress, cancelled, venue='bybit')
    okx_path, okx_manifest = normalize_okx_archive(day, progress, cancelled)
    binance_path, binance_manifest = normalize_binance_trades(day, progress, cancelled)
    return dict(day=day, bybit_books_path=str(bybit_path), bybit=bybit_manifest,
                okx_books_path=str(okx_path), okx=okx_manifest,
                binance_trades_path=str(binance_path), binance=binance_manifest)


def _book_path(venue: str, day: str) -> tuple[Path, dict]:
    """仅返回对应场所日档已规范化且摘要匹配的 L2；缺失或篡改均停止。

    输入参数：venue、day（单位和范围由下方校验及调用方契约限定）。"""
    folder = _market_dir(venue, day)
    books = folder / 'books.parquet'
    manifest_path = folder / 'manifest.json'
    if not books.exists() or not manifest_path.exists():
        raise FileNotFoundError(f'{venue} ETH-USDC historical L2 is not normalized for {day}')
    manifest = read(manifest_path)
    if manifest.get('books_sha256') != sha(books):
        raise ValueError(f'{venue} books.parquet failed manifest hash verification')
    return books, manifest


def _trade_path(day: str) -> tuple[Path, dict]:
    """核验 Binance 成交 Parquet 与来源清单，返回合法路径；不能用它代替订单簿。

    输入参数：day（单位和范围由下方校验及调用方契约限定）。"""
    folder = _market_dir('binance', day)
    path, manifest_path = folder / 'trades.parquet', folder / 'trades_manifest.json'
    if not path.exists() or not manifest_path.exists():
        raise FileNotFoundError(f'Binance ETH-USDC trade tape is not normalized for {day}')
    manifest = read(manifest_path)
    if manifest.get('trades_sha256') != sha(path):
        raise ValueError('Binance trades.parquet failed manifest hash verification')
    return path, manifest


def _asof_trade_context(aligned: pd.DataFrame, trade_path: Path, latency_ms: int,
                        max_age_ms: int) -> pd.DataFrame:
    """把较早已知 Binance 成交向后对齐到跨所盘口时点，加入成交价参照并限制陈旧度；未来成交不可进入。

    输入参数：aligned、trade_path、latency_ms、max_age_ms（单位和范围由下方校验及调用方契约限定）。"""
    trades = pd.read_parquet(trade_path, columns=['exchange_ts', 'price', 'quantity', 'quote_quantity',
                                                 'aggressor_side', 'trade_id'])
    if trades.empty:
        return aligned
    trades['binance_available_at'] = trades['exchange_ts'].astype('float64') + latency_ms / 1000
    trades = trades.sort_values('binance_available_at').drop_duplicates('binance_available_at', keep='last')
    left = aligned.sort_values('evaluation_at')
    out = pd.merge_asof(left, trades.sort_values('binance_available_at'),
                        left_on='evaluation_at', right_on='binance_available_at',
                        direction='backward', tolerance=max_age_ms / 1000)
    out['binance_trade_age_ms'] = (out['evaluation_at'] - out['binance_available_at']) * 1000
    out['binance_vs_bybit_mid_bps'] = (
        (out['price'].astype('float64') / out['bybit_mid'] - 1) * 10000)
    out['binance_vs_okx_mid_bps'] = (
        (out['price'].astype('float64') / out['okx_mid'] - 1) * 10000)
    return out


def analyze_cross_venue(day: str, quantity_eth: str | float = '0.1',
                        bybit_fee_bps: str | float = '10',
                        okx_fee_bps: str | float = '10',
                        assumed_latency_ms: int = 250,
                        max_book_age_ms: int = 1500,
                        max_binance_trade_age_ms: int = 3000,
                        progress=None, cancelled: threading.Event | None = None,
                        run_id: str | None = None) -> tuple[Path, dict]:
    """同日 Bybit/OKX 簿按因果时间对齐，双向模拟买卖腿并各扣一次费用；输出快照机会和质量，不累计重叠时点成策略收益。

    输入参数：day、quantity_eth、bybit_fee_bps、okx_fee_bps、assumed_latency_ms、max_book_age_ms、max_binance_trade_age_ms、progress、cancelled、run_id（单位和范围由下方校验及调用方契约限定）。

    原始实现说明：
    Compare pre-funded CEX buy/sell routes using only causally available book states."""
    quantity, bybit_fee, okx_fee = map(D, map(str, (quantity_eth, bybit_fee_bps, okx_fee_bps)))
    if quantity <= 0 or bybit_fee < 0 or okx_fee < 0:
        raise ValueError('Quantity must be positive and taker fee assumptions cannot be negative')
    if not 0 <= assumed_latency_ms <= 5000 or not 100 <= max_book_age_ms <= 10000:
        raise ValueError('Latency or book-age parameter is outside its supported range')
    bybit_path, bybit_manifest = _book_path('bybit', day)
    okx_path, okx_manifest = _book_path('okx', day)
    trade_path, binance_manifest = _trade_path(day)

    bybit = pd.read_parquet(bybit_path, columns=['exchange_ts', 'bids_json', 'asks_json'])
    okx = pd.read_parquet(okx_path, columns=['exchange_ts', 'bids_json', 'asks_json'])
    bybit['bybit_available_at'] = bybit['exchange_ts'].astype('float64') + assumed_latency_ms / 1000
    okx['okx_available_at'] = okx['exchange_ts'].astype('float64') + assumed_latency_ms / 1000
    bybit = bybit.sort_values('bybit_available_at')
    okx = okx.sort_values('okx_available_at')
    paired = pd.merge_asof(bybit, okx, left_on='bybit_available_at', right_on='okx_available_at',
                           direction='backward', tolerance=max_book_age_ms / 1000,
                           suffixes=('_bybit', '_okx'))
    paired = paired.dropna(subset=['bids_json_okx', 'asks_json_okx']).copy()
    if paired.empty:
        raise ValueError('No causal, fresh Bybit/OKX book pairs overlap on the selected date')
    paired = paired.rename(columns={'bybit_available_at': 'evaluation_at',
                                    'exchange_ts_bybit': 'bybit_exchange_ts',
                                    'exchange_ts_okx': 'okx_exchange_ts',
                                    'bids_json_bybit': 'bybit_bids_json',
                                    'asks_json_bybit': 'bybit_asks_json',
                                    'bids_json_okx': 'okx_bids_json',
                                    'asks_json_okx': 'okx_asks_json'})
    paired['okx_book_age_ms'] = (paired['evaluation_at'] - paired['okx_available_at']) * 1000
    paired['exchange_timestamp_skew_ms'] = (
        (paired['bybit_exchange_ts'] - paired['okx_exchange_ts']).abs() * 1000)

    rows = []
    total = len(paired)
    for index, rec in enumerate(paired.itertuples(index=False), start=1):
        if cancelled and index % 5000 == 0 and cancelled.is_set():
            raise InterruptedError('Cross-venue analysis cancelled from dashboard')
        bybit_book = dict(bids_json=rec.bybit_bids_json, asks_json=rec.bybit_asks_json)
        okx_book = dict(bids_json=rec.okx_bids_json, asks_json=rec.okx_asks_json)
        b_buy = sweep(bybit_book, 'buy', format(quantity, 'f'), format(bybit_fee, 'f'))
        b_sell = sweep(bybit_book, 'sell', format(quantity, 'f'), format(bybit_fee, 'f'))
        o_buy = sweep(okx_book, 'buy', format(quantity, 'f'), format(okx_fee, 'f'))
        o_sell = sweep(okx_book, 'sell', format(quantity, 'f'), format(okx_fee, 'f'))
        complete_b_o = b_buy['complete'] and o_sell['complete']
        complete_o_b = o_buy['complete'] and b_sell['complete']
        pnl_buy_bybit_sell_okx = (D(o_sell['net_quote']) - D(b_buy['net_quote'])) if complete_b_o else None
        pnl_buy_okx_sell_bybit = (D(b_sell['net_quote']) - D(o_buy['net_quote'])) if complete_o_b else None
        b_mid = (D(json.loads(rec.bybit_bids_json)[0][0]) + D(json.loads(rec.bybit_asks_json)[0][0])) / 2
        o_mid = (D(json.loads(rec.okx_bids_json)[0][0]) + D(json.loads(rec.okx_asks_json)[0][0])) / 2
        row = dict(
            evaluation_at=float(rec.evaluation_at),
            utc=datetime.fromtimestamp(float(rec.evaluation_at), timezone.utc).isoformat(),
            bybit_exchange_ts=float(rec.bybit_exchange_ts), okx_exchange_ts=float(rec.okx_exchange_ts),
            okx_book_age_ms=float(rec.okx_book_age_ms),
            exchange_timestamp_skew_ms=float(rec.exchange_timestamp_skew_ms),
            bybit_mid=float(b_mid), okx_mid=float(o_mid),
            bybit_bid=float(json.loads(rec.bybit_bids_json)[0][0]),
            bybit_ask=float(json.loads(rec.bybit_asks_json)[0][0]),
            okx_bid=float(json.loads(rec.okx_bids_json)[0][0]),
            okx_ask=float(json.loads(rec.okx_asks_json)[0][0]),
            buy_bybit_sell_okx_complete=bool(complete_b_o),
            buy_bybit_sell_okx_net_usdc=float(pnl_buy_bybit_sell_okx) if pnl_buy_bybit_sell_okx is not None else None,
            buy_okx_sell_bybit_complete=bool(complete_o_b),
            buy_okx_sell_bybit_net_usdc=float(pnl_buy_okx_sell_bybit) if pnl_buy_okx_sell_bybit is not None else None,
            bybit_buy_vwap=float(b_buy['vwap']) if b_buy['complete'] else None,
            okx_sell_vwap=float(o_sell['vwap']) if o_sell['complete'] else None,
            okx_buy_vwap=float(o_buy['vwap']) if o_buy['complete'] else None,
            bybit_sell_vwap=float(b_sell['vwap']) if b_sell['complete'] else None)
        rows.append(row)
        if progress and index % 5000 == 0:
            progress(dict(stage='cross_venue', completed=index, total=total,
                          message=f'Comparing causally aligned CEX books: {index:,}/{total:,}'))
    aligned = pd.DataFrame(rows)
    aligned = _asof_trade_context(aligned, trade_path, assumed_latency_ms,
                                  max_binance_trade_age_ms)
    output_id = run_id or uuid.uuid4().hex
    if not output_id.isalnum() or len(output_id) != 32:
        raise ValueError('Invalid cross-venue run identifier')
    output_folder = CROSS_ROOT / 'runs' / output_id
    output_folder.mkdir(parents=True, exist_ok=False)
    output_path = output_folder / 'aligned.parquet'
    aligned.to_parquet(output_path, index=False, compression='zstd')

    b_o = aligned['buy_bybit_sell_okx_net_usdc'].dropna()
    o_b = aligned['buy_okx_sell_bybit_net_usdc'].dropna()
    positive_b_o = b_o[b_o > 0]
    positive_o_b = o_b[o_b > 0]
    positive_any = int(((aligned['buy_bybit_sell_okx_net_usdc'] > 0) |
                        (aligned['buy_okx_sell_bybit_net_usdc'] > 0)).fillna(False).sum())
    context = aligned[['binance_available_at', 'price', 'aggressor_side']].dropna()
    manifest = dict(day=day, venue='binance', symbol='ETHUSDC',
                    source='Binance public spot trade tape; no Binance L2 in this run')
    report = dict(
        run_id=output_id, window=dict(day_utc=day, start_utc=f'{day}T00:00:00Z',
                                     end_utc=f'{day}T23:59:59.999Z'),
        order=dict(base_quantity_eth=format(quantity, 'f'),
                   bybit_taker_fee_bps=format(bybit_fee, 'f'),
                   okx_taker_fee_bps=format(okx_fee, 'f'),
                   assumed_event_to_available_latency_ms=assumed_latency_ms,
                   maximum_asof_book_age_ms=max_book_age_ms),
        data=dict(bybit=bybit_manifest, okx=okx_manifest, binance_trades=binance_manifest,
                  aligned_points=len(aligned), binance_trade_references=int(len(context)),
                  aligned_sha256=sha(output_path), aligned_bytes=output_path.stat().st_size),
        synchronization=dict(method='Bybit observation times, as-of/backward OKX book join; future snapshots are excluded',
                             bybit_views=len(bybit), okx_views=len(okx),
                             matched_points=len(aligned),
                             okx_book_age_ms_p50=float(aligned['okx_book_age_ms'].median()),
                             okx_book_age_ms_p95=float(aligned['okx_book_age_ms'].quantile(.95)),
                             max_exchange_timestamp_skew_ms=float(aligned['exchange_timestamp_skew_ms'].max()),
                             assumed_latency_is_measured=False),
        arbitrage=dict(
            model='same-quantity cross-venue taker sweep, fees included',
            pre_funded_inventory_required=True,
            buy_bybit_sell_okx=dict(complete_quotes=int(len(b_o)), positive_points=int(len(positive_b_o)),
                                    positive_share_pct=float(len(positive_b_o) / len(b_o) * 100) if len(b_o) else 0,
                                    best_single_snapshot_net_usdc=float(b_o.max()) if len(b_o) else None,
                                    median_positive_snapshot_net_usdc=float(positive_b_o.median()) if len(positive_b_o) else None),
            buy_okx_sell_bybit=dict(complete_quotes=int(len(o_b)), positive_points=int(len(positive_o_b)),
                                    positive_share_pct=float(len(positive_o_b) / len(o_b) * 100) if len(o_b) else 0,
                                    best_single_snapshot_net_usdc=float(o_b.max()) if len(o_b) else None,
                                    median_positive_snapshot_net_usdc=float(positive_o_b.median()) if len(positive_o_b) else None),
            positive_snapshot_seconds_any_direction=positive_any,
            cumulative_pnl_reported=False),
        binance=dict(
            book_execution_available=False,
            reference='causal last Binance trade at or before each aligned book time',
            matched_trade_references=int(len(context)),
            median_vs_bybit_mid_bps=float(aligned['binance_vs_bybit_mid_bps'].dropna().median()) if aligned['binance_vs_bybit_mid_bps'].notna().any() else None,
            median_vs_okx_mid_bps=float(aligned['binance_vs_okx_mid_bps'].dropna().median()) if aligned['binance_vs_okx_mid_bps'].notna().any() else None,
            execution_claim='trade-price divergence only; not an executable spread or Binance arbitrage quote'),
        limits=['Bybit and OKX files contain L2 price-level depth, not individual queue position (L3).',
                'Binance contributes tick-level spot trades only; its public spot archive does not supply this historical L2 book.',
                'Evaluation uses exchange event timestamps plus a user assumption; historical local receipt times are unavailable.',
                'A positive snapshot is not a distinct strategy fill; overlapping seconds are not summed as cumulative profit.',
                'Assumes prefunded ETH and USDC at both venues; inventory transfers, withdrawal delays, financing, and operational risk are excluded.',
                'Fees are user assumptions and must be set to the trader’s account tier.'],
        created_at=utcnow(), result_path=str(output_path))
    dump(output_folder / 'result.json', report)
    log('cross_venue_analysis_completed', run_id=output_id, day=day,
        points=len(aligned), quantity_eth=format(quantity, 'f'),
        positive_snapshots=positive_any, bybit_l2=bybit_manifest.get('books_sha256'),
        okx_l2=okx_manifest.get('books_sha256'), binance_trades=binance_manifest.get('trades_sha256'))
    return output_path, report


def _job_path(job_id: str) -> Path:
    """校验跨所任务标识，限制结果路径在固定运行根目录。

    输入参数：job_id（单位和范围由下方校验及调用方契约限定）。"""
    if not job_id.isalnum() or len(job_id) != 32:
        raise ValueError('Invalid cross-venue job identifier')
    return CROSS_JOB_ROOT / job_id


def _save_job(job: dict) -> None:
    """锁内更新跨所任务状态并写磁盘，使刷新后能继续查看。

    输入参数：job（单位和范围由下方校验及调用方契约限定）。"""
    with _cross_lock:
        _cross_jobs[job['id']] = job.copy()
    folder = _job_path(job['id'])
    folder.mkdir(parents=True, exist_ok=True)
    dump(folder / 'job.json', job)


def _cross_worker(job_id: str, config: dict, cancelled: threading.Event) -> None:
    """串行后台完成准备和同窗分析，分别记录完成、取消和失败；结果与任务 id 绑定。

    输入参数：job_id、config、cancelled（单位和范围由下方校验及调用方契约限定）。"""
    job = dict(id=job_id, status='running', stage='starting', progress=0.01,
               message='Starting same-window CEX data preparation', config=config,
               created_at=utcnow(), error=None)
    _save_job(job)

    stage_floor = {'download': 0.03, 'normalize': 0.10, 'normalize_okx': 0.35,
                   'download_binance': 0.73, 'normalize_binance': 0.82,
                   'cross_venue': 0.90}

    def progress(state: dict) -> None:
        """按阶段底线和完成数量计算跨所进度，持久化当前提示供页面轮询。

        输入参数：state（单位和范围由下方校验及调用方契约限定）。"""
        current = dict(job)
        current.update(state)
        current['status'] = 'running'
        floor = stage_floor.get(current.get('stage'), float(current.get('progress', 0.02)))
        if current.get('stage') == 'cross_venue' and current.get('total'):
            ratio = int(current.get('completed', 0)) / max(1, int(current['total']))
            floor += min(0.09, 0.09 * ratio)
        elif current.get('stage') == 'download' and current.get('expected_bytes'):
            ratio = int(current.get('bytes', 0)) / max(1, int(current['expected_bytes']))
            floor += min(0.05, 0.05 * ratio)
        current['progress'] = max(float(current.get('progress', 0.01)), floor)
        current['updated_at'] = utcnow()
        _save_job(current)

    try:
        day = config['day']
        if cancelled.is_set():
            raise InterruptedError('Cross-venue run cancelled from dashboard')
        progress(dict(stage='data', progress=0.03, message='Preparing Bybit L2, OKX L2 and Binance trades'))
        sources = prepare_cross_venue_data(day, progress=progress, cancelled=cancelled)
        if cancelled.is_set():
            raise InterruptedError('Cross-venue run cancelled from dashboard')
        progress(dict(stage='cross_venue', progress=0.9, message='Aligning markets and simulating both trade directions'))
        result_path, report = analyze_cross_venue(
            day=day, quantity_eth=config['quantity_eth'],
            bybit_fee_bps=config['bybit_fee_bps'], okx_fee_bps=config['okx_fee_bps'],
            assumed_latency_ms=config['assumed_latency_ms'],
            max_book_age_ms=config['max_book_age_ms'],
            max_binance_trade_age_ms=config['max_binance_trade_age_ms'],
            progress=progress, cancelled=cancelled, run_id=job_id)
        job.update(status='completed', stage='complete', progress=1.0,
                   message='Cross-venue analysis complete', completed_at=utcnow(),
                   result_path=str(result_path.parent / 'result.json'),
                   aligned_path=str(result_path), source_dates=[sources['day']])
        _save_job(job)
        log('cross_venue_job_completed', run_id=job_id, day=day,
            aligned_points=report['data']['aligned_points'])
    except InterruptedError as exc:
        job.update(status='cancelled', stage='cancelled', progress=1.0,
                   message=str(exc), completed_at=utcnow())
        _save_job(job)
        log('cross_venue_job_cancelled', run_id=job_id, day=config.get('day'))
    except Exception as exc:
        job.update(status='failed', stage='failed', progress=1.0,
                   message='Cross-venue run failed', error=f'{type(exc).__name__}: {exc}',
                   completed_at=utcnow())
        _save_job(job)
        log('cross_venue_job_failed', run_id=job_id, day=config.get('day'),
            error_type=type(exc).__name__, error=str(exc))


def submit_cross_venue(config: dict) -> str:
    """创建排队记录和取消事件，提交单线程执行器，立即向看板返回任务 id。

    输入参数：config（单位和范围由下方校验及调用方契约限定）。"""
    job_id = uuid.uuid4().hex
    event = threading.Event()
    with _cross_lock:
        _cross_cancel[job_id] = event
    queued = dict(id=job_id, status='queued', stage='queued', progress=0.0,
                  message='Queued for cross-venue data preparation', config=config.copy(),
                  created_at=utcnow(), error=None)
    _save_job(queued)
    _cross_pool.submit(_cross_worker, job_id, config.copy(), event)
    return job_id


def get_cross_job(job_id: str) -> dict | None:
    """从内存或磁盘恢复指定跨所任务，非法或不存在返回 None。

    输入参数：job_id（单位和范围由下方校验及调用方契约限定）。"""
    with _cross_lock:
        item = _cross_jobs.get(job_id)
    if item is not None:
        return item.copy()
    try:
        return read(_job_path(job_id) / 'job.json')
    except (FileNotFoundError, ValueError):
        return None


def get_cross_report(job_id: str) -> dict | None:
    """只读取已完成任务且位于项目允许目录的报告，缺失或路径非法返回 None。

    输入参数：job_id（单位和范围由下方校验及调用方契约限定）。"""
    job = get_cross_job(job_id)
    if not job or job.get('status') != 'completed' or not job.get('result_path'):
        return None
    try:
        path = Path(job['result_path']).resolve()
        path.relative_to((CROSS_ROOT / 'runs').resolve())
        return read(path)
    except (FileNotFoundError, ValueError):
        return None


def cancel_cross_job(job_id: str) -> bool:
    """请求仍在本进程的跨所任务取消，通过事件在下载或分析检查点停止。

    输入参数：job_id（单位和范围由下方校验及调用方契约限定）。"""
    with _cross_lock:
        event = _cross_cancel.get(job_id)
    if event is None:
        return False
    event.set()
    item = get_cross_job(job_id)
    if item and item.get('status') in ('queued', 'running'):
        item.update(message='Cancellation requested', updated_at=utcnow())
        _save_job(item)
    return True


def recent_cross_jobs(limit: int = 20) -> list[dict]:
    """读取最近跨所任务的持久状态，按创建时间倒序供看板恢复和导出。

    输入参数：limit（单位和范围由下方校验及调用方契约限定）。"""
    items = []
    if CROSS_JOB_ROOT.exists():
        for folder in CROSS_JOB_ROOT.iterdir():
            path = folder / 'job.json'
            if folder.is_dir() and path.exists():
                try:
                    items.append(read(path))
                except Exception:
                    continue
    return sorted(items, key=lambda item: item.get('created_at', ''), reverse=True)[:limit]
