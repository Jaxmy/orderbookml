"""组件用途：按哈希验证原始日档，流式重建每个增量，批量输出秒级前二十档视图；不覆盖旧规范化文件。。

原始说明：Replay every raw delta; save causal one-second decision views in bounded batches."""
import json
import zipfile
import pyarrow as pa
import pyarrow.parquet as pq
from datetime import datetime
from core.io import ROOT, read, dump, sha, utcnow
from core.orderbook import OrderBook
from download_history import HOME, usage

def main():
    """按哈希验证原始日档，流式重建每个增量，批量输出秒级前二十档视图；不覆盖旧规范化文件。"""
    cfg = read(ROOT/'history.json')
    source = read(HOME/'download_manifest.json')
    if source['config_sha256'] != sha(ROOT/'history.json'):
        raise ValueError('Research specification changed after download')
    results = []
    for day in cfg['dates']:
        archive = HOME/f'{day}_{cfg["symbol"]}_ob200.data.zip'
        if sha(archive) != source['files'][archive.name]:
            raise ValueError('Archive hash mismatch')
        target = HOME/(day+'.books.parquet')
        if target.exists():
            raise ValueError('Refuse to overwrite normalized research data')
        book = OrderBook(cfg['symbol'])
        writer, batch, count, emitted, last_second = None, [], 0, 0, None
        start = datetime.fromisoformat(day+'T00:00:00+00:00').timestamp()
        outside = 0
        try:
            with zipfile.ZipFile(archive) as z, z.open(z.namelist()[0]) as stream:
                for line in stream:
                    msg = json.loads(line)
                    count += 1
                    if not book.apply(msg):
                        continue
                    available = msg['ts']/1000+cfg['assumed_feed_latency_ms']/1000
                    if not start <= available < start+86400:
                        outside += 1
                        continue
                    second = int(available)
                    if second == last_second:
                        continue
                    batch.append(book.row(available))
                    emitted += 1
                    last_second = second
                    if len(batch)>=2000:
                        if usage()+64_000_000>min(cfg['storage_cap_bytes'],4_000_000_000):
                            raise ValueError('Insufficient storage reservation')
                        table = pa.Table.from_pylist(batch)
                        if writer is None:
                            writer = pq.ParquetWriter(target,table.schema,compression='zstd')
                        writer.write_table(table)
                        batch.clear()
                if batch:
                    if usage()+64_000_000>min(cfg['storage_cap_bytes'],4_000_000_000):
                        raise ValueError('Insufficient storage reservation')
                    table = pa.Table.from_pylist(batch)
                    if writer is None:
                        writer = pq.ParquetWriter(target,table.schema,compression='zstd')
                    writer.write_table(table)
        finally:
            if writer:
                writer.close()
        result = dict(day=day,events=count,views=emitted,gaps=book.gaps,
            snapshots=book.resets,duplicates=book.duplicates,outside_window=outside,
            sha256=sha(target),coverage_seconds=emitted/86400)
        results.append(result)
        dump(HOME/(day+'.quality.json'),result)
        print(result,flush=True)
    dump(HOME/'normalized_manifest.json',dict(kind='historical',venue='bybit',symbol=cfg['symbol'],
        config=cfg,created_at=utcnow(),days=results,total_bytes=usage(),
        timestamp_semantics='exchange system time + assumed 250ms; first event per second; no measured local timestamps',
        raw_depth=200,view_depth=20,archive_crc_verified=True))

if __name__ == '__main__':
    main()
