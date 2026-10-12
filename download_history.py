"""组件用途：累计历史研究存储占用，供归档下载前后容量检查。；按固定研究清单下载公开Bybit日档，流式检查长度、CRC和容量，保存来源摘要；已有冻结归档只复用。。

原始说明：Bounded public downloads; never extract an uncompressed archive to disk."""
import json
import zipfile
import requests
from core.io import ROOT, read, dump, sha, utcnow

HOME = ROOT/'data'/'historical'

def usage():
    """累计历史研究存储占用，供归档下载前后容量检查。"""
    return sum(p.stat().st_size for p in HOME.rglob('*') if p.is_file())

def main():
    """按固定研究清单下载公开Bybit日档，流式检查长度、CRC和容量，保存来源摘要；已有冻结归档只复用。"""
    cfg = read(ROOT/'history.json')
    HOME.mkdir(parents=True, exist_ok=True)
    lock = HOME/'download.lock'
    with lock.open('x') as lock_handle:
        try:
            for day in cfg['dates']:
                name = f'{day}_{cfg["symbol"]}_ob200.data.zip'
                path = HOME/name
                if path.exists():
                    print('cached', name, flush=True)
                    continue
                url = f'https://quote-saver.bycsi.com/orderbook/spot/{cfg["symbol"]}/{name}'
                partial = path.with_suffix('.part')
                if partial.exists():
                    raise ValueError(f'Incomplete download requires inspection: {partial}')
                with requests.get(url, stream=True, timeout=(15,60)) as r:
                    r.raise_for_status()
                    length = int(r.headers.get('Content-Length',0))
                    archives = sum(p.stat().st_size for p in HOME.glob('*.zip'))
                    if not length or archives+length > cfg['archive_cap_bytes']:
                        raise ValueError('Unknown length or archive budget exceeded')
                    if usage()+length > min(cfg['storage_cap_bytes'],4_000_000_000):
                        raise ValueError('5 GB budget exceeded')
                    written = 0
                    with partial.open('xb') as f:
                        for block in r.iter_content(1024*1024):
                            if written+len(block)>length or usage()+len(block)>min(cfg['storage_cap_bytes'],4_000_000_000):
                                raise ValueError('Download exceeded reserved capacity')
                            f.write(block)
                            written += len(block)
                    if written != length:
                        raise ValueError('Truncated response')
                with zipfile.ZipFile(partial) as z:
                    if len(z.infolist()) != 1 or z.infolist()[0].file_size > 4_000_000_000:
                        raise ValueError('Unexpected archive layout or expansion')
                    # Streaming CRC validation also occurs when the parser reaches EOF.
                    with z.open(z.namelist()[0]) as f:
                        first = json.loads(f.readline())
                    if first['data']['s'] != cfg['symbol']:
                        raise ValueError('Wrong symbol')
                partial.rename(path)
                dump(HOME/(day+'.source.json'),dict(url=url,bytes=written,sha256=sha(path),
                    downloaded_at=utcnow(),first_type=first.get('type'),first_ts=first.get('ts')))
                print(day, written, 'bytes', 'first:', str(first)[:220], flush=True)
            dump(HOME/'download_manifest.json',dict(config=cfg,config_sha256=sha(ROOT/'history.json'),
                files={p.name:sha(p) for p in HOME.glob('*.zip')},total_bytes=usage(),created_at=utcnow()))
        finally:
            lock_handle.close()
            lock.unlink()

if __name__ == '__main__':
    main()
