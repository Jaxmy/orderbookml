"""组件用途：生成带 UTC 时区的当前时间字符串，作为日志、清单和实验创建时间；不代表交易所事件时间。；以 1MB 分块读取文件并累计 SHA-256；返回十六进制摘要，避免把整个归档加载入内存。。"""
import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def utcnow():
    """生成带 UTC 时区的当前时间字符串，作为日志、清单和实验创建时间；不代表交易所事件时间。"""
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    """以 1MB 分块读取文件并累计 SHA-256；返回十六进制摘要，避免把整个归档加载入内存。

    输入参数：path（单位和范围由下方校验及调用方契约限定）。"""
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def dump(path, value):
    """创建目标父目录，把对象写为 UTF-8 JSON；禁止 NaN/Infinity，非 JSON 原生类型转字符串。会覆盖指定文件，调用方负责冻结目录保护。

    输入参数：path、value（单位和范围由下方校验及调用方契约限定）。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False, default=str), encoding='utf-8')


def read(path):
    """读取指定 UTF-8 JSON 并反序列化；文件不存在或格式损坏时向调用方抛错。

    输入参数：path（单位和范围由下方校验及调用方契约限定）。"""
    return json.loads(Path(path).read_text(encoding='utf-8'))


def code_hash():
    """按文件名顺序把根目录和 core 的 Python 文件名及字节纳入摘要；注释修改也改变版本摘要。"""
    h = hashlib.sha256()
    files = list(ROOT.glob('*.py')) + list((ROOT / 'core').glob('*.py'))
    for p in sorted(files):
        h.update(p.relative_to(ROOT).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def manifest(folder, kind, start, end, config, errors=None, extra=None):
    """统计当前目录 Parquet/JSONL 的哈希，加入窗口、配置、版本和错误后写 manifest.json；原始来源说明属于早期采集流程。

    输入参数：folder、kind、start、end、config、errors、extra（单位和范围由下方校验及调用方契约限定）。"""
    folder = Path(folder)
    files = {p.name: sha(p) for p in folder.iterdir() if p.is_file() and p.suffix in ('.parquet', '.jsonl')}
    doc = dict(schema_version=1, kind=kind, start=start, end=end, created_at=utcnow(),
               code_sha256=code_hash(), python=platform.python_version(), config=config,
               files=files, errors=errors or [], sources={'cex': 'Binance partial depth 20',
               'dex': 'Uniswap V3 QuoterV2 eth_call', 'deployments': 'https://developers.uniswap.org/deployments'})
    doc.update(extra or {})
    dump(folder / 'manifest.json', doc)
    return doc


def verified_manifest(path):
    """读取清单并逐文件验证摘要，阻止清单路径逃出父目录；任一内容不符即拒绝继续分析。

    输入参数：path（单位和范围由下方校验及调用方契约限定）。"""
    p = Path(path).resolve()
    m = read(p)
    for name, expected in m['files'].items():
        child = (p.parent / name).resolve()
        if child.parent != p.parent or sha(child) != expected:
            raise ValueError(f'Data integrity failure: {name}')
    return m


def log(event, **details):
    """追加一行带 UTC 时间和事件字段的 JSON 日志，不改写既有事件；调用方不得传入敏感凭据。

    输入参数：event（单位和范围由下方校验及调用方契约限定）。"""
    p = ROOT / 'logs' / 'events.jsonl'
    p.parent.mkdir(exist_ok=True)
    with p.open('a', encoding='utf-8') as f:
        f.write(json.dumps(dict(time=utcnow(), event=event, **details), ensure_ascii=False, default=str) + '\n')
