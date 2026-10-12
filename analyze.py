"""组件入口：核验采集清单、清洗盘口、生成质量和执行报告；数据及窗口满足要求才训练或做独立外部评价，记录资源。"""
import argparse
import json
import time
from pathlib import Path
import pandas as pd
import psutil
from core.io import verified_manifest, dump, log, read, sha
from core.quality import clean_books,coverage
from core.reporting import report
from core.model import features,train,external


def run(path,output,external_model=None):
    """核验采集清单、清洗盘口、生成质量和执行报告；数据及窗口满足要求才训练或做独立外部评价，记录资源。

    输入参数：path、output、external_model（单位和范围由下方校验及调用方契约限定）。"""
    started=time.perf_counter();path=Path(path);out=Path(output)
    if out.exists():raise ValueError('Output exists; preserve frozen reports and use a new output directory')
    m=verified_manifest(path);out.mkdir(parents=True)
    books,invalid=clean_books(pd.read_parquet(path.parent/'cex.parquet'))
    books=books[(books.available_at>=m['start'])&(books.available_at<m['end'])].reset_index(drop=True)
    dex=pd.read_parquet(path.parent/'dex.parquet')
    if len(dex):dex=dex[(dex.available_at>=m['start'])&(dex.available_at<m['end'])].copy()
    quality={'cex':coverage(books,m['start'],m['end']), 'invalid_books':invalid,'kind':m['kind']}
    dump(out/'manifest.json',m)
    if not len(books):
        dump(out/'quality.json',quality)
        raise ValueError('No valid CEX data; data quality failed')
    f=features(books,m['start'],m['end']);f.to_parquet(out/'features.parquet',index=False)
    quality['ml_samples']=len(f)
    if external_model:
        quality['accepted']=quality['cex']['coverage']>=.95 and len(f)>=200
        dump(out/'quality.json',quality)
        if not quality['accepted']:raise ValueError('External data quality failed')
        mm=Path(external_model).resolve()
        result=external(f,mm.parent,m)
        dump(out/'external_result.json',result)
        dump(out/'model_link.json',{'model_directory':str(mm.parent),'manifest_sha256':sha(mm)})
    else:
        quality['dex']=coverage(dex.drop_duplicates('group_id') if len(dex) else dex,m['start'],m['end'],60)
        result=report(books,dex,m,out)
        quality.update(result)
        quality['accepted']=(quality['cex']['coverage']>=.95 and quality['dex']['coverage']>=.9 and result['valid_groups']>=200)
        if m['end']-m['start']==21600 and quality['accepted']:
            train(f,m['start'],out/'models',m)
        else:
            dump(out/'models'/'ml_status.json',{'status':'not_trained','reason':'main sample duration or coverage failed','kind':m['kind']})
    quality['market_acceptance']=quality['accepted'] and m['kind']=='live'
    quality['elapsed_seconds']=time.perf_counter()-started
    mem=psutil.Process().memory_info()
    quality['peak_working_set_bytes']=getattr(mem,'peak_wset',mem.rss)
    quality['memory_target_passed']=quality['peak_working_set_bytes']<=2*1024**3
    dump(out/'quality.json',quality)
    badge='合成测试数据，不能作为真实行情/模型有效性的证据' if m['kind']=='synthetic' else ('短时预检数据，非正式研究' if m['kind']=='smoke' else '只读市场样本；无实盘成交')
    summary=f'# 分析交付报告\n\n**{badge}**\n\n## 数据与验收\n\n```json\n{json.dumps(quality,ensure_ascii=False,indent=2)}\n```\n\n'
    summary+='## 方法与限制\n\n同规模成本含 CEX 假设费率、DEX 内含池费和另列 gas；报价不保证真实成交。ML 目标为未来深度成本，不含方向性价格风险。LP 手续费设为零，仅展示库存与盈亏平衡。\n\n'
    summary+='## 复核入口\n\n- decisions.md：按规则挑选的三份判断与风险。\n- reconciliation.json、ledger.json：独立资产汇总与逐笔记录。\n- models/：冻结参数、样本外误差、失败案例；external 缺失表示跨日期检验仍待完成。\n- first_book_working.json：逐档输入与中间量；独立固定答案见 docs/INDEPENDENT_CHECKS.md。\n'
    (out/'report.md').write_text(summary,encoding='utf-8')
    log('analysis_complete',output=str(out),kind=m['kind'],quality=quality)
    return quality


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--manifest',required=True);p.add_argument('--output',required=True)
    p.add_argument('--external-model')
    a=p.parse_args();print(json.dumps(run(a.manifest,a.output,a.external_model),indent=2))
