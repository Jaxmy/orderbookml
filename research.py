"""组件用途：按既定日期构造并分开保存训练/验证/测试特征及摘要，保护旧研究输入。；读取指定已保存分区并核验特征摘要，不重新切分或偷偷改窗口。。"""
import argparse
from datetime import datetime
import joblib
import pandas as pd
from sklearn.metrics import mean_absolute_error
from threadpoolctl import threadpool_limits
from core.io import ROOT, read, dump, sha, code_hash, utcnow
from core.research import FEATURES, TASKS, build_features, partition, candidates, score
from download_history import HOME, usage

OUT=HOME/'research'
stamp=lambda s:datetime.fromisoformat(s).timestamp()

def prepare():
    """按既定日期构造并分开保存训练/验证/测试特征及摘要，保护旧研究输入。"""
    cfg=read(ROOT/'history.json')
    manifest=read(HOME/'normalized_manifest.json')
    OUT.mkdir(exist_ok=True)
    for day in manifest['days']:
        path=HOME/(day['day']+'.books.parquet')
        target=OUT/(day['day']+'.features.parquet')
        if target.exists(): raise ValueError('Features already exist')
        if sha(path)!=day['sha256']: raise ValueError('Book hash changed')
        start=stamp(day['day']+'T00:00:00+00:00')
        frame=build_features(pd.read_parquet(path),start,start+86400)
        if usage()+64_000_000>min(cfg['storage_cap_bytes'],4_000_000_000): raise ValueError('Storage budget')
        frame.to_parquet(target,index=False,compression='zstd')
        print(day['day'],len(frame),flush=True)
    dump(OUT/'features_manifest.json',dict(config_sha256=sha(ROOT/'history.json'),
        source_manifest_sha256=sha(HOME/'normalized_manifest.json'),
        files={p.name:sha(p) for p in OUT.glob('*.features.parquet')},created_at=utcnow()))

def load(role):
    """读取指定已保存分区并核验特征摘要，不重新切分或偷偷改窗口。

    输入参数：role（单位和范围由下方校验及调用方契约限定）。"""
    cfg=read(ROOT/'history.json'); fm=read(OUT/'features_manifest.json')
    if fm['config_sha256']!=sha(ROOT/'history.json'): raise ValueError('Specification changed')
    train_end,valid_end,end=map(stamp,[cfg['train_end'],cfg['validation_end'],cfg['test_end']])
    start=stamp(cfg['dates'][0]+'T00:00:00+00:00')
    lo,hi={'train':(start,train_end),'validation':(train_end,valid_end),'test':(valid_end,end)}[role]
    frames=[]
    for day in cfg['dates']:
        t=stamp(day+'T00:00:00+00:00')
        if t>=hi or t+86400<=lo: continue
        path=OUT/(day+'.features.parquet')
        if sha(path)!=fm['files'][path.name]: raise ValueError('Features changed')
        frames.append(pd.read_parquet(path))
    return partition(pd.concat(frames,ignore_index=True),lo,hi)

