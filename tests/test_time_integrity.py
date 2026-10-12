import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from core.model import features,split,FEATURES,metrics
from core.quality import asof_index,coverage
from core.io import dump,sha,verified_manifest


def books(n=240):
    """生成确定性的盘口时间序列，便于修改未来行核验信息隔离。

    输入参数：n（单位和范围由下方校验及调用方契约限定）。"""
    return pd.DataFrame([dict(id=str(i),available_at=float(i),
           bids_json=json.dumps([[str(99+i*.001),'1']]),asks_json=json.dumps([[str(101+i*.001),'1']])) for i in range(n)])


def test_future_changes_do_not_change_past_features():
    """验证未来行情修改不改变过去特征；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    b=books();f=features(b,0,240)
    b.loc[b.available_at>120,'asks_json']='[["150","1"]]'
    other=features(b,0,240)
    pd.testing.assert_frame_equal(f[f.t<=120][FEATURES],other[other.t<=120][FEATURES])


def test_missing_window_is_not_zero_filled():
    """验证缺失历史窗口不得零填造信号；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    b=books();b=b[(b.available_at<80)|(b.available_at>100)]
    f=features(b,0,240)
    assert not ((f.t>=90)&(f.t<=150)).any()


def test_purge_horizon():
    """验证切分标签期限的隔离；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    f=pd.DataFrame({'t':np.arange(0,21600,10),'target_t':np.arange(0,21600,10)+60})
    tr,va,te=split(f,0)
    assert tr.target_t.max()<va.t.min()
    assert va.target_t.max()<te.t.min()


def test_asof_never_uses_future_and_stale_rejected():
    """验证向后对齐不读未来且拒绝陈旧；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    times=np.array([1.,5.,10.])
    assert asof_index(times,4,3)==0
    assert asof_index(times,4.1,3) is None
    assert asof_index(times,.9,3) is None


def test_coverage_keeps_expected_denominator():
    """验证质量覆盖率保留完整请求窗口分母；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    r=coverage(pd.DataFrame({'available_at':[0.,0.1,4.]}),0,10)
    assert r['expected']==10 and r['coverage']==.2


def test_manifest_tampering(tmp_path):
    """验证来源摘要篡改拒绝；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。

    输入参数：tmp_path（单位和范围由下方校验及调用方契约限定）。"""
    p=tmp_path/'x.parquet';p.write_bytes(b'original')
    dump(tmp_path/'manifest.json',{'files':{'x.parquet':sha(p)}})
    verified_manifest(tmp_path/'manifest.json')
    p.write_bytes(b'changed')
    with pytest.raises(ValueError):verified_manifest(tmp_path/'manifest.json')


def test_zero_baseline_percentage_not_infinite():
    """验证零基线百分比不输出Infinity；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    r=metrics([1,1],[1,1],[1,1])
    assert r['improvement_pct'] is None and r['mae_bps']==0


def test_partial_last_minute_coverage_is_bounded():
    """验证尾部不完整分钟覆盖率不超一；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    r=coverage(pd.DataFrame({'available_at':[1.,61.]}),0,90,60)
    assert r['expected']==2 and r['coverage']==1
