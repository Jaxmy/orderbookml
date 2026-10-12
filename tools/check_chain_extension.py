"""只读验证链上新组件；只打印公共节点响应摘要，不打印环境变量或凭据。"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import requests
from core.chain_history import extract_events,compare_channels

try:
    result=extract_events('2026-10-01T12:00:00+00:00','2026-10-01T12:01:00+00:00')
    print({key:result[key] for key in ['event_count','counts','last_block','events_path']})
except requests.HTTPError as error:
    print('event_download_http',error.response.status_code,error.response.text[:800])
except Exception as error:
    print('event_download_error',type(error).__name__,str(error)[:400])
try:
    result=compare_channels('2026-10-01','12:00:00','buy','.3',{'bybit':10,'okx':10},weth_accepted=True)
    print({key:result[key] for key in ['rows','block','gas_eth']})
except requests.HTTPError as error:
    print('comparison_http',error.response.status_code,error.response.text[:800])
except Exception as error:
    print('comparison_error',type(error).__name__,str(error)[:400])
