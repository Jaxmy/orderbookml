"""组件用途：基于已保存预测的烟测报告校核，不拟合模型。

原始说明：Score matured live forecasts without training, changing thresholds or claiming alpha."""
import pandas as pd
from core.io import ROOT,dump,utcnow
from core.store import Store
from core.model import features

if __name__=='__main__':
    store=Store(); books=sorted(store.latest('book',1000),key=lambda r:r['available_at'])
    predictions=sorted(store.latest('prediction',1000),key=lambda r:r['feature_time'])
    if not predictions: raise ValueError('No live forecasts recorded')
    start=int(books[0]['available_at']//10)*10; end=int(books[-1]['available_at'])+1
    frame=features(pd.DataFrame(books),start,end)
    outcomes=frame.set_index('t'); scored=[]
    for prediction in predictions:
        t=prediction['feature_time']
        if prediction['latest_feature_source_at']>t: raise ValueError('Future feature source')
        if t not in outcomes.index: continue
        row=outcomes.loc[t]; output=prediction['outputs']['execution_cost']
        if prediction['available_at']>=row.target_available_at: raise ValueError('Forecast was not recorded before its outcome')
        scored.append(dict(t=t,forecast_available_at=prediction['available_at'],target_available_at=float(row.target_available_at),
            prediction=output['prediction'],baseline=output['baseline'],actual=float(row.y),
            model_sha256=prediction['model_sha256']))
    if not scored: raise ValueError('No matured forecasts yet')
    result=dict(time=utcnow(),live_forecasts=len(predictions),matured=len(scored),retrained=False,
        mean_absolute_error=sum(abs(r['prediction']-r['actual']) for r in scored)/len(scored),
        persistence_mean_absolute_error=sum(abs(r['baseline']-r['actual']) for r in scored)/len(scored),
        observations=scored,interpretation='Short operational smoke only; sample too small for an effectiveness claim')
    dump(ROOT/'logs'/'live_model_smoke.json',result)
    print({k:v for k,v in result.items() if k!='observations'})
