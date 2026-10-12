"""组件用途：累计目录文件大小，忽略遍历期间已消失的文件，供五十亿字节资源预检使用。；汇总本机 Bybit 已规范化日期，返回有序去重列表供看板选择缓存。。

原始说明：Dashboard-driven, bounded historical CEX execution experiments (P1)."""
from __future__ import annotations

import bisect
import concurrent.futures
import json
import threading
import time
import uuid
import zipfile
from datetime import date, datetime, time as day_time, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests

from .execution import mid, sweep, validate_book
from .io import ROOT, dump, log, read, sha, utcnow
from .orderbook import OrderBook

DATA_ROOT = ROOT / 'data'
EXPERIMENT_ROOT = DATA_ROOT / 'experiments'
RUN_ROOT = EXPERIMENT_ROOT / 'runs'
MARKET_ROOT = EXPERIMENT_ROOT / 'market' / 'bybit' / 'ETHUSDC'
HIST_ROOT = DATA_ROOT / 'historical'
DATA_CAP = 5_000_000_000
ARCHIVE_CAP = 1_000_000_000
MAX_WINDOW_DAYS = 7
BASE_URL = 'https://quote-saver.bycsi.com/orderbook/spot/ETHUSDC'

_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix='market-research')
_jobs: dict[str, dict] = {}
_cancel: dict[str, threading.Event] = {}
_lock = threading.RLock()


def _bytes(folder: Path) -> int:
    """累计目录文件大小，忽略遍历期间已消失的文件，供五十亿字节资源预检使用。

    输入参数：folder（单位和范围由下方校验及调用方契约限定）。"""
    total = 0
    if folder.exists():
        for p in folder.rglob('*'):
            try:
                if p.is_file():
                    total += p.stat().st_size
            except FileNotFoundError:
                pass
    return total


def local_days() -> list[str]:
    """汇总本机 Bybit 已规范化日期，返回有序去重列表供看板选择缓存。"""
    values = set()
    for p in HIST_ROOT.glob('*.books.parquet'):
        values.add(p.name.split('.')[0])
    for p in MARKET_ROOT.glob('*/books.parquet'):
        values.add(p.parent.name)
    return sorted(values)


def probe_latest(max_days: int = 14) -> dict:
    """从最近过去日期向前检查公开 Bybit 日档 HEAD，检查长度预算并返回首个可用来源；保留失败原因，不把实时接口当历史数据。

    输入参数：max_days（单位和范围由下方校验及调用方契约限定）。"""
    today = datetime.now(timezone.utc).date()
    session = requests.Session()
    failures = []
    for offset in range(1, max_days + 1):
        day = today - timedelta(days=offset)
        name = f'{day.isoformat()}_ETHUSDC_ob200.data.zip'
        try:
            response = session.head(f'{BASE_URL}/{name}', timeout=(4, 8), allow_redirects=True)
            if response.status_code == 200:
                size = int(response.headers.get('Content-Length', 0))
                if size <= 0 or size > ARCHIVE_CAP:
                    raise ValueError('Public archive has unknown or over-limit size')
                return dict(day=day.isoformat(), bytes=size, url=f'{BASE_URL}/{name}', checked_at=utcnow())
            failures.append(f'{day}:{response.status_code}')
        except Exception as exc:
            failures.append(f'{day}:{type(exc).__name__}')
    raise RuntimeError('No recent public daily archive found. ' + ', '.join(failures[-4:]))


