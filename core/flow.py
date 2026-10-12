"""组件用途：按时间桶汇总成交量、名义额、主动方向和RPI占比；桶结束才标为可用，避免提前读取整桶未来成交。。

原始说明：Trade-flow aggregates become available only after their bucket closes."""
import numpy as np
import pandas as pd

def aggregate_trades(trades,seconds=3600):
    """按时间桶汇总成交量、名义额、主动方向和RPI占比；桶结束才标为可用，避免提前读取整桶未来成交。

    输入参数：trades、seconds（单位和范围由下方校验及调用方契约限定）。"""
    if seconds<=0: raise ValueError('Invalid interval')
    if not trades.side.isin(['buy','sell']).all() or (trades.volume<=0).any() or (trades.price<=0).any():
        raise ValueError('Invalid trade')
    x=trades.copy()
    x['bucket_start']=np.floor(x.available_at/seconds)*seconds
    x['notional']=x.price*x.volume
    x['signed_volume']=np.where(x.side=='buy',x.volume,-x.volume)
    x['rpi_volume']=np.where(x.rpi.astype(bool),x.volume,0)
    grouped=x.groupby('bucket_start').agg(trades=('price','size'),volume_eth=('volume','sum'),
        notional_usdc=('notional','sum'),signed_volume_eth=('signed_volume','sum'),rpi_volume_eth=('rpi_volume','sum')).reset_index()
    grouped['available_at']=grouped.bucket_start+seconds
    grouped['vwap']=grouped.notional_usdc/grouped.volume_eth
    grouped['flow_imbalance']=grouped.signed_volume_eth/grouped.volume_eth
    return grouped
