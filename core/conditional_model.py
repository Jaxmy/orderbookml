"""组件用途：校验盘口并取前五档浮点价格与数量，供条件特征汇总；与成交引擎的 Decimal 计算分离。；把一日盘口向后对齐到秒格，构造过去特征和买卖方向/数量/期限条件；未来行仅计算标签。过滤缺失、陈旧或深度不足窗口。。

原始说明：Scale/side/horizon-conditioned cost and risk estimates from causal books."""
from __future__ import annotations

import json
import uuid
from datetime import date, timedelta
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from .execution import sweep, validate_book
from .io import ROOT, dump, read, sha, utcnow

FEATURES = ['spread_bps', 'bid_depth5_eth', 'ask_depth5_eth', 'imbalance5',
            'return10_bps', 'return60_bps', 'vol60_bps', 'side_sign',
            'order_size_eth', 'size_to_depth', 'current_cost_bps', 'horizon_seconds']
TARGETS = ('adverse_mid_bps', 'future_execution_cost_bps', 'future_volatility_bps')
MODEL_ROOT = ROOT / 'data' / 'experiments' / 'models' / 'conditional'
BOOK_ROOT = ROOT / 'data' / 'historical'
TRAIN_DAYS = ('2026-09-01', '2026-09-02', '2026-09-03', '2026-09-04')
VALIDATION_DAY = '2026-09-05'
SIZES_ETH = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0)
HORIZONS = (10, 30, 60)
SAMPLE_EVERY_SECONDS = 60


def _top(row: dict) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """校验盘口并取前五档浮点价格与数量，供条件特征汇总；与成交引擎的 Decimal 计算分离。

    输入参数：row（单位和范围由下方校验及调用方契约限定）。"""
    bids, asks = validate_book(row)
    return ([(float(p), float(q)) for p, q in bids[:5]],
            [(float(p), float(q)) for p, q in asks[:5]])


