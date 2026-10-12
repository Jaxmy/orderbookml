"""组件用途：重建秒格的过去收益/波动、五档盘口与当前半ETH买单成本；未来六十秒成本仅作y标签。在线模式允许无标签但必须有完整过去窗口。；按先训练、后验证、最后测试切分时间，移除未来标签跨越下一边界的锚点。。"""
import os
os.environ.setdefault('OMP_NUM_THREADS', '1')
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error
from threadpoolctl import threadpool_limits
from .execution import sweep, validate_book
from .quality import asof_index
from .io import dump, sha, utcnow, code_hash, read

FEATURES = ['spread_bps', 'bid_depth5', 'ask_depth5', 'imbalance5', 'cost_now', 'return10', 'return60', 'vol60']


def features(books, start, end, include_unlabeled=False):
    """重建秒格的过去收益/波动、五档盘口与当前半ETH买单成本；未来六十秒成本仅作y标签。在线模式允许无标签但必须有完整过去窗口。

    输入参数：books、start、end、include_unlabeled（单位和范围由下方校验及调用方契约限定）。"""
    rows = []
    for r in books.to_dict('records'):
        bids, asks = validate_book(r)
        q = sweep(r, 'buy', '.5', '0')
        bq, aq = sum(float(x[1]) for x in bids[:5]), sum(float(x[1]) for x in asks[:5])
        rows.append(dict(available_at=r['available_at'], source_id=r['id'], mid=float(q['mid']),
                         spread_bps=float((asks[0][0]-bids[0][0])/__import__('decimal').Decimal(q['mid'])*10000),
                         bid_depth5=sum(float(p*v) for p,v in bids[:5]),
                         ask_depth5=sum(float(p*v) for p,v in asks[:5]), imbalance5=(bq-aq)/(bq+aq),
                         cost_now=float(q['price_cost_bps']) if q['complete'] else np.nan))
    if not rows:
        return pd.DataFrame(columns=['t', 'target_t', 'label_source_id', 'target_available_at', 'y'] + FEATURES)
    raw = pd.DataFrame(rows).sort_values('available_at')
    grid = pd.DataFrame({'t': np.arange(start, end, 1, dtype=float)})
    grid = pd.merge_asof(grid, raw, left_on='t', right_on='available_at', direction='backward', tolerance=3)
    grid['return10'] = grid.mid / grid.mid.shift(10) - 1
    grid['return60'] = grid.mid / grid.mid.shift(60) - 1
    grid['vol60'] = grid.mid.pct_change(fill_method=None).rolling(60, min_periods=60).std()
    grid['valid_window'] = grid.cost_now.notna().rolling(61, min_periods=61).sum().eq(61)
    grid['y'] = grid.cost_now.shift(-60)
    grid['target_t'] = grid.t + 60
    grid['target_available_at'] = grid.available_at.shift(-60)
    grid['label_source_id'] = grid.source_id.shift(-60)
    selected = grid.iloc[::10].copy()
    selected = selected[selected.valid_window].dropna(subset=FEATURES+([] if include_unlabeled else ['y']))
    return selected.reset_index(drop=True)


def split(frame, start):
    # Purge ALL anchors whose label horizon would meet/cross the next partition.
    """按先训练、后验证、最后测试切分时间，移除未来标签跨越下一边界的锚点。

    输入参数：frame、start（单位和范围由下方校验及调用方契约限定）。"""
    train = frame[(frame.t < start+10800) & (frame.target_t < start+10800)]
    valid = frame[(frame.t >= start+10800) & (frame.target_t < start+14400)]
    test = frame[frame.t >= start+14400]
    return train, valid, test


def metrics(y, predicted, baseline):
    """计算MAE、RMSE及目标尾部误差，与持平基线比较；基线为零时改善百分比返回None而非Infinity。

    输入参数：y、predicted、baseline（单位和范围由下方校验及调用方契约限定）。"""
    y, predicted, baseline = map(np.asarray, (y, predicted, baseline))
    err = mean_absolute_error(y, predicted)
    base = mean_absolute_error(y, baseline)
    tail = y >= np.quantile(y, .9)
    return dict(n=len(y), mae_bps=float(err), rmse_bps=float(mean_squared_error(y, predicted)**.5),
                tail_mae_bps=float(np.abs(y[tail]-predicted[tail]).mean()),
                target_std_bps=float(np.std(y)), delta_mae_vs_baseline=float(err-base),
                improvement_pct=float(100*(base-err)/base) if base > 0 else None)


def evaluate(frame, models, out, label):
    """用给定已训练模型和基线预测，保存逐样本结果、误差及最差案例，不重训。

    输入参数：frame、models、out、label（单位和范围由下方校验及调用方契约限定）。"""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    result, pred = {}, frame.copy()
    with threadpool_limits(limits=1):
        for name in ['baseline']+list(models):
            values = frame.cost_now.to_numpy() if name == 'baseline' else models[name].predict(frame[FEATURES])
            result[name] = metrics(frame.y, values, frame.cost_now)
            pred[name] = values
    pred.to_parquet(out / f'{label}_predictions.parquet', index=False)
    dump(out / f'{label}_metrics.json', result)
    failures = {}
    for name in models:
        worst = pred.assign(abs_error=(pred[name]-pred.y).abs()).nlargest(3, 'abs_error')
        failures[name] = json.loads(worst.to_json(orient='records'))
    dump(out / f'{label}_failures.json', failures)
    return result