def _resolve_book(day: str, venue: str = 'bybit') -> tuple[Path, dict]:
    """定位已有旧目录或新市场缓存，核验清单与盘口哈希；已有文件不符时拒绝而非悄悄重建覆盖。

    输入参数：day、venue（单位和范围由下方校验及调用方契约限定）。"""
    if venue == 'okx':
        dynamic = EXPERIMENT_ROOT / 'market' / 'okx' / 'ETH-USDC' / day / 'books.parquet'
    elif venue == 'bybit':
        dynamic = MARKET_ROOT / day / 'books.parquet'
    else:
        raise ValueError(f'Historical L2 execution is unavailable for {venue}')
    if dynamic.exists():
        manifest = read(dynamic.parent / 'manifest.json')
        if manifest.get('books_sha256') != sha(dynamic):
            raise ValueError(f'{day}: normalized book hash mismatch')
        return dynamic, manifest
    legacy = HIST_ROOT / f'{day}.books.parquet'
    if venue == 'bybit' and legacy.exists():
        manifest = read(HIST_ROOT / 'normalized_manifest.json')
        record = next((r for r in manifest['days'] if r['day'] == day), None)
        if not record or record['sha256'] != sha(legacy):
            raise ValueError(f'{day}: legacy normalized book hash mismatch')
        return legacy, dict(day=day, venue='bybit', symbol='ETHUSDC',
                            source='existing verified project archive', books_sha256=record['sha256'],
                            views=record['views'], events=record['events'], gaps=record['gaps'],
                            timestamp_semantics=manifest['timestamp_semantics'])
    raise FileNotFoundError(day)


