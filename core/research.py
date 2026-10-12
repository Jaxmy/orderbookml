"""组件用途：同时约束特征时刻、标签终点和标签实际可用时间归属分区，剔除跨界样本。；建立两种岭回归和两种提升树的固定候选，标准化随Pipeline只在拟合输入上学习。。

原始说明：Chronological research: fitting and final scoring are separate commands."""
import numpy as np
import pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error
from .model import FEATURES, features

def partition(frame, start, end):
    # Label endpoint and actual observed source must both belong to this partition.
    """同时约束特征时刻、标签终点和标签实际可用时间归属分区，剔除跨界样本。

    输入参数：frame、start、end（单位和范围由下方校验及调用方契约限定）。"""
    return frame[(frame.t>=start)&(frame.target_t<end)&(frame.target_available_at<end)].copy()

def candidates():
    """建立两种岭回归和两种提升树的固定候选，标准化随Pipeline只在拟合输入上学习。"""
    return {
        'ridge_1':make_pipeline(StandardScaler(),Ridge(alpha=1)),
        'ridge_10':make_pipeline(StandardScaler(),Ridge(alpha=10)),
        'tree_7':HistGradientBoostingRegressor(max_iter=100,max_leaf_nodes=7,min_samples_leaf=100,early_stopping=False,random_state=42),
        'tree_15':HistGradientBoostingRegressor(max_iter=100,max_leaf_nodes=15,min_samples_leaf=100,early_stopping=False,random_state=42),
    }

def build_features(books,start,end):
    """复用旧盘口特征再加入未来波动标签和过去波动基线，校验向后时间对齐；标签不进入 FEATURES。

    输入参数：books、start、end（单位和范围由下方校验及调用方契约限定）。"""
    frame=features(books,start,end)
    if frame.empty:
        return frame
    # Forward realized volatility is a LABEL ONLY; no shifted series enters FEATURES.
    raw=books[['available_at','bids_json','asks_json']].copy()
    import json
    raw['mid']=[(float(json.loads(b)[0][0])+float(json.loads(a)[0][0]))/2 for b,a in zip(raw.bids_json,raw.asks_json)]
    grid=pd.merge_asof(pd.DataFrame({'t':np.arange(start,end,dtype=float)}),
        raw[['available_at','mid']].sort_values('available_at'),left_on='t',right_on='available_at',direction='backward',tolerance=3)
    returns=grid.mid.pct_change(fill_method=None)
    grid['vol_target']=returns.rolling(60,min_periods=60).std().shift(-60)*10000
    frame=frame.merge(grid[['t','vol_target']],on='t',validate='one_to_one').dropna(subset=['vol_target'])
    frame['vol_baseline']=frame.vol60*10000
    if not ((frame.available_at<=frame.t)&(frame.target_available_at<=frame.target_t)).all():
        raise ValueError('As-of causality violated')
    return frame

def score(y,pred,base,t):
    """计算模型与基线绝对误差差值，并以小时块bootstrap生成区间，减少重叠标签造成的虚假独立性；仅限给定样本。

    输入参数：y、pred、base、t（单位和范围由下方校验及调用方契约限定）。"""
    errors=np.abs(np.asarray(y)-pred)
    baseline_errors=np.abs(np.asarray(y)-base)
    delta=errors-baseline_errors
    # Hour blocks avoid treating highly overlapping 60s targets as independent samples.
    blocks=pd.DataFrame({'hour':np.asarray(t)//3600,'delta':delta}).groupby('hour').delta.agg(['sum','count']).to_numpy()
    rng=np.random.default_rng(42)
    samples=[blocks[rng.integers(0,len(blocks),size=len(blocks))].sum(axis=0) for _ in range(1000)]
    boots=[total/n for total,n in samples]
    return dict(n=len(y),mae=float(errors.mean()),baseline_mae=float(baseline_errors.mean()),
        delta_mae=float(delta.mean()),hour_block_delta_ci95=list(map(float,np.quantile(boots,[.025,.975]))),
        ci_warning='Conditional on this seven-day sample; not long-term generalization evidence')

TASKS={'execution_cost':('y','cost_now'),'volatility':('vol_target','vol_baseline')}
