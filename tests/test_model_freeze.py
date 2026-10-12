import numpy as np
import pandas as pd
import pytest
from core.model import FEATURES,train,external
from core.io import read,sha


def test_training_freeze_and_external_guards(tmp_path):
    """验证训练冻结、权重防篡改与外部窗口守卫；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。

    输入参数：tmp_path（单位和范围由下方校验及调用方契约限定）。"""
    rng=np.random.default_rng(8)
    n=2160
    f=pd.DataFrame(rng.normal(size=(n,8)),columns=FEATURES)
    f['t']=np.arange(n)*10.;f['target_t']=f.t+60
    f['y']=f.cost_now*.5+rng.normal(0,.1,n)
    c={'symbol':'ETHUSDC','cex_fee_bps':'10','max_cex_age':3}
    m={'kind':'synthetic','end':21600,'files':{},'config':c}
    folder=tmp_path/'models'
    mm=train(f,0,folder,m)
    assert mm['standardizer_n_samples']==mm['counts']['train']==1074
    assert mm['train_max_target']<mm['validation_min_t']
    assert mm['validation_max_target']<mm['test_min_t']
    assert mm['total_fits']==6
    with pytest.raises(ValueError,match='Frozen model'):train(f,0,folder,m)
    with pytest.raises(ValueError,match='mix'):external(f.head(300),folder,{**m,'kind':'live'})
    before=sha(folder/'models.joblib')
    external(f.tail(300),folder,m)
    assert sha(folder/'models.joblib')==before
    assert read(folder/'external_audit.json')['retrained'] is False
    with pytest.raises(ValueError,match='already exists'):external(f.tail(300),folder,m)
