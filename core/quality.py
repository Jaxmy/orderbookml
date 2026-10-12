"""组件用途：逐行检查盘口与可用时间，坏记录单独保留原因；有效记录排序并按 id 去重，返回清洗表和失败清单。；二分查找不晚于目标时刻的最后一个观测；无过去观测或超陈旧度返回 None，绝不使用未来行。。"""
import numpy as np
import pandas as pd
import math
from .execution import validate_book


def clean_books(frame):
    """逐行检查盘口与可用时间，坏记录单独保留原因；有效记录排序并按 id 去重，返回清洗表和失败清单。

    输入参数：frame（单位和范围由下方校验及调用方契约限定）。"""
    accepted, failures = [], []
    for row in frame.to_dict('records'):
        try:
            validate_book(row)
            if not np.isfinite(float(row['available_at'])):
                raise ValueError('invalid timestamp')
            accepted.append(row)
        except (ValueError, KeyError, TypeError) as e:
            failures.append({'id': row.get('id'), 'error': str(e)})
    result = pd.DataFrame(accepted, columns=frame.columns)
    if len(result):
        result = result.sort_values('available_at').drop_duplicates('id', keep='first')
    return result, failures


def asof_index(times, t, max_age=3):
    """二分查找不晚于目标时刻的最后一个观测；无过去观测或超陈旧度返回 None，绝不使用未来行。

    输入参数：times、t、max_age（单位和范围由下方校验及调用方契约限定）。"""
    i = int(np.searchsorted(times, t, side='right') - 1)
    return i if i >= 0 and 0 <= t - times[i] <= max_age else None


def coverage(frame, start, end, interval=1):
    """以整个请求窗口的理论时间格为分母，计算被有效观测占据的格子比例；缺失窗口仍计入分母。

    输入参数：frame、start、end、interval（单位和范围由下方校验及调用方契约限定）。"""
    expected = math.ceil((end - start) / interval)
    ts = frame['available_at'].to_numpy() if len(frame) else np.array([])
    valid = ts[(ts >= start) & (ts < end)]
    occupied = len(np.unique(np.floor((valid - start) / interval)))
    return dict(expected=expected, occupied=occupied, coverage=occupied / expected if expected else 0)
