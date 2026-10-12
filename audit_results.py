"""组件用途：独立审计已保存研究证据。

原始说明：One documented reporting correction; uses saved predictions, never fits a model."""
import pandas as pd
from core.io import ROOT,read,dump,sha,utcnow
from core.research import score,TASKS

if __name__=='__main__':
    out=ROOT/'data'/'historical'/'research'
    original=out/'test_metrics.original-unweighted-ci.json'
    if original.exists(): raise ValueError('Correction already applied')
    old=read(out/'test_metrics.json')
    frozen=read(out/'frozen.json'); pred=pd.read_parquet(out/'test_predictions.parquet')
    result={}
    for task in TASKS:
        actual=pred[task+'_actual']; p=pred[task+'_model'].to_numpy(); base=pred[task+'_baseline'].to_numpy()
        selected=base if frozen['tasks'][task]['selected']=='persistence' else p
        result[task]={'candidate':score(actual,p,base,pred.t),'selected':score(actual,selected,base,pred.t)}
    dump(original,old); dump(out/'test_metrics.json',result)
    report=(out/'report.md').read_text(encoding='utf-8')
    for task in TASKS:
        report=report.replace(str(old[task]['candidate']['hour_block_delta_ci95']),str(result[task]['candidate']['hour_block_delta_ci95']))
    (out/'report.md').write_text(report+'\n\n报告审计：置信区间按小时块重采样后，用总误差/总样本数计算，与整体 MAE 差值使用同一权重。仅修正报告；无重训、无更换模型。\n',encoding='utf-8')
    dump(out/'report_correction.json',dict(time=utcnow(),reason='Match block bootstrap weighting to sample-weighted MAE estimand',
        retrained=False,model_sha256=sha(out/'models.joblib'),predictions_sha256=sha(out/'test_predictions.parquet')))
    print(result)
