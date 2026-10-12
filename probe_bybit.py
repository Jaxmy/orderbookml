"""组件用途：Bybit公共行情和元数据检查。"""
import re
import requests
from core.io import dump, ROOT

BASE = 'https://quote-saver.bycsi.com/orderbook/spot/ETHUSDC/'
if __name__ == '__main__':
    r = requests.get(BASE, timeout=30)
    r.raise_for_status()
    names = re.findall(r'href="([^"]+\.data\.zip)"', r.text)
    selected = [n for n in names if n.startswith(('2026-09-01_', '2026-09-02_', '2026-09-03_'))]
    result = {'directory': BASE, 'latest': names[-5:], 'files': []}
    for name in selected:
        with requests.get(BASE+name, headers={'Range':'bytes=0-1023'}, stream=True, timeout=30) as x:
            head = next(x.iter_content(1024), b'')
            result['files'].append({'url':BASE+name, 'status':x.status_code,
                'length':x.headers.get('Content-Length'), 'range':x.headers.get('Content-Range'),
                'magic':head[:4].hex()})
    dump(ROOT/'logs'/'bybit_history_probe.json', result)
    print(result)