def _prepare_day(day: str, progress, cancelled: threading.Event,
                 venue: str = 'bybit') -> tuple[Path, dict]:
    """复用经验证的缓存或下载受大小限制日档，检查 ZIP CRC，流式应用快照/增量，每秒输出首个有效前二十档视图。进度/取消由回调与事件控制。

    输入参数：day、progress、cancelled、venue（单位和范围由下方校验及调用方契约限定）。"""
    if venue == 'okx':
        try:
            return _resolve_book(day, venue)
        except FileNotFoundError:
            from .okx_orderbook import normalize_okx_archive
            return normalize_okx_archive(day, progress, cancelled)
    if venue != 'bybit':
        raise ValueError(f'Historical L2 execution is unavailable for {venue}')
    try:
        return _resolve_book(day, venue)
    except FileNotFoundError:
        pass

    target = MARKET_ROOT / day
    target.mkdir(parents=True, exist_ok=True)
    archive = target / 'source.zip'
    manifest_path = target / 'manifest.json'
    if archive.exists() and not manifest_path.exists():
        # Verify browser/dashboard-downloaded archives before rebuilding them.
        with zipfile.ZipFile(archive) as archive_file:
            if archive_file.testzip() is not None or len(archive_file.infolist()) != 1:
                raise ValueError(f'{day}: unmanifested Bybit archive failed ZIP/layout validation')
            member = archive_file.infolist()[0]
            if member.file_size > DATA_CAP or Path(member.filename).name != f'{day}_ETHUSDC_ob200.data':
                raise ValueError(f'{day}: unmanifested Bybit archive does not match the requested date/instrument')
            with archive_file.open(member) as source:
                first = json.loads(source.readline())
                if first.get('data', {}).get('s') != 'ETHUSDC':
                    raise ValueError(f'{day}: unmanifested Bybit archive contains the wrong instrument')
    elif archive.exists():
        existing = read(manifest_path)
        expected_hash = existing.get('archive_sha256')
        if expected_hash and expected_hash != sha(archive):
            raise ValueError(f'{day}: source archive hash differs from the recorded manifest')
    if not archive.exists():
        name = f'{day}_ETHUSDC_ob200.data.zip'
        url = f'{BASE_URL}/{name}'
        partial = target / 'source.zip.part'
        if partial.exists():
            raise ValueError(f'{day}: partial download exists; it was preserved for inspection')
        with requests.get(url, stream=True, timeout=(10, 45)) as response:
            response.raise_for_status()
            expected = int(response.headers.get('Content-Length', 0))
            if expected <= 0 or expected > ARCHIVE_CAP:
                raise ValueError(f'{day}: unknown or over-limit archive size')
            if _bytes(HIST_ROOT) + _bytes(EXPERIMENT_ROOT) + expected > DATA_CAP:
                raise ValueError('Historical data budget of 5 GB would be exceeded')
            written = 0
            try:
                with partial.open('xb') as stream:
                    for block in response.iter_content(1024 * 1024):
                        if cancelled.is_set():
                            stream.close()
                            partial.unlink(missing_ok=True)
                            raise InterruptedError('Experiment cancelled during archive download')
                        if not block:
                            continue
                        written += len(block)
                        if written > expected or written > ARCHIVE_CAP:
                            raise ValueError('Archive exceeded its announced size limit')
                        stream.write(block)
                        progress(dict(stage='download', day=day, bytes=written, expected_bytes=expected,
                                      message=f'Downloading {day} public Bybit L2 archive'))
                if written != expected:
                    raise ValueError(f'Truncated archive: received {written} of {expected} bytes')
                with zipfile.ZipFile(partial) as archive_file:
                    if len(archive_file.infolist()) != 1 or archive_file.infolist()[0].file_size > DATA_CAP:
                        raise ValueError('Unexpected archive layout or expansion size')
                    with archive_file.open(archive_file.namelist()[0]) as source:
                        first = json.loads(source.readline())
                        if first.get('data', {}).get('s') != 'ETHUSDC':
                            raise ValueError('Archive instrument does not match ETHUSDC')
                partial.replace(archive)
            except Exception:
                # Preserve partial bytes as evidence; the dashboard reports their path.
                raise
        log('experiment_archive_downloaded', day=day, bytes=written, sha256=sha(archive), source=url)

    if _bytes(HIST_ROOT) + _bytes(EXPERIMENT_ROOT) > DATA_CAP:
        raise ValueError('Historical data budget of 5 GB exceeded before normalization')
    books_path = target / 'books.parquet'
    partial_books = target / 'books.parquet.part'
    if partial_books.exists():
        raise ValueError(f'{day}: partial normalized file exists; it was preserved for inspection')
    book = OrderBook('ETHUSDC')
    batch, emitted, count, outside, last_second = [], 0, 0, 0, None
    start = datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()
    writer = None
    progress(dict(stage='normalize', day=day, events=0, message=f'Rebuilding causal L2 book for {day}'))
    try:
        with zipfile.ZipFile(archive) as zf, zf.open(zf.namelist()[0]) as source:
            for line in source:
                if count % 10000 == 0 and cancelled.is_set():
                    raise InterruptedError('Experiment cancelled during book reconstruction')
                count += 1
                message = json.loads(line)
                if not book.apply(message):
                    continue
                available = message['ts'] / 1000 + 0.250
                if not start <= available < start + 86400:
                    outside += 1
                    continue
                second = int(available)
                if second == last_second:
                    continue
                batch.append(book.row(available))
                emitted += 1
                last_second = second
                if len(batch) >= 2000:
                    if _bytes(HIST_ROOT) + _bytes(EXPERIMENT_ROOT) + 64_000_000 > DATA_CAP:
                        raise ValueError('Insufficient disk reservation for normalized history')
                    table = pa.Table.from_pylist(batch)
                    if writer is None:
                        writer = pq.ParquetWriter(partial_books, table.schema, compression='zstd')
                    writer.write_table(table)
                    batch.clear()
                if count % 50000 == 0:
                    progress(dict(stage='normalize', day=day, events=count, views=emitted,
                                  message=f'Rebuilding {day}: {count:,} source events'))
            if batch:
                table = pa.Table.from_pylist(batch)
                if writer is None:
                    writer = pq.ParquetWriter(partial_books, table.schema, compression='zstd')
                writer.write_table(table)
    finally:
        if writer is not None:
            writer.close()
        if cancelled.is_set():
            partial_books.unlink(missing_ok=True)
            raise InterruptedError('Experiment cancelled during book reconstruction')
    if emitted < 1:
        raise ValueError(f'{day}: no valid order book views reconstructed')
    partial_books.replace(books_path)
    doc = dict(day=day, venue='bybit', symbol='ETHUSDC', market='spot',
               source_url=f'{BASE_URL}/{day}_ETHUSDC_ob200.data.zip',
               archive_bytes=archive.stat().st_size, archive_sha256=sha(archive),
               books_bytes=books_path.stat().st_size, books_sha256=sha(books_path),
               events=count, views=emitted, gaps=book.gaps, snapshots=book.resets,
               duplicates=book.duplicates, outside_window=outside,
               source_depth=200, view_depth=20, view_frequency='first valid event per second',
               timestamp_semantics='exchange event timestamp + assumed 250ms; no measured local receipt timestamp',
               crc_verified=True, created_at=utcnow())
    dump(manifest_path, doc)
    log('experiment_book_normalized', day=day, events=count, views=emitted, gaps=book.gaps,
        archive_sha256=doc['archive_sha256'], books_sha256=doc['books_sha256'])
    return books_path, doc