def train():
    """只用训练/验证分区比较候选和历史基线，保存冻结权重、选择结果及代码/数据摘要。"""
    if (OUT/'frozen.json').exists(): raise ValueError('Frozen experiment: no retraining')
    tr,va=load('train'),load('validation')
    if len(tr)<1000 or len(va)<200: raise ValueError('Insufficient valid samples')
    result,models={},{}
    # No test partition is opened in this command.
    with threadpool_limits(limits=1):
        for task,(label,baseline) in TASKS.items():
            ranked=[]; fold_scores=[]
            for name,model in candidates().items():
                # Two expanding folds confined to training dates; development diagnostic only.
                origin=stamp(read(ROOT/'history.json')['dates'][0]+'T00:00:00+00:00')
                for days in [2,3]:
                    cutoff=origin+days*86400
                    fit=partition(tr,origin,cutoff); hold=partition(tr,cutoff,cutoff+86400)
                    model.fit(fit[FEATURES],fit[label])
                    fold_scores.append(dict(model=name,fold=days,mae=float(mean_absolute_error(hold[label],model.predict(hold[FEATURES])))))
                model.fit(tr[FEATURES],tr[label])
                error=float(mean_absolute_error(va[label],model.predict(va[FEATURES])))
                ranked.append((error,name,model))
            error,name,model=min(ranked,key=lambda x:x[0])
            baseline_error=float(mean_absolute_error(va[label],va[baseline]))
            models[task]=model
            result[task]=dict(candidate=name,selected=name if error<baseline_error else 'persistence',
                validation_mae=error,validation_baseline_mae=baseline_error,
                candidates=[dict(name=n,mae=e) for e,n,_ in ranked],walk_forward=fold_scores)
    joblib.dump(models,OUT/'models.joblib')
    dump(OUT/'frozen.json',dict(created_at=utcnow(),tasks=result,features=FEATURES,
        counts={'train':len(tr),'validation':len(va)},train_max_label=float(tr.target_t.max()),
        validation_min_t=float(va.t.min()),validation_max_label=float(va.target_t.max()),
        model_sha256=sha(OUT/'models.joblib'),features_sha256=sha(OUT/'features_manifest.json'),
        config_sha256=sha(ROOT/'history.json'),code_sha256=code_hash(),test_observed=False))
    print(result,flush=True)

def evaluate():
    """核验冻结数据/代码，先记录最终测试已打开再一次性评分和写报告；禁止反复打开测试调参。"""
    if (OUT/'test_started.json').exists(): raise ValueError('Final test already opened; no repeated tuning')
    frozen=read(OUT/'frozen.json')
    if frozen['model_sha256']!=sha(OUT/'models.joblib') or frozen['features_sha256']!=sha(OUT/'features_manifest.json'):
        raise ValueError('Frozen artifacts changed')
    if frozen['config_sha256']!=sha(ROOT/'history.json') or frozen['code_sha256']!=code_hash():
        raise ValueError('Specification/code changed after freeze')
    dump(OUT/'test_started.json',dict(time=utcnow(),frozen_sha256=sha(OUT/'frozen.json')))
    te=load('test'); models=joblib.load(OUT/'models.joblib'); result={}
    pred=te[['t','target_t','source_id','label_source_id']].copy()
    with threadpool_limits(limits=1):
        for task,(label,baseline) in TASKS.items():
            p=models[task].predict(te[FEATURES])
            deployed=te[baseline].to_numpy() if frozen['tasks'][task]['selected']=='persistence' else p
            result[task]=dict(candidate=score(te[label],p,te[baseline].to_numpy(),te.t),
                selected=score(te[label],deployed,te[baseline].to_numpy(),te.t))
            pred[task+'_actual']=te[label].to_numpy(); pred[task+'_model']=p
            pred[task+'_baseline']=te[baseline].to_numpy()
    pred.to_parquet(OUT/'test_predictions.parquet',index=False)
    dump(OUT/'test_metrics.json',result)
    text=['# 真实历史 ML 研究结果','', 'Bybit ETH/USDC；七日固定样本；秒级视图，交易所时间 + 250ms 假设。',
          '训练 09-01—09-04，验证 09-05，封存测试 09-06—09-07（UTC）。',
          '模型先冻结，再用独立命令打开测试分区。标签跨界样本剔除；标准化只在训练拟合。','']
    for task,value in result.items():
        s=value['candidate']; spec=frozen['tasks'][task]
        text += [f'## {task}',f'候选 {spec["candidate"]}；验证集决定使用 {spec["selected"]}。',
            f'最终测试 N={s["n"]}，模型 MAE={s["mae"]:.6f}，persistence MAE={s["baseline_mae"]:.6f}。',
            f'模型减基线 MAE 差值 95% 小时块 bootstrap 区间：{s["hour_block_delta_ci95"]}。','']
    text += ['收益与实际执行尚需独立验证；成本预测精度不等于可盈利策略。',
             '仅七日样本，无法覆盖长期市场制度变化；保留不胜过基线的结果。']
    (OUT/'report.md').write_text('\n'.join(text),encoding='utf-8')
    print(result,flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('action',choices=['prepare','train','evaluate'])
    globals()[p.parse_args().action]()