def _day_samples(day: str, source_path: Path | None = None) -> pd.DataFrame:
    """把一日盘口向后对齐到秒格，构造过去特征和买卖方向/数量/期限条件；未来行仅计算标签。过滤缺失、陈旧或深度不足窗口。

    输入参数：day（单位和范围由下方校验及调用方契约限定）。"""
    path = source_path or BOOK_ROOT / f'{day}.books.parquet'
    if not path.exists():
        raise FileNotFoundError(f'Missing verified Bybit books for {day}')
    raw = pd.read_parquet(path, columns=['available_at', 'bids_json', 'asks_json'])
    raw = raw.sort_values('available_at').reset_index(drop=True)
    event_times = raw.available_at.to_numpy(dtype='float64')
    starts = date.fromisoformat(day)
    start_ts = pd.Timestamp(starts, tz='UTC').timestamp()
    grid = np.arange(start_ts, start_ts + 86400, dtype='float64')
    idx = np.searchsorted(event_times, grid, side='right') - 1
    valid = idx >= 0
    age = np.full(len(grid), np.inf)
    age[valid] = grid[valid] - event_times[idx[valid]]
    valid &= age <= 3.0
    mids = np.full(len(grid), np.nan)
    for j in np.flatnonzero(valid):
        row = raw.iloc[int(idx[j])]
        bids = json.loads(row.bids_json)
        asks = json.loads(row.asks_json)
        mids[j] = (float(bids[0][0]) + float(asks[0][0])) / 2
    mid_series = pd.Series(mids)
    returns = mid_series.pct_change(fill_method=None)
    ret10 = (mid_series / mid_series.shift(10) - 1) * 10000
    ret60 = (mid_series / mid_series.shift(60) - 1) * 10000
    vol60 = returns.rolling(60, min_periods=60).std() * 10000
    valid_window = pd.Series(valid.astype(int)).rolling(61, min_periods=61).sum().eq(61)
    rows = []
    sample_idx = np.arange(60, 86400 - max(HORIZONS), SAMPLE_EVERY_SECONDS)
    for i in sample_idx:
        if not valid_window.iloc[i] or not np.isfinite([ret10.iloc[i], ret60.iloc[i], vol60.iloc[i]]).all():
            continue
        current_row = raw.iloc[int(idx[i])].to_dict()
        try:
            bids, asks = _top(current_row)
        except ValueError:
            continue
        bid_q = sum(q for _, q in bids)
        ask_q = sum(q for _, q in asks)
        bid_notional = sum(p * q for p, q in bids)
        ask_notional = sum(p * q for p, q in asks)
        current_mid = float(mids[i])
        spread = (asks[0][0] - bids[0][0]) / current_mid * 10000
        bid_size, ask_size = bid_q, ask_q
        imbalance = (bid_size - ask_size) / max(bid_size + ask_size, 1e-12)
        for horizon in HORIZONS:
            future_i = i + horizon
            if not valid[future_i] or not np.isfinite(mids[future_i]):
                continue
            future_vol_window = returns.iloc[i + 1:future_i + 1]
            if future_vol_window.isna().any():
                continue
            future_vol = float(future_vol_window.std(ddof=1) * 10000) if len(future_vol_window) > 1 else 0.0
            future_row = raw.iloc[int(idx[future_i])].to_dict()
            for side in ('buy', 'sell'):
                side_sign = 1.0 if side == 'buy' else -1.0
                depth = ask_q if side == 'buy' else bid_q
                for quantity in SIZES_ETH:
                    now = sweep(current_row, side, str(quantity), '0')
                    future = sweep(future_row, side, str(quantity), '0')
                    if not now['complete'] or not future['complete']:
                        continue
                    rows.append(dict(
                        t=float(grid[i]), target_t=float(grid[future_i]),
                        spread_bps=spread, bid_depth5_eth=bid_q, ask_depth5_eth=ask_q,
                        imbalance5=imbalance, return10_bps=float(ret10.iloc[i]),
                        return60_bps=float(ret60.iloc[i]), vol60_bps=float(vol60.iloc[i]),
                        side_sign=side_sign, order_size_eth=quantity,
                        size_to_depth=quantity / max(depth, 1e-12),
                        current_cost_bps=float(now['price_cost_bps']),
                        horizon_seconds=float(horizon),
                        adverse_mid_bps=side_sign * (float(mids[future_i]) / current_mid - 1) * 10000,
                        future_execution_cost_bps=float(future['price_cost_bps']),
                        future_volatility_bps=future_vol))
    return pd.DataFrame(rows)


def build_training_frames() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """只载入预定训练日及验证日；标签终点触及分区边界的样本剔除。返回两张样本表和来源/时间边界清单，不读取最终测试日。"""
    train = pd.concat([_day_samples(day) for day in TRAIN_DAYS], ignore_index=True)
    valid = _day_samples(VALIDATION_DAY)
    valid_end = pd.Timestamp(date.fromisoformat(VALIDATION_DAY) + timedelta(days=1), tz='UTC').timestamp()
    train_start = pd.Timestamp(date.fromisoformat(TRAIN_DAYS[0]), tz='UTC').timestamp()
    # Purge any label whose forward horizon touches the validation boundary.
    validation_start = pd.Timestamp(date.fromisoformat(VALIDATION_DAY), tz='UTC').timestamp()
    train = train[train.target_t < validation_start].reset_index(drop=True)
    valid = valid[valid.target_t < valid_end].reset_index(drop=True)
    manifest = dict(train_days=list(TRAIN_DAYS), validation_day=VALIDATION_DAY,
                    train_start_utc=datetime_iso(train_start),
                    train_label_end_utc=datetime_iso(float(train.target_t.max())) if len(train) else None,
                    validation_label_end_utc=datetime_iso(float(valid.target_t.max())) if len(valid) else None,
                    horizons_seconds=list(HORIZONS), sizes_eth=list(SIZES_ETH),
                    sample_every_seconds=SAMPLE_EVERY_SECONDS,
                    source_files={day: sha(BOOK_ROOT / f'{day}.books.parquet')
                                  for day in (*TRAIN_DAYS, VALIDATION_DAY)},
                    future_test_days_not_loaded=True)
    return train, valid, manifest


