"""组件入口：读取早期看板可选JSON，文件缺失返回None供页面提示。；读取早期看板Parquet表，文件缺失返回空表，不创造行情。"""
from pathlib import Path
import json
import pandas as pd
import plotly.express as px
import streamlit as st

ROOT=Path(__file__).resolve().parent
st.set_page_config(page_title='Execution Replay',page_icon='📊',layout='wide')
st.title('执行分析与仓位回放')
st.caption('ML-assisted execution research · 固定窗口 · 离线核验 · 无实盘下单')
options=sorted(p for p in (ROOT/'reports').glob('*/quality.json') if (p.parent/'comparisons.parquet').exists())
if not options:
    st.info('尚无分析结果。先按 README 生成明确标注的合成演示，或分析已冻结的真实数据。')
    st.stop()
chosen=st.sidebar.selectbox('结果包',options,format_func=lambda p:p.parent.name)
folder=chosen.parent
def read(name):
    """读取早期看板可选JSON，文件缺失返回None供页面提示。

    输入参数：name（单位和范围由下方校验及调用方契约限定）。"""
    p=folder/name
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else None
def frame(name):
    """读取早期看板Parquet表，文件缺失返回空表，不创造行情。

    输入参数：name（单位和范围由下方校验及调用方契约限定）。"""
    p=folder/name
    return pd.read_parquet(p) if p.exists() else pd.DataFrame()
q=read('quality.json');m=read('manifest.json')
if m['kind']=='synthetic':st.warning('合成测试数据：仅证明软件流程。所有价格、预测误差与盈亏均不可作为真实市场业绩。')
elif m['kind']=='smoke':st.warning('短时真实预检样本：不满足正式六小时研究窗口。')
else:st.info('真实只读市场数据；成交、费用与 LP 仓位仍是模拟。')
st.caption(f"窗口：{pd.to_datetime(m['start'],unit='s',utc=True)} → {pd.to_datetime(m['end'],unit='s',utc=True)} · UTC")
page=st.sidebar.radio('分析视图',['执行与机器学习','库存与对账','LP 与研究结论'])
if page=='执行与机器学习':
    a,b,c=st.columns(3)
    a.metric('CEX 秒桶覆盖率',f"{q['cex']['coverage']:.1%}")
    b.metric('有效比较组',q.get('valid_groups','—'))
    c.metric('真实数据覆盖率验收','通过' if q.get('market_acceptance') else '未通过 / 尚未完成')
    comp=frame('comparisons.parquet')
    if len(comp):
        side=st.selectbox('方向',['buy','sell'])
        filt=comp[comp.side==side]
        ts=sorted(filt.available_at.unique())
        idx=st.slider('回放时间索引',0,len(ts)-1,0) if len(ts)>1 else 0
        at=filt[filt.available_at==ts[idx]]
        st.caption(str(pd.to_datetime(ts[idx],unit='s',utc=True)))
        plot=at.melt(id_vars=['quantity'],value_vars=['cex_cost_bps','dex_cost_bps'],var_name='场所',value_name='全成本 bps')
        st.plotly_chart(px.line(plot,x='quantity',y='全成本 bps',color='场所',markers=True),width='stretch')
        st.dataframe(at,width='stretch')
        st.caption('DEX 已含池费；另计 gas。CEX 使用假设费率。报价不保证成交。')
        with st.expander('费用敏感性与数据质量'):
            st.dataframe(frame('fee_sensitivity.parquet').head(100),width='stretch')
            st.json(q)
    else:st.info('没有通过新鲜度检查的跨场所比较。')
    st.subheader('未来 60 秒执行成本预测')
    models=folder/'models'
    if not (models/'model_manifest.json').exists():
        st.info('尚无达到样本要求的冻结模型。')
    else:
        mm=json.loads((models/'model_manifest.json').read_text(encoding='utf-8'))
        st.caption(f"验证集选择：{mm['selected']}；最多六次拟合；目标不含等待期间方向性价格涨跌。")
        for label,title in [('internal','主样本内部测试'),('external','另一天独立留出')]:
            st.markdown(f'**{title}**')
            metrics=models/f'{label}_metrics.json'
            if not metrics.exists():st.info('待完成，不能用内部测试代替。');continue
            st.dataframe(pd.DataFrame(json.loads(metrics.read_text())).T,width='stretch')
            pred=pd.read_parquet(models/f'{label}_predictions.parquet')
            pred['UTC']=pd.to_datetime(pred.t,unit='s',utc=True)
            fig=px.line(pred,x='UTC',y=['y','baseline','ridge','tree'],labels={'value':'价格成本 bps'})
            st.plotly_chart(fig,width='stretch')
        with st.expander('模型冻结、系数与防泄漏证据'):st.json(mm)
    with st.expander('场所与费用决策记录'):
        for decision in (read('decisions.json') or [])[:2]:st.json(decision)
elif page=='库存与对账':
    audits=read('reconciliation.json')
    if audits is None:st.info('当前结果包不包含账本。')
    else:
        st.success('两场景独立对账通过') if all(v['ok'] for v in audits.values()) else st.error('发现对账差异')
        equity=frame('equity.parquet')
        if len(equity):
            equity['UTC']=pd.to_datetime(equity.t,unit='s',utc=True)
            st.plotly_chart(px.line(equity,x='UTC',y='pnl',color='venue',labels={'pnl':'模拟 P&L / USDC'}),width='stretch')
        events=read('ledger.json')
        st.dataframe(pd.DataFrame(events).drop(columns=['balances'],errors='ignore'),width='stretch')
        st.caption('12 笔固定意向订单/场景用于账本验收，不代表交易策略。缺口不插值估值。')
        with st.expander('独立现金流对账'):st.json(audits)
        with st.expander('拒单与剩余风险'):st.json((read('decisions.json') or [{}])[-1])
else:
    lp=read('lp.json')
    if lp:
        st.caption(f"固定区间 {lp['lower']:.2f}–{lp['upper']:.2f} USDC/ETH；初始名义价值 1,000 USDC")
        table=pd.DataFrame(lp['scenarios'])
        st.plotly_chart(px.bar(table,x='shock',y='fee_to_break_even',labels={'shock':'价格冲击','fee_to_break_even':'相对 HODL 打平所需费用收入 / USDC'}),width='stretch')
        st.dataframe(table,width='stretch')
        path=frame('lp_path.parquet')
        if len(path):
            path['UTC']=pd.to_datetime(path.t,unit='s',utc=True)
            st.plotly_chart(px.line(path,x='UTC',y=['lp_value','hodl_value']),width='stretch')
        st.info('手续费收入设为零；这是库存与盈亏平衡情景，不是历史池子盈利还原。')
    else:st.info('无有效 DEX 状态，LP 结果未生成。')
    report=folder/'report.md'
    if report.exists():st.markdown(report.read_text(encoding='utf-8'))
    st.download_button('下载报告',report.read_text(encoding='utf-8') if report.exists() else '',file_name='report.md')
st.sidebar.markdown('---')
st.sidebar.caption('完整进度与限制：项目 BUILD_LOG.md。时间均使用 UTC；本地运行不发送订单。')
