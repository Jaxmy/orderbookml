"""组件用途：只加载冻结本地模型做只读推断，不在实时循环训练或发送订单。。

原始说明：Use frozen local artifacts on causal live features. Never fits or updates a model."""
import time
import joblib
import pandas as pd
import numpy as np
from threadpoolctl import threadpool_limits
from .io import ROOT,read,sha
from .model import features,FEATURES

class LiveModel:
    """只加载冻结本地模型做只读推断，不在实时循环训练或发送订单。"""
    def __init__(self):
        """读取旧固定规模模型清单并核验权重摘要，通过后加载模型字典。"""
        path=ROOT/'data'/'historical'/'research'
        self.manifest=read(path/'frozen.json')
        if sha(path/'models.joblib')!=self.manifest['model_sha256']: raise ValueError('Model hash changed')
        self.models=joblib.load(path/'models.joblib')

    def predict(self,rows,decision):
        """用决策时刻的因果特征预测旧任务；历史不足/过期返回None，基线胜出时使用基线并报告分布偏移。

        输入参数：rows、decision（单位和范围由下方校验及调用方契约限定）。"""
        if len(rows)<61 or rows[-1]['available_at']<decision-3: return None
        frame=features(pd.DataFrame(rows),decision-120,decision+1,include_unlabeled=True)
        x=frame[frame.t==decision]
        if len(x)!=1: return None
        outputs={}
        with threadpool_limits(limits=1):
            for task,model in self.models.items():
                baseline=float(x.cost_now.iloc[0]) if task=='execution_cost' else float(x.vol60.iloc[0]*10000)
                prediction=baseline if self.manifest['tasks'][task]['selected']=='persistence' else float(model.predict(x[FEATURES])[0])
                outputs[task]=dict(prediction=prediction,baseline=baseline,selected=self.manifest['tasks'][task]['selected'])
        scaler=self.models['execution_cost'][0] if hasattr(self.models['execution_cost'],'steps') else None
        z=float(np.max(np.abs(scaler.transform(x[FEATURES])))) if scaler else None
        return dict(id=f'prediction-{decision}',available_at=time.time(),feature_time=decision,target_time=decision+60,
            latest_feature_source_at=float(x.available_at.iloc[0]),source_id=str(x.source_id.iloc[0]),
            outputs=outputs,model_sha256=self.manifest['model_sha256'],max_training_standardized_deviation=z,
            distribution_warning=z is not None and z>5,mode='read-only prediction; no order generated',
            timing='live receiver timestamps; training used assumed 250ms historical feed latency')