def datetime_iso(timestamp: float) -> str:
    """将 Unix 秒转换为明确 UTC 的 ISO 时间字符串，用于模型时间边界记录。

    输入参数：timestamp（单位和范围由下方校验及调用方契约限定）。"""
    return pd.Timestamp(timestamp, unit='s', tz='UTC').isoformat()


def train_conditional_model(cancelled=None, progress=None) -> dict:
    """每目标在训练集拟合 Ridge/提升树，在时间验证集与 persistence 比 MAE；选型后仅重拟合训练加验证，写新版本权重及摘要。失败模型不强行替代基线。

    原始实现说明：
    Fit a new immutable model; only train/validation dates are read."""
    if cancelled is not None and cancelled.is_set():raise InterruptedError('Training cancelled')
    if progress:progress(dict(stage='training_data',progress=.05))
    train, valid, data_manifest = build_training_frames()
    if len(train) < 500 or len(valid) < 100:
        raise ValueError(f'Insufficient training/validation samples: {len(train)}/{len(valid)}')
    run_id = uuid.uuid4().hex
    folder = MODEL_ROOT / 'runs' / run_id
    folder.mkdir(parents=True, exist_ok=False)
    selected, validation, candidates = {}, {}, {}
    fitted = {}
    with threadpool_limits(limits=1):
        for target in TARGETS:
            if cancelled is not None and cancelled.is_set():raise InterruptedError('Training cancelled')
            if progress:progress(dict(stage='training',progress=.1+.7*list(TARGETS).index(target)/len(TARGETS)))
            baseline = (np.zeros(len(valid)) if target == 'adverse_mid_bps'
                        else valid.current_cost_bps.to_numpy() if target == 'future_execution_cost_bps'
                        else valid.vol60_bps.to_numpy() * np.sqrt(valid.horizon_seconds.to_numpy() / 60))
            baseline_score = float(mean_absolute_error(valid[target], baseline))
            ranked = []
            candidates[target] = {}
            for model_name in ('ridge', 'hist_gradient_boosting'):
                if model_name == 'ridge':
                    model = make_pipeline(StandardScaler(), Ridge(alpha=2.0))
                else:
                    model = HistGradientBoostingRegressor(max_iter=80, max_leaf_nodes=15,
                                                          min_samples_leaf=80, l2_regularization=2.0,
                                                          early_stopping=False, random_state=42)
                if cancelled is not None and cancelled.is_set():raise InterruptedError('Training cancelled')
                model.fit(train[FEATURES], train[target])
                if cancelled is not None and cancelled.is_set():raise InterruptedError('Training cancelled')
                prediction = model.predict(valid[FEATURES])
                score = float(mean_absolute_error(valid[target], prediction))
                candidates[target][model_name] = dict(validation_mae=score,
                                                       persistence_mae=baseline_score)
                ranked.append((score, model_name))
            best_score, best_model = min(ranked)
            winner = best_model if best_score < baseline_score else 'persistence'
            selected[target] = winner
            validation[target] = (candidates[target][winner] if winner != 'persistence'
                                  else dict(validation_mae=baseline_score,
                                            persistence_mae=baseline_score,
                                            selected='persistence'))
            if winner == 'persistence':
                # Do not freeze a more complex model when it loses to the
                # causal persistence baseline on the chronological validation.
                continue
            final = (make_pipeline(StandardScaler(), Ridge(alpha=2.0)) if winner == 'ridge'
                     else HistGradientBoostingRegressor(max_iter=80, max_leaf_nodes=15,
                                                        min_samples_leaf=80, l2_regularization=2.0,
                                                        early_stopping=False, random_state=42))
            # Refit on the chronological train+validation union only after
            # model family selection; no Sep 6-7/test labels are loaded.
            combined = pd.concat([train, valid], ignore_index=True)
            if cancelled is not None and cancelled.is_set():raise InterruptedError('Training cancelled')
            final.fit(combined[FEATURES], combined[target])
            if cancelled is not None and cancelled.is_set():raise InterruptedError('Training cancelled')
            fitted[target] = final
    if cancelled is not None and cancelled.is_set():raise InterruptedError('Training cancelled')
    model_path = folder / 'models.joblib'
    joblib.dump(fitted, model_path, compress=3)
    manifest = dict(status='frozen_prototype', model_id=run_id, created_at=utcnow(),
                    features=FEATURES, targets=list(TARGETS), selected=selected,
                    candidates=candidates, validation=validation,
                    counts=dict(train=len(train), validation=len(valid),
                                train_validation_union=len(train) + len(valid)),
                    training=data_manifest, model_sha256=sha(model_path),
                    sklearn_version=sklearn.__version__, code_sha256=sha(Path(__file__)),
                    usage_guard='Predict only for decision timestamps after the validation label cutoff; not a sealed OOS performance claim.')
    dump(folder / 'manifest.json', manifest)
    dump(folder / 'training_report.json', manifest)
    return manifest