def _unit_sweep(row: dict, side: str, quantity: D, fee_bps: D) -> dict:
    """检查正数量并调用共用逐档吃单引擎，统一数量和费率格式。

    输入参数：row、side、quantity、fee_bps（单位和范围由下方校验及调用方契约限定）。"""
    if quantity <= 0:
        raise ValueError('Order quantity must be positive')
    return sweep(row, side, format(quantity, 'f'), format(fee_bps, 'f'))


def _budget_sweep(row: dict, side: str, budget: D, fee_bps: D, quantity_step: D) -> dict:
    """在可见深度范围对整数数量步长二分，找含费不超 USDC 预算的最大买入量；预算模式不支持卖单。

    输入参数：row、side、budget、fee_bps、quantity_step（单位和范围由下方校验及调用方契约限定）。"""
    if budget <= 0 or quantity_step <= 0:
        raise ValueError('Budget and quantity step must be positive')
    bids, asks = validate_book(row)
    available = sum((q for _, q in (asks if side == 'buy' else bids)), D(0))
    high = int(available / quantity_step)
    low = 0
    while low < high:
        mid_units = (low + high + 1) // 2
        quote = _unit_sweep(row, side, quantity_step * mid_units, fee_bps)
        spent = D(quote['net_quote']) if side == 'buy' else D(quote['net_quote'])
        # A quote budget is meaningful for buys. Sells are configured by base quantity.
        if side != 'buy':
            raise ValueError('Quote-budget mode is only supported for buys')
        if quote['complete'] and spent <= budget:
            low = mid_units
        else:
            high = mid_units - 1
    if low == 0:
        raise ValueError('Budget is too small for the configured quantity step or book depth')
    result = _unit_sweep(row, side, quantity_step * low, fee_bps)
    if D(result['net_quote']) > budget:
        raise ArithmeticError('Budget constraint violated after rounding')
    return result


def _fill_at(rows: list[dict], exchange_times: list[float], scheduled: float,
             order_latency_ms: int, max_book_age_ms: int) -> tuple[dict | None, float | None, str | None]:
    """按下单时点加延迟，在事件时间序列向后查盘口；缺簿和陈旧分别返回拒单原因。

    输入参数：rows、exchange_times、scheduled、order_latency_ms、max_book_age_ms（单位和范围由下方校验及调用方契约限定）。"""
    target = scheduled + order_latency_ms / 1000
    index = bisect.bisect_right(exchange_times, target) - 1
    if index < 0:
        return None, None, 'no_book_at_or_before_arrival'
    row = rows[index]
    age_ms = (target - exchange_times[index]) * 1000
    if age_ms > max_book_age_ms:
        return None, age_ms, 'stale_book_at_arrival'
    return row, age_ms, None


