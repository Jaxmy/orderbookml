"""通过实际本机 HTTP API 提交历史静态分配，验证持久队列到真实报告的闭环。"""
import time
import sys
import requests
payload=dict(kind='static',config=dict(day='2026-10-01',utc_time='12:00:00',side='buy',amount_mode='base_quantity',amount='.3',fees_bps={'bybit':10,'okx':10},quote_balances={'bybit':'5000','okx':'5000'},base_balances={'bybit':'1','okx':'1'}))
if len(sys.argv)>1 and sys.argv[1]=='channels':
    payload=dict(kind='channels',config=dict(day='2026-10-01',utc_time='12:00:00',side='buy',quantity='.3',fees_bps={'bybit':10,'okx':10},weth_accepted=True))
response=requests.post('http://127.0.0.1:8010/experiments',json=payload,timeout=15);response.raise_for_status();identifier=response.json()['id']
for attempt in range(60):
    response=requests.get('http://127.0.0.1:8010/experiments/'+identifier,timeout=15);response.raise_for_status();task=response.json()
    if task['status'] not in ('queued','running'):break
    time.sleep(1)
print(dict(id=identifier,status=task['status'],error=task['error'],result=(task['result'] or {}).get('result',(task['result'] or {}).get('rows'))))
response=requests.get('http://127.0.0.1:8502/_stcore/health',timeout=15);print('dashboard_health',response.status_code,response.text)
