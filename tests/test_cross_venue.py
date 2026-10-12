import io
import json
import shutil
import tarfile
import uuid
from datetime import date, datetime, time, timezone

import pandas as pd
import pytest

from core import cross_venue, okx_orderbook
from core.io import ROOT, dump, sha


@pytest.fixture
def tmp_path():
    """为测试建立工作区内唯一临时目录，避开Windows系统临时目录权限问题，不删除历史证据。"""
    allowed = ROOT / 'data' / 'experiments' / 'test_artifacts'
    allowed.mkdir(parents=True, exist_ok=True)
    folder = allowed / f'cross-venue-{uuid.uuid4().hex}'
    folder.mkdir()
    try:
        yield folder
    finally:
        resolved = folder.resolve()
        resolved.relative_to(allowed.resolve())
        shutil.rmtree(resolved)


def test_okx_archive_snapshot_and_delta_rebuild(tmp_path, monkeypatch):
    """验证OKX档案快照、增量与零量删除；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。

    输入参数：tmp_path、monkeypatch（单位和范围由下方校验及调用方契约限定）。"""
    day = '2026-10-01'
    market_root = tmp_path / 'market'
    monkeypatch.setattr(okx_orderbook, 'MARKET_ROOT', market_root)
    monkeypatch.setattr(okx_orderbook, 'DATA_ROOT', tmp_path)
    start = datetime.combine(date.fromisoformat(day), time.min, tzinfo=timezone.utc).timestamp()
    rows = [
        dict(instId='ETH-USDC', action='snapshot', ts=str(int((start + .1) * 1000)),
             bids=[['100', '2', '1'], ['99', '3', '1']],
             asks=[['101', '2', '1'], ['102', '3', '1']]),
        dict(instId='ETH-USDC', action='update', ts=str(int((start + 1.1) * 1000)),
             bids=[['100', '2', '1']],
             asks=[['101', '0', '0'], ['100.5', '1', '1']]),
    ]
    body = ''.join(json.dumps(row) + '\n' for row in rows).encode()
    folder = market_root / 'okx' / 'ETH-USDC' / day
    folder.mkdir(parents=True)
    archive_path = folder / 'source.tar.gz'
    member = f'ETH-USDC-L2orderbook-400lv-{day}.data'
    with tarfile.open(archive_path, 'w:gz') as archive:
        info = tarfile.TarInfo(member)
        info.size = len(body)
        archive.addfile(info, io.BytesIO(body))

    book_path, manifest = okx_orderbook.normalize_okx_archive(day, assumed_latency_ms=0)
    books = pd.read_parquet(book_path)
    assert manifest['source_events'] == 2
    assert manifest['snapshots'] == 1
    assert manifest['updates'] == 1
    assert manifest['out_of_order_events'] == 0
    assert len(books) == 2
    assert json.loads(books.iloc[1].asks_json) == [['100.5', '1'], ['102', '3']]


def test_cross_venue_sweep_applies_both_fees(tmp_path, monkeypatch):
    """验证跨所双腿手续费分别计算；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。

    输入参数：tmp_path、monkeypatch（单位和范围由下方校验及调用方契约限定）。"""
    day = '1970-01-01'
    market_root = tmp_path / 'market'
    monkeypatch.setattr(cross_venue, 'MARKET_ROOT', market_root)
    monkeypatch.setattr(cross_venue, 'CROSS_ROOT', tmp_path / 'cross')

    books = {
        'bybit': dict(bids_json=json.dumps([['99', '2']]),
                      asks_json=json.dumps([['100', '2']])),
        'okx': dict(bids_json=json.dumps([['101', '2']]),
                    asks_json=json.dumps([['102', '2']])),
    }
    for venue, row in books.items():
        native = 'ETH-USDC' if venue == 'okx' else 'ETHUSDC'
        folder = market_root / venue / native / day
        folder.mkdir(parents=True)
        path = folder / 'books.parquet'
        pd.DataFrame([dict(exchange_ts=1000.1, **row)]).to_parquet(path, index=False)
        dump(folder / 'manifest.json', dict(day=day, venue=venue, books_sha256=sha(path)))

    trade_dir = market_root / 'binance' / 'ETHUSDC' / day
    trade_dir.mkdir(parents=True)
    trade_path = trade_dir / 'trades.parquet'
    pd.DataFrame([dict(exchange_ts=1000.1, price='100.2', quantity='0.1',
                       quote_quantity='10.02', aggressor_side='buy', trade_id='1')]).to_parquet(
                           trade_path, index=False)
    dump(trade_dir / 'trades_manifest.json', dict(trades_sha256=sha(trade_path)))

    result_path, report = cross_venue.analyze_cross_venue(
        day, quantity_eth='1', bybit_fee_bps='10', okx_fee_bps='10',
        assumed_latency_ms=0, max_book_age_ms=1000)
    assert result_path.exists()
    assert report['arbitrage']['buy_bybit_sell_okx']['positive_points'] == 1
    assert abs(report['arbitrage']['buy_bybit_sell_okx']['best_single_snapshot_net_usdc'] - .799) < 1e-9
    assert report['arbitrage']['buy_okx_sell_bybit']['positive_points'] == 0


def test_binance_trade_reference_never_uses_a_future_trade(tmp_path):
    """验证Binance参照成交严格向后匹配；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。

    输入参数：tmp_path（单位和范围由下方校验及调用方契约限定）。"""
    trades = pd.DataFrame([
        dict(exchange_ts=100.0, price='100', quantity='1', quote_quantity='100',
             aggressor_side='buy', trade_id='known'),
        dict(exchange_ts=101.5, price='999', quantity='1', quote_quantity='999',
             aggressor_side='buy', trade_id='future'),
    ])
    trade_path = tmp_path / 'trades.parquet'
    trades.to_parquet(trade_path, index=False)
    aligned = pd.DataFrame([
        dict(evaluation_at=100.5, bybit_mid=100.0, okx_mid=100.0),
        dict(evaluation_at=101.2, bybit_mid=100.0, okx_mid=100.0),
    ])
    result = cross_venue._asof_trade_context(aligned, trade_path, latency_ms=100,
                                             max_age_ms=3000)
    assert list(result.price) == ['100', '100']
    assert result.binance_trade_age_ms.iloc[1] > 1000