def _simulate(rows: list[dict], start_ts: float, horizon_seconds: int, side: str,
              amount_mode: str, amount: D, fee_bps: D, order_latency_ms: int,
              max_book_age_ms: int, quantity_step: D, slices: int, policy: str) -> dict:
    """模拟立即或等额父单切片，逐切片计费用、缺量、预算余量与参考价偏差；这是旧 P1 基线，不是求解器。

    输入参数：rows、start_ts、horizon_seconds、side、amount_mode、amount、fee_bps、order_latency_ms、max_book_age_ms、quantity_step、slices、policy（单位和范围由下方校验及调用方契约限定）。"""
    exchange_times = [float(row['exchange_ts']) for row in rows]
    decision, _, reason = _fill_at(rows, exchange_times, start_ts, 0, max_book_age_ms)
    if reason:
        # 决策时刻无有效盘口时仍返回完整结果契约；零成交不产生费用，参考价格和成本不可计算。
        return dict(policy=policy, status='rejected', reason=f'decision_{reason}', fills=[],
                    side=side, amount_mode=amount_mode,
                    requested_base=str(amount) if amount_mode == 'base_quantity' else None,
                    requested_quote=str(amount) if amount_mode == 'quote_budget' else None,
                    filled_base='0', gross_quote='0', fee_quote='0', net_quote='0',
                    unspent_quote=str(amount) if amount_mode == 'quote_budget' else None,
                    remaining_base=str(amount) if amount_mode == 'base_quantity' else None,
                    average_price=None, decision_mid=None,
                    price_shortfall_vs_decision_mid=None,
                    all_in_shortfall_vs_decision_mid=None, all_in_shortfall_bps=None,
                    execution_duration_seconds=0, slices=0)
    decision_mid = mid(decision)
    count = 1 if policy == 'immediate' else slices
    action_duration = max(0, horizon_seconds)
    if amount_mode == 'base_quantity' and count > 1:
        total_units = int(amount / quantity_step)
        base_units, extra_units = divmod(total_units, count)
        if base_units == 0:
            raise ValueError('Base quantity is too small for the selected number of slices at this precision')
        targets = [quantity_step * (base_units + (1 if i < extra_units else 0))
                   for i in range(count)]
    else:
        targets = [amount if count == 1 else amount / count] * count
    gross = D(0)
    fees = D(0)
    filled = D(0)
    fills = []
    for i in range(count):
        scheduled = start_ts if count == 1 else start_ts + (action_duration * i / count)
        row, age_ms, rejection = _fill_at(rows, exchange_times, scheduled,
                                         order_latency_ms, max_book_age_ms)
        reason = rejection
        target_amount = targets[i]
        if amount_mode == 'quote_budget':
            quote = _budget_sweep(row, side, target_amount, fee_bps, quantity_step) if row and not rejection else None
        else:
            quote = _unit_sweep(row, side, target_amount, fee_bps) if row and not rejection else None
        status = 'filled'
        if rejection:
            status, reason = 'rejected', rejection
        elif not quote['complete']:
            status, reason = 'partial', 'visible_depth_insufficient'
        if quote:
            q = D(quote['filled'])
            g = D(quote['quote'])
            f = D(quote['fee'])
            filled += q
            gross += g
            fees += f
            fills.append(dict(index=i + 1, scheduled_at_utc=datetime.fromtimestamp(scheduled, timezone.utc).isoformat(),
                              book_exchange_ts_utc=datetime.fromtimestamp(float(row['exchange_ts']), timezone.utc).isoformat(),
                              book_age_ms=round(float(age_ms), 3), status=status, reason=reason,
                              requested=str(target_amount), filled=str(q), vwap=quote['vwap'],
                              reference_mid=quote['mid'], price_cost_bps=quote['price_cost_bps'],
                              gross_quote=str(g), fee=str(f), levels=quote['steps']))
        else:
            fills.append(dict(index=i + 1,
                              scheduled_at_utc=datetime.fromtimestamp(scheduled, timezone.utc).isoformat(),
                              book_exchange_ts_utc=None, book_age_ms=age_ms, status=status, reason=reason,
                              requested=str(target_amount), filled='0', vwap=None, reference_mid=None,
                              price_cost_bps=None, gross_quote='0', fee='0', levels=[]))
    net_quote = gross + fees if side == 'buy' else gross - fees
    if amount_mode == 'quote_budget':
        left = max(D(0), amount - net_quote)
        # A budget order is maximized at the configured quantity precision.  Any
        # smaller remainder than one additional quantity step per scheduled
        # slice is precision residue, not an unfilled executable order.
        fee_multiplier = D(1) + fee_bps / D(10000)
        rounding_tolerance = D(0)
        for fill in fills:
            levels = fill.get('levels') or []
            if levels:
                marginal_price = D(str(levels[0]['price']))
                rounding_tolerance += quantity_step * marginal_price * fee_multiplier
        complete = left <= rounding_tolerance + D('0.00000001')
        requested_base = None
    else:
        left = max(D(0), amount - filled)
        complete = left <= quantity_step / 2
        requested_base = str(amount)
    if filled:
        shortfall = gross - filled * decision_mid if side == 'buy' else filled * decision_mid - gross
        all_in_shortfall = net_quote - filled * decision_mid if side == 'buy' else filled * decision_mid - net_quote
        avg_px = gross / filled
        all_in_bps = all_in_shortfall / (filled * decision_mid) * D(10000)
    else:
        shortfall = all_in_shortfall = avg_px = all_in_bps = None
    return dict(policy=policy, status='complete' if complete else ('partial' if filled else 'rejected'),
                reason=None if complete else 'unfilled_budget_or_quantity', side=side,
                amount_mode=amount_mode, requested_base=requested_base,
                requested_quote=str(amount) if amount_mode == 'quote_budget' else None,
                filled_base=str(filled), gross_quote=str(gross), fee_quote=str(fees),
                net_quote=str(net_quote), unspent_quote=str(left) if amount_mode == 'quote_budget' else None,
                remaining_base=str(left) if amount_mode == 'base_quantity' else None,
                average_price=str(avg_px) if avg_px is not None else None,
                decision_mid=str(decision_mid), price_shortfall_vs_decision_mid=str(shortfall) if shortfall is not None else None,
                all_in_shortfall_vs_decision_mid=str(all_in_shortfall) if all_in_shortfall is not None else None,
                all_in_shortfall_bps=str(all_in_bps) if all_in_bps is not None else None,
                execution_duration_seconds=action_duration if count > 1 else 0,
                slices=count, fills=fills,
                assumptions=['Historical 1-second first-event decision views; underlying source archive is L2, not L3.',
                             'Uses exchange event timestamps; historical local receive times are unavailable.',
                             'Visible book is treated as available liquidity; queue position and market feedback are not modeled.',
                             'Fees are user-specified; no account fee tier is inferred.'])