def train(frame, start, folder, data_manifest):
    """在训练区拟合候选，在验证区选参数；样本不足明确返回。先冻结权重/清单，再评价内部测试，拒绝覆盖冻结模型。

    输入参数：frame、start、folder、data_manifest（单位和范围由下方校验及调用方契约限定）。"""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    if (folder/'model_manifest.json').exists():
        raise ValueError('Frozen model exists; refusing to retrain/overwrite')
    tr, va, te = split(frame, start)
    counts = dict(train=len(tr), validation=len(va), internal_test=len(te))
    if len(tr)<500 or len(va)<100 or len(te)<200:
        result = dict(status='insufficient_samples', counts=counts)
        dump(folder/'ml_status.json', result)
        return result
    candidates, best = [], {}
    with threadpool_limits(limits=1):
        for name, params in [('ridge', [.1,1,10]), ('tree', [3,7])]:
            ranked = []
            for param in params:
                model = make_pipeline(StandardScaler(), Ridge(alpha=param)) if name == 'ridge' else HistGradientBoostingRegressor(max_iter=100, min_samples_leaf=30, max_leaf_nodes=param, random_state=42, early_stopping=False)
                model.fit(tr[FEATURES], tr.y)
                score = float(mean_absolute_error(va.y, model.predict(va[FEATURES])))
                candidates.append(dict(model=name, parameter=param, validation_mae=score))
                ranked.append((score, param, model))
            best[name] = min(ranked, key=lambda x:x[0])
        selected = min(best, key=lambda n:best[n][0])
        reduced = [x for x in FEATURES if x not in ['bid_depth5','ask_depth5','imbalance5']]
        from sklearn.base import clone
        ablation = clone(best[selected][2]).fit(tr[reduced], tr.y)
        ablation_mae = float(mean_absolute_error(va.y, ablation.predict(va[reduced])))
    models = {n:x[2] for n,x in best.items()}
    joblib.dump(models, folder/'models.joblib')
    freeze = datetime.now(timezone.utc)
    holdout_day = max(freeze.date(), datetime.fromtimestamp(data_manifest['end'],timezone.utc).date()) + timedelta(days=1)
    holdout_start = datetime.combine(holdout_day, datetime.min.time(), timezone.utc).timestamp()
    mm = dict(status='frozen', kind=data_manifest['kind'], selected=selected, features=FEATURES,
              counts=counts, candidates=candidates, ablation_validation_mae=ablation_mae,
              full_validation_mae=best[selected][0], total_fits=6,
              frozen_at=freeze.isoformat(), external_start=holdout_start, external_end=holdout_start+7200,
              model_sha256=sha(folder/'models.joblib'), code_sha256=code_hash(),
              sklearn_version=sklearn.__version__, source_files=data_manifest['files'],
              config=data_manifest['config'], train_max_target=float(tr.target_t.max()),
              validation_min_t=float(va.t.min()), validation_max_target=float(va.target_t.max()),
              test_min_t=float(te.t.min()), standardizer_n_samples=int(models['ridge'][0].n_samples_seen_),
              ridge_standardized_coefficients=dict(zip(FEATURES, map(float, models['ridge'][-1].coef_))))
    dump(folder/'model_manifest.json', mm)  # Freeze BEFORE reading test labels for scoring.
    result = evaluate(te, models, folder, 'internal')
    distribution = {c: {'median':float(te[c].median()),'p90':float(te[c].quantile(.9))} for c in ['spread_bps','bid_depth5','ask_depth5','y']}
    dump(folder/'internal_distribution.json', distribution)
    dump(folder/'ml_status.json', dict(status='frozen', internal=result, external='pending', kind=mm['kind']))
    return mm


def external(frame, folder, data_manifest):
    """检验外部数据类型、冻结时间/配置和摘要，拒绝重复最终评价；使用既有模型只评分，不能把合成数据当真实。

    输入参数：frame、folder、data_manifest（单位和范围由下方校验及调用方契约限定）。"""
    folder = Path(folder)
    mm = read(folder/'model_manifest.json')
    if (folder/'external_metrics.json').exists():
        raise ValueError('External evaluation already exists; refusing repeated evaluation')
    if sha(folder/'models.joblib') != mm['model_sha256']:
        raise ValueError('Frozen model hash mismatch')
    if data_manifest['kind'] != mm['kind']:
        raise ValueError('Cannot mix synthetic and live research')
    if data_manifest['kind'] == 'live':
        if data_manifest['start'] != mm['external_start'] or data_manifest['end'] != mm['external_end']:
            raise ValueError('External window does not match frozen schedule')
        if data_manifest.get('role') != 'external' or data_manifest.get('model_sha256') != mm['model_sha256']:
            raise ValueError('External data not bound to frozen model before capture')
    for key in ['symbol','cex_fee_bps','max_cex_age']:
        if data_manifest['config'][key] != mm['config'][key]:
            raise ValueError(f'External config changed: {key}')
    if len(frame)<200:
        raise ValueError('External sample count below 200; not accepted')
    # Only load locally generated, hash-checked model artifacts; never download pickles.
    models = joblib.load(folder/'models.joblib')
    result = evaluate(frame, models, folder, 'external')
    distribution = {c:{'median':float(frame[c].median()),'p90':float(frame[c].quantile(.9))} for c in ['spread_bps','bid_depth5','ask_depth5','y']}
    dump(folder/'external_distribution.json', distribution)
    dump(folder/'external_audit.json',dict(evaluated_at=utcnow(), retrained=False,
                                          model_sha256=sha(folder/'models.joblib'), data_files=data_manifest['files'],kind=mm['kind']))
    return result
