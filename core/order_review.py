"""用户成交记录映射与复盘：核算真实成交成本，不把假设成交写成真实成交。"""
from decimal import Decimal,InvalidOperation
import pandas as pd
from .io import utcnow


def normalize_fills(frame,mapping,timezone_name='UTC',venue='bybit'):
    """映射时间/方向/ETH量/USDC价格/USDC费用，拒绝非有限数、非法方向、重复成交与缺列。"""
    if len(frame)==0 or len(frame)>5000:raise ValueError('Upload 1–5000 trade rows')
    required={'timestamp','side','quantity','price','fee'}
    if not required.issubset(mapping) or any(mapping[k] not in frame.columns for k in required):
        raise ValueError('Map time, direction, quantity, price and fee columns')
    if len({mapping[k] for k in required})!=5:raise ValueError('Each required field must map to a different column')
    if venue not in ('bybit','okx'):raise ValueError('Trade review currently supports Bybit/OKX ETH-USDC only')
    records=[];identifiers=set()
    for index,row in frame.iterrows():
        stamp=pd.Timestamp(row[mapping['timestamp']])
        if pd.isna(stamp):raise ValueError(f'Missing trade time at row {index+1}')
        stamp=stamp.tz_localize(timezone_name,ambiguous='raise',nonexistent='raise') if stamp.tzinfo is None else stamp
        side=str(row[mapping['side']]).strip().lower()
        if side not in ('buy','sell'):raise ValueError(f'Trade direction must be buy/sell at row {index+1}')
        values={}
        for field in ('quantity','price','fee'):
            try:value=Decimal(str(row[mapping[field]]))
            except InvalidOperation:raise ValueError(f'Invalid {field} at row {index+1}') from None
            if not value.is_finite() or value<0 or (field!='fee' and value==0):
                raise ValueError(f'Invalid {field} at row {index+1}')
            values[field]=str(value)
        identifier=str(row[mapping['id']]) if mapping.get('id') else str(index+1)
        if identifier in identifiers:raise ValueError(f'Duplicate trade identifier: {identifier}')
        identifiers.add(identifier)
        records.append(dict(id=identifier,timestamp=stamp.tz_convert('UTC').isoformat(),side=side,venue=venue,**values))
    return sorted(records,key=lambda row:row['timestamp'])


def review_fills(records):
    """按用户提供的成交量、价格和USDC费计算分方向均价与资金流；不推断未上传订单或钱包盈亏。"""
    # 再次验证队列中保存的记录，避免导入后通过篡改配置跳过单位与数值检查。
    frame=pd.DataFrame(records)
    if frame.empty:raise ValueError('Trade records are empty')
    if len(set(frame.venue))!=1:raise ValueError('Review one exchange at a time')
    verified=normalize_fills(frame,{k:k for k in ('timestamp','side','quantity','price','fee','id')},'UTC',str(frame.venue.iloc[0]))
    summary=[];net_quote=Decimal(0);net_base=Decimal(0)
    for side in ('buy','sell'):
        rows=[r for r in verified if r['side']==side]
        if not rows:continue
        quantity=sum((Decimal(r['quantity']) for r in rows),Decimal(0))
        gross=sum((Decimal(r['quantity'])*Decimal(r['price']) for r in rows),Decimal(0))
        fees=sum((Decimal(r['fee']) for r in rows),Decimal(0))
        quote=-(gross+fees) if side=='buy' else gross-fees
        net_quote+=quote;net_base+=quantity if side=='buy' else -quantity
        summary.append(dict(side=side,trades=len(rows),quantity=str(quantity),average_price=str(gross/quantity),fee_quote=str(fees),net_quote_change=str(quote),all_in_unit_price=str((gross+fees if side=='buy' else gross-fees)/quantity)))
    return dict(created_at=utcnow(),source='user_uploaded_fills',venue=verified[0]['venue'],symbol='ETH/USDC',
        first_trade=verified[0]['timestamp'],last_trade=verified[-1]['timestamp'],summary=summary,fills=verified,
        net_quote_change=str(net_quote),net_base_change=str(net_base),fee_currency='USDC',
        scope='Uploaded fills only; cash flows are not account profit or evidence of unfilled orders')