def run_experiment(config: dict, progress, cancelled: threading.Event) -> dict:
    """校验市场、时区、规模和最长窗口，逐日准备缓存后运行 P1 立即/分批对照并返回数据质量及完成率报告。

    输入参数：config、progress、cancelled（单位和范围由下方校验及调用方契约限定）。"""
    # 单位必须是内部枚举；拒绝界面文案流入计算，不能将未知预算单位悄悄按 ETH 处理。
    if config['amount_mode'] not in ('quote_budget', 'base_quantity') or config['side'] not in ('buy', 'sell'):
        raise ValueError('Invalid order amount mode or side')
    if config['side'] == 'sell' and config['amount_mode'] != 'base_quantity':
        raise ValueError('Sell orders require an ETH quantity')
    start_date = date.fromisoformat(config['start_date'])
    end_date = date.fromisoformat(config['end_date'])
    day_count = (end_date - start_date).days + 1
    if day_count < 1 or day_count > MAX_WINDOW_DAYS:
        raise ValueError(f'Initial dashboard build supports windows of 1 to {MAX_WINDOW_DAYS} calendar days')
    if config['venue'] not in ('bybit', 'okx') or config['symbol'] != 'ETHUSDC':
        raise ValueError('Execution replay supports Bybit/OKX spot ETH-USDC L2; Binance trade tape is not an order book')
    tz = ZoneInfo(config['timezone'])
    local_start = datetime.combine(start_date, day_time.fromisoformat(config['start_time']), tzinfo=tz)
    start_ts = local_start.timestamp()
    horizon = int(config['horizon_seconds'])
    if horizon < 0 or horizon > 86400:
        raise ValueError('Execution horizon must be between 0 and 24 hours')
    end_ts = start_ts + horizon
    utc_first = datetime.fromtimestamp(start_ts, timezone.utc).date()
    utc_last = datetime.fromtimestamp(max(start_ts, end_ts), timezone.utc).date()
    needed_days = [(utc_first + timedelta(days=i)).isoformat()
                   for i in range((utc_last - utc_first).days + 1)]
    if len(needed_days) > MAX_WINDOW_DAYS:
        raise ValueError('Selected time zone and execution window cross too many UTC dates')
    books, manifests = [], []
    for idx, day in enumerate(needed_days, start=1):
        if cancelled.is_set():
            raise InterruptedError('Experiment cancelled from dashboard')
        progress(dict(stage='data', completed_days=idx - 1, total_days=len(needed_days),
                      day=day, message=f'Preparing verified market data for {day}'))
        path, manifest = _prepare_day(day, progress, cancelled, venue=config['venue'])
        manifests.append(manifest)
        frame = pd.read_parquet(path)
        books.extend(frame.to_dict('records'))
        del frame
    books.sort(key=lambda r: float(r['exchange_ts']))
    if not books:
        raise ValueError('No reconstructed book records in selected dates')
    if start_ts < books[0]['exchange_ts'] or start_ts > books[-1]['exchange_ts']:
        raise ValueError('Selected start time is outside the available historical observations')
    if end_ts > books[-1]['exchange_ts']:
        raise ValueError('Selected execution horizon extends beyond available data; shorten the horizon')
    amount = D(str(config['amount']))
    fee = D(str(config['fee_bps']))
    step = D(str(config['quantity_step']))
    side = config['side']
    if amount <= 0 or fee < 0 or step <= 0:
        raise ValueError('Amount/precision must be positive and fee cannot be negative')
    if config['amount_mode'] == 'quote_budget' and side != 'buy':
        raise ValueError('Quote budget currently applies to buy orders; sell orders use base quantity')
    if config['amount_mode'] == 'base_quantity':
        units = amount / step
        if units != units.to_integral_value():
            raise ValueError('Base quantity must be an exact multiple of the configured research precision step')
    if config['min_completion_pct'] < 0 or config['min_completion_pct'] > 100:
        raise ValueError('Minimum completion threshold must be within 0–100%')
    latency_ms = int(config['order_latency_ms'])
    max_age_ms = int(config['max_book_age_ms'])
    immediate = _simulate(books, start_ts, horizon, side, config['amount_mode'], amount,
                          fee, latency_ms, max_age_ms, step, 1, 'immediate')
    splits = int(config['twap_slices'])
    twap = _simulate(books, start_ts, horizon, side, config['amount_mode'], amount,
                     fee, latency_ms, max_age_ms, step, splits, 'twap_equal_slices')
    for result in (immediate, twap):
        denom = amount if config['amount_mode'] == 'quote_budget' else amount
        done = D(result.get('net_quote', '0')) if config['amount_mode'] == 'quote_budget' else D(result.get('filled_base', '0'))
        result['completion_pct'] = float(min(D(100), max(D(0), done / denom * 100))) if denom else 0.0
        result['meets_minimum_completion'] = result['completion_pct'] >= float(config['min_completion_pct'])
    report = dict(schema_version=1, created_at=utcnow(), config=config,
                  window=dict(start_local=local_start.isoformat(),
                              end_utc=datetime.fromtimestamp(end_ts, timezone.utc).isoformat(),
                              available_utc_days=needed_days),
                  data=dict(venue=config['venue'].upper(), market='Spot ETH/USDC', manifests=manifests,
                            source_frequency='one-second first valid L2 event view',
                            source_events=sum(int(m.get('events', m.get('source_events', 0)) or 0)
                                              for m in manifests),
                            book_views=sum(int(m.get('views', 0)) for m in manifests),
                            simulation_book_views=len(books),
                            gaps=sum(int(m.get('gaps', 0) or 0) for m in manifests),
                            local_receive_timestamp=False),
                  results=dict(immediate=immediate, equal_slice_baseline=twap),
                  solver_status='not_implemented_P2',
                  conclusion='P1 comparison of immediate and equal-slice execution baselines. No optimization solver or limit queue model is included yet.')
    return report