def load_conditional_model(model_id: str) -> tuple[dict, dict]:
    """校验模型标识、冻结状态和本地权重摘要后加载；不接受任意外部 pickle 或静默改写权重。

    输入参数：model_id（单位和范围由下方校验及调用方契约限定）。"""
    if len(model_id) != 32 or not model_id.isalnum():
        raise ValueError('Invalid model identifier')
    folder = MODEL_ROOT / 'runs' / model_id
    manifest = read(folder / 'manifest.json')
    model_path = folder / 'models.joblib'
    if not manifest or manifest.get('status') != 'frozen_prototype' or not model_path.exists():
        raise FileNotFoundError(f'Frozen conditional model {model_id} was not found')
    if sha(model_path) != manifest['model_sha256']:
        raise ValueError('Conditional model hash does not match its manifest')
    return joblib.load(model_path), manifest


def predict_conditional(model_id: str, features: dict) -> dict:
    """校验特征契约并使用冻结模型预测；未保留模型的目标使用当前成本/历史波动基线，输出模型版本。

    输入参数：model_id、features（单位和范围由下方校验及调用方契约限定）。"""
    models, manifest = load_conditional_model(model_id)
    if any(name not in features for name in FEATURES):
        raise ValueError('Prediction features do not match the frozen model contract')
    row = pd.DataFrame([{name: float(features[name]) for name in FEATURES}], columns=FEATURES)
    values = {name: float(model.predict(row)[0]) for name, model in models.items()}
    if 'adverse_mid_bps' not in values:
        values['adverse_mid_bps'] = 0.0
    if 'future_execution_cost_bps' not in values:
        values['future_execution_cost_bps'] = float(features['current_cost_bps'])
    if 'future_volatility_bps' not in values:
        values['future_volatility_bps'] = (float(features['vol60_bps']) *
                                            np.sqrt(float(features['horizon_seconds']) / 60))
    values['future_volatility_bps'] = max(0.0, values['future_volatility_bps'])
    values['model_id'] = model_id
    values['status'] = manifest['status']
    return values