def _job_path(job_id: str) -> Path:
    """校验实验 id 只允许固定长度字母数字，拼接项目内运行目录，阻止路径穿越。

    输入参数：job_id（单位和范围由下方校验及调用方契约限定）。"""
    if not job_id.replace('-', '').isalnum() or len(job_id) != 32:
        raise ValueError('Invalid experiment id')
    return RUN_ROOT / job_id


def _save_job(job: dict) -> None:
    """在锁内更新内存状态副本，再写 job.json，供看板轮询与刷新恢复。

    输入参数：job（单位和范围由下方校验及调用方契约限定）。"""
    with _lock:
        _jobs[job['id']] = job.copy()
    folder = _job_path(job['id'])
    folder.mkdir(parents=True, exist_ok=True)
    dump(folder / 'job.json', job)


def _worker(job_id: str, config: dict, cancel_event: threading.Event) -> None:
    """后台执行单个实验，保存结果并将成功、取消或异常明确记录到状态和事件日志。

    输入参数：job_id、config、cancel_event（单位和范围由下方校验及调用方契约限定）。"""
    folder = _job_path(job_id)
    job = dict(id=job_id, status='running', stage='starting', progress=0.0,
               message='Starting experiment', config=config, created_at=utcnow(), error=None)
    _save_job(job)

    def progress(state: dict) -> None:
        """将数据/下载/规范化回调映射为页面进度和提示，更新持久任务状态。

        输入参数：state（单位和范围由下方校验及调用方契约限定）。"""
        current = dict(job)
        current.update(state)
        current['status'] = 'running'
        if current.get('stage') == 'download':
            expected = max(1, int(current.get('expected_bytes', 1)))
            current['progress'] = min(0.75, 0.05 + 0.60 * int(current.get('bytes', 0)) / expected)
        elif current.get('stage') == 'normalize':
            current['progress'] = 0.70
        elif current.get('stage') == 'data' and current.get('total_days'):
            current['progress'] = min(0.75, 0.05 + 0.65 * int(current.get('completed_days', 0)) /
                                     int(current['total_days']))
        else:
            current['progress'] = max(float(current.get('progress', 0)), 0.80)
        current['updated_at'] = utcnow()
        _save_job(current)

    try:
        report = run_experiment(config, progress, cancel_event)
        dump(folder / 'result.json', report)
        job.update(status='completed', stage='complete', progress=1.0,
                   message='Experiment complete', completed_at=utcnow(),
                   result_path=str(folder / 'result.json'))
        _save_job(job)
        log('execution_experiment_completed', experiment_id=job_id,
            dates=report['window']['available_utc_days'], source='bybit',
            status='completed', solver_status=report['solver_status'])
    except InterruptedError as exc:
        job.update(status='cancelled', stage='cancelled', message=str(exc), completed_at=utcnow())
        _save_job(job)
        log('execution_experiment_cancelled', experiment_id=job_id)
    except Exception as exc:
        job.update(status='failed', stage='failed', message='Experiment failed', error=f'{type(exc).__name__}: {exc}',
                   completed_at=utcnow())
        _save_job(job)
        log('execution_experiment_failed', experiment_id=job_id, error_type=type(exc).__name__, error=str(exc))


def submit(config: dict) -> str:
    """生成新运行 id、取消事件并提交串行线程池；返回 id，不在页面线程执行长下载。

    输入参数：config（单位和范围由下方校验及调用方契约限定）。"""
    job_id = uuid.uuid4().hex
    cancel_event = threading.Event()
    with _lock:
        _cancel[job_id] = cancel_event
    _pool.submit(_worker, job_id, config.copy(), cancel_event)
    return job_id


def get_job(job_id: str) -> dict | None:
    """优先读内存副本，服务重启后回读 job.json；无此任务或标识非法返回 None。

    输入参数：job_id（单位和范围由下方校验及调用方契约限定）。"""
    with _lock:
        job = _jobs.get(job_id)
    if job is not None:
        return job.copy()
    try:
        return read(_job_path(job_id) / 'job.json')
    except (FileNotFoundError, ValueError):
        return None


def get_result(job_id: str) -> dict | None:
    """校验运行 id 后读取已落盘结果，缺文件返回 None。

    输入参数：job_id（单位和范围由下方校验及调用方契约限定）。"""
    try:
        path = _job_path(job_id) / 'result.json'
        return read(path) if path.exists() else None
    except ValueError:
        return None


def cancel(job_id: str) -> bool:
    """给本进程仍可控制的任务设置取消事件并更新提示；进程已丢失的任务不会伪造取消成功。

    输入参数：job_id（单位和范围由下方校验及调用方契约限定）。"""
    with _lock:
        event = _cancel.get(job_id)
    if not event:
        return False
    event.set()
    job = get_job(job_id)
    if job and job.get('status') == 'running':
        job.update(message='Cancellation requested', updated_at=utcnow())
        _save_job(job)
    return True


def recent_jobs(limit: int = 20) -> list[dict]:
    """枚举已保存任务状态，跳过损坏记录，按创建时间返回最近记录供看板历史列表。

    输入参数：limit（单位和范围由下方校验及调用方契约限定）。"""
    items = []
    if not RUN_ROOT.exists():
        return items
    for path in RUN_ROOT.iterdir():
        if path.is_dir() and (path / 'job.json').exists():
            try:
                items.append(read(path / 'job.json'))
            except Exception:
                continue
    return sorted(items, key=lambda j: j.get('created_at', ''), reverse=True)[:limit]