def live_feature_row(book: dict, history: pd.DataFrame, side: str,
                     order_size_eth: float, horizon_seconds: int) -> dict:
    """只从当前簿与过去一分钟价格生成十二项条件特征，检查连续性、可见深度和训练期限；不能把未来标签当输入。

    输入参数：book、history、side、order_size_eth、horizon_seconds（单位和范围由下方校验及调用方契约限定）。

    原始实现说明：
    Build the exact frozen feature contract using only observations <= now."""
    if side not in ('buy', 'sell') or order_size_eth <= 0:
        raise ValueError('Invalid side or order size for conditional features')
    bids, asks = validate_book(book)
    now = float(book.get('evaluation_at', book.get('available_at')))
    mid = float((bids[0][0] + asks[0][0]) / 2)
    bid_depth = float(sum(q for _, q in bids[:5]))
    ask_depth = float(sum(q for _, q in asks[:5]))
    imbalance = (bid_depth - ask_depth) / max(bid_depth + ask_depth, 1e-12)
    depth = ask_depth if side == 'buy' else bid_depth
    current = sweep(book, side, str(order_size_eth), '0')
    if not current['complete']:
        raise ValueError('Order size exceeds currently visible Bybit top-20 depth')
    history = history[history.available_at <= now].sort_values('available_at')
    times = history.available_at.to_numpy(dtype='float64')
    mids = history.mid.to_numpy(dtype='float64')

    def asof(target: float):
        """从已经截断的历史序列找不晚于目标的中间价；缺观测或间隔超过三秒返回 None。

        输入参数：target（单位和范围由下方校验及调用方契约限定）。"""
        index = np.searchsorted(times, target, side='right') - 1
        if index < 0 or target - times[index] > 3:
            return None
        return mids[index]

    prior10, prior60 = asof(now - 10), asof(now - 60)
    if prior10 is None or prior60 is None or prior10 <= 0 or prior60 <= 0:
        raise ValueError('Need a continuous one-minute past window before requesting predictions')
    grid = np.arange(now - 60, now + 0.1, 1.0)
    indices = np.searchsorted(times, grid, side='right') - 1
    valid = indices >= 0
    grid_mids = np.full(len(grid), np.nan)
    ages = np.full(len(grid), np.inf)
    grid_mids[valid] = mids[indices[valid]]
    ages[valid] = grid[valid] - times[indices[valid]]
    if np.any(ages > 3) or not np.isfinite(grid_mids).all():
        raise ValueError('Past one-minute history contains gaps; conditional prediction is unavailable')
    vol = float(pd.Series(grid_mids).pct_change(fill_method=None).dropna().std(ddof=1) * 10000)
    horizon = int(horizon_seconds)
    if horizon < min(HORIZONS) or horizon > max(HORIZONS):
        raise ValueError('Conditional horizon must be within the trained 10–60 second range')
    return dict(spread_bps=float((asks[0][0] - bids[0][0]) / ((asks[0][0] + bids[0][0]) / 2) * 10000),
                bid_depth5_eth=bid_depth, ask_depth5_eth=ask_depth,
                imbalance5=imbalance, return10_bps=(mid / prior10 - 1) * 10000,
                return60_bps=(mid / prior60 - 1) * 10000, vol60_bps=vol,
                side_sign=1.0 if side == 'buy' else -1.0,
                order_size_eth=float(order_size_eth), size_to_depth=float(order_size_eth / max(depth, 1e-12)),
                current_cost_bps=float(current['price_cost_bps']), horizon_seconds=float(horizon))


def predict_with_models(models: dict, feature_rows: list[dict]) -> dict[str, np.ndarray]:
    """按冻结特征顺序组成表格并限制线程数，批量调用各目标模型；缺模型的目标由上层补基线。

    输入参数：models、feature_rows（单位和范围由下方校验及调用方契约限定）。"""
    frame = pd.DataFrame(feature_rows, columns=FEATURES)
    with threadpool_limits(limits=1):
        return {name: np.asarray(model.predict(frame), dtype='float64') for name, model in models.items()}


def list_conditional_models() -> list[dict]:
    """枚举本地冻结版本清单并按创建时间倒序；不训练、加载全量行情或更改任何权重。"""
    path = MODEL_ROOT / 'runs'
    items = []
    if path.exists():
        for folder in path.iterdir():
            if folder.is_dir():
                manifest = read(folder / 'manifest.json')
                if manifest:
                    items.append(manifest)
    return sorted(items, key=lambda x: x.get('created_at', ''), reverse=True)
