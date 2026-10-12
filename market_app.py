"""双语订单研究看板：只展示操作、交易结果与图表解释。"""
from datetime import date, datetime, time as day_time, timedelta, timezone
import json
from decimal import Decimal
from pathlib import Path
import pandas as pd
import plotly.express as px
import streamlit as st
from core.experiment_engine import local_days, probe_latest
from core.task_manager import (submit_execution as submit, get_execution_job as get_job, get_execution_result as get_result, execution_history as recent_jobs, cancel_any as cancel, submit_task, get_task, list_tasks, retry_task, ensure_worker)
from core.cross_venue import ingest_okx_upload
from core.task_manager import cancel_any as cancel_cross_job, cross_job as get_cross_job, cross_result as get_cross_report, cross_history as recent_cross_jobs, submit_cross as submit_cross_venue
from core.optimizer import run_static_snapshot
from core.passive import load_bybit_passive_day, simulate_passive_limit
from core.conditional_model import list_conditional_models, train_conditional_model
from core.mpc import bybit_days, run_mpc_replay
from core.limit_optimizer import run_limit_optimization, RUN_ROOT as LIMIT_RUN_ROOT
from core.acceptance import list_acceptance
from core.task_manager import submit_sealed as submit_acceptance, get_task as acceptance_job, cancel_any as cancel_acceptance
from core.io import ROOT
from core.dashboard_errors import describe_failure

st.set_page_config(page_title='Execution Research', layout='wide')
heading, language_box = st.columns([6, 1])
with language_box:
    language = st.selectbox('Language / 语言', ['English', '中文'], key='ui_language')


def t(english, chinese):
    """选择对应语言的界面文字；首次访问默认使用英语。"""
    return chinese if language == '中文' else english


def word(value):
    """把后台方向、状态与方案标识转成业务名称，原报告不变。"""
    names = {'buy': ('Buy ETH','买入 ETH'), 'sell': ('Sell ETH','卖出 ETH'),
        'complete': ('Completed','已完成'), 'completed': ('Completed','已完成'),
        'optimal': ('Completed','已完成'), 'partial': ('Partially filled','部分成交'),
        'rejected': ('Not filled','未成交'), 'infeasible': ('Not filled','未成交'),
        'running': ('Running','运行中'), 'queued': ('Waiting','等待中'),
        'failed': ('Failed','失败'), 'interrupted': ('Interrupted','已中断'), 'cancelled': ('Cancelled','已取消'),
        'conservative': ('Longer queue','较长排队'), 'middle': ('Medium queue','中等排队'),
        'optimistic': ('Shorter queue','较短排队'),
        'immediate': ('Execute as early as allowed','尽早执行'), 'mpc': ('Adaptive execution','动态执行'),
        'equal_slice': ('Equal-size batches','等额分批'),
        'execution_cost': ('Execution cost','执行成本'), 'volatility': ('Price volatility','价格波动'),
        'adverse_mid_bps': ('Adverse price move (bps)','不利价格变化（bps）'),
        'execution_cost_bps': ('Execution cost (bps)','执行成本（bps）'),
        'volatility_bps': ('Price volatility (bps)','价格波动（bps）'),
        'future_execution_cost_bps': ('Execution cost (bps)','执行成本（bps）'),
        'future_volatility_bps': ('Price volatility (bps)','价格波动（bps）'),
        'persistence': ('Recent-market baseline','近期行情基线'),
        'candidate': ('Candidate prediction','候选预测'), 'selected': ('Selected prediction','选定预测'),
        'quoted': ('Quoted','已报价'),'unavailable': ('Unavailable','不可用'),'Swap': ('Swap','兑换'),'Mint': ('Add liquidity','增加流动性'),'Burn': ('Remove liquidity','移除流动性'),
        'ridge': ('Linear prediction','线性预测'), 'hgb': ('Tree prediction','树模型预测')}
    if value.startswith('immediate_') or value.startswith('frozen_ml_'):
        name=t('Immediate execution','立即执行') if value.startswith('immediate_') else t('Prediction-based execution','预测辅助执行')
        return name+' · '+value.rsplit('_',1)[1]+' '+t('s delay','秒延迟')
    return t(*names[value]) if value in names else value


def table(rows, columns):
    """只选业务列并翻译列名与状态，隐藏嵌套报告、代码地址和工程字段。"""
    frame=pd.DataFrame(rows)
    keys=[k for k in columns if k in frame.columns]
    frame=frame[keys].copy()
    for key in keys:
        frame[key]=frame[key].map(lambda v: word(v) if isinstance(v,str) else v)
    st.dataframe(frame.rename(columns={k:t(*columns[k]) for k in keys}),width='stretch',hide_index=True)


def chart(frame, x, series, y_label=('USDC','USDC'), bar=False):
    """在副本中翻译曲线名称及坐标轴，绘制曲线或柱图，不改动历史数据。"""
    labels={k:t(*v) for k,v in series.items()}
    plot=(px.bar if bar else px.line)(frame.rename(columns=labels),x=x,y=list(labels.values()),
        labels={x:t('Time (UTC)','时间（UTC）'),'value':t(*y_label),'variable':t('Series','曲线')})
    st.plotly_chart(plot,width='stretch')


def download(report, filename, key):
    """下载完整结果文件；不把 JSON 或指令直接渲染在页面上。"""
    st.download_button(t('Download results','下载结果'),json.dumps(report,ensure_ascii=False,indent=2,default=str).encode('utf-8'),file_name=filename,mime='application/json',key=key)


def read(path):
    """读取可选历史报告，缺失时返回空值，让页面提示暂无结果。"""
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None


@st.cache_data(show_spinner=False,max_entries=2)
def cached_bybit_passive_day(day):
    """缓存最多两个日期的盘口和成交，减少限价表单重复读盘。"""
    return load_bybit_passive_day(day)


def error_message(exc):
    """显示实际失败原因及常见问题的双语建议，完整异常仅保存在后台日志。"""
    from core.io import log
    log('dashboard_request_failed',reason=str(exc),error_type=type(exc).__name__)
    st.error(t('Unable to complete this request: ', '未能完成本次请求：') + describe_failure(exc, language == '中文'))


def progress(job):
    """把后台任务阶段归纳为进度说明，内部处理日志不放到看板。"""
    value=float(job.get('progress',0))
    if job.get('total'):
        value=job.get('completed',0)/job['total']
    st.progress(min(1.,max(0.,value)),text=t('Preparing data and comparing plans…','正在准备数据并比较方案…'))


FILL_COLUMNS={'strategy': ('Plan','方案'),'scenario': ('Queue scenario','排队情景'),
    'status': ('Outcome','成交情况'),'completion_pct': ('Completed (%)','完成比例（%）'),
    'filled_quantity': ('Filled (ETH)','成交数量（ETH）'),'filled_base': ('Filled (ETH)','成交数量（ETH）'),
    'unfilled_quantity': ('Unfilled (ETH)','未成交数量（ETH）'),
    'average_price': ('Average price (USDC/ETH)','成交均价（USDC/ETH）'),
    'fee_quote': ('Fees (USDC)','手续费（USDC）'),'net_quote': ('Payment / proceeds (USDC)','支出／收入（USDC）'),
    'execution_seconds': ('Execution time (s)','执行用时（秒）')}
with heading:
    st.title(t('Order Execution Research','订单执行研究'))
    st.caption(t('Compare where, when and how to trade.','比较在哪成交、何时成交，以及如何下单。'))
pages={'执行研究工作台': ('Simulate an order','模拟一笔订单'),
    '跨所数据与套利': ('Exchange comparison','交易所比较'),
    '优化求解与限价情景': ('Compare execution plans','比较执行方案'),
    '历史研究与 ML': ('Forecast performance','预测效果'),
    '成交量与订单流': ('Volume and buying pressure','成交量与买卖力量'),
    '执行回放与风险': ('Historical execution results','历史执行结果'),
    'DeFi 与 LP 历史': ('Liquidity pool performance','流动性池表现')}
page=st.sidebar.radio(t('Explore','功能导航'),list(pages),format_func=lambda v:t(*pages[v]),key='navigation')
home=ROOT/'data'/'historical';out=home/'research'


def render_experiment_result(experiment_id,context='active'):
    """轮询实验并展示即时／分批执行的完成量、费用及逐次成交，支持取消和下载。"""
    job=get_job(experiment_id)
    if not job:
        st.warning(t('This run is unavailable.','找不到这次运行。'));return
    if job['status'] in ('queued','running'):
        progress(job)
        if st.button(t('Cancel run','取消运行'),key=f'cancel_{experiment_id}'):
            cancel(experiment_id)
        return
    if job['status'] == 'failed':
        st.error(t('Simulation failed: ', '模拟失败：') + describe_failure(job.get('error') or job.get('reason'), language == '中文'))
        return
    if job['status'] == 'cancelled':
        st.info(word(job['status']));return
    result=get_result(experiment_id)
    if not result:
        st.info(t('Results are not available yet.','结果尚未准备好。'));return
    st.caption(f"{result['data']['venue'].upper()} · ETH/USDC · {', '.join(result['window']['available_utc_days'])} UTC")
    for col,key,label in zip(st.columns(2),['immediate','equal_slice_baseline'],[('Trade at the start','开始时一次成交'),('Equal-size batches','等额分批')]):
        item=result['results'][key]
        with col:
            st.subheader(t(*label))
            st.write(word(item['status']))
            if item.get('reason') in ('decision_stale_book_at_arrival', 'decision_no_book_at_or_before_arrival'):
                st.warning(t('No recent quote is available at the chosen start time. Try another time or adjust the maximum quote age.',
                             '所选开始时刻没有有效的新鲜报价，请换一个时刻或调整报价有效时间。'))
            # 旧报告的未成交分支缺少汇总字段；由实际成交明细推导费用与金额，不改写历史文件。
            fee_quote = Decimal(str(item.get('fee_quote', sum(Decimal(str(f['fee'])) for f in item['fills']))))
            gross_quote = sum(Decimal(str(f['gross_quote'])) for f in item['fills'])
            net_quote = Decimal(str(item.get('net_quote', gross_quote + fee_quote if result['config']['side'] == 'buy' else gross_quote - fee_quote)))
            a,b,c=st.columns(3)
            a.metric(t('Completed','完成比例'),f"{item['completion_pct']:.2f}%")
            b.metric(t('Filled ETH','成交 ETH'),f"{float(item['filled_base']):.8f}")
            c.metric(t('Fees (USDC)','手续费（USDC）'),f"{float(fee_quote):.4f}")
            st.write(t('Payment / proceeds (USDC)','支出／收入（USDC）'),f"{float(net_quote):,.4f}")
            if item.get('average_price'):
                st.write(t('Average price (USDC/ETH)','成交均价（USDC/ETH）'),f"{float(item['average_price']):,.4f}")
                st.write(t('Cost above the starting midpoint, including fees (bps)','相对开始时中间价的含费成本（bps）'),f"{float(item['all_in_shortfall_bps']):.3f}")
            if item.get('unspent_quote') is not None:
                st.write(t('Unspent USDC','剩余 USDC'),f"{float(item['unspent_quote']):.4f}")
            if item.get('remaining_base') is not None:
                st.write(t('Unfilled ETH','未成交 ETH'),f"{float(item['remaining_base']):.8f}")
    st.caption(t('The midpoint is halfway between the best buy and sell prices. Lower cost means trading closer to this reference.','中间价是最优买价与卖价的平均值。成本越低，成交越接近这个参照。'))
    rows=[dict(strategy=t('At the start','开始时成交') if name=='immediate' else t('Batches','分批成交'),time=fill['scheduled_at_utc'],status=fill['status'],quantity=fill['filled'],price=fill['vwap'],fee=fill['fee']) for name,item in result['results'].items() for fill in item['fills']]
    table(rows,{'strategy': ('Plan','方案'),'time': ('Scheduled time (UTC)','计划时间（UTC）'),'status': ('Outcome','成交情况'),'quantity': ('ETH','ETH'),'price': ('Price (USDC/ETH)','价格（USDC/ETH）'),'fee': ('Fees (USDC)','手续费（USDC）')})
    download(result,f'execution-{experiment_id}.json',f'dl_{context}_{experiment_id}')
    st.download_button(t('Download trades (CSV)','下载成交表（CSV）'),pd.DataFrame(rows).to_csv(index=False).encode('utf-8-sig'),file_name=f'execution-{experiment_id}.csv',key=f'csv_{context}_{experiment_id}')


def render_cross_venue_job(job_id,context='active'):
    """展示跨所进度与双向扣费价差；Binance 仅作成交价参照，不作为盘口执行报价。"""
    job=get_cross_job(job_id)
    if not job:return
    if job['status'] in ('queued','running'):
        progress(job)
        if st.button(t('Cancel comparison','取消比较'),key=f'cancel_cross_{job_id}'):cancel_cross_job(job_id)
        return
    if job['status']=='failed':
        st.error(t('Comparison failed: ', '比较失败：') + describe_failure(job.get('error') or job.get('reason'), language == '中文'))
        return
    if job['status']!='completed':
        st.warning(word(job['status']));return
    report=get_cross_report(job_id)
    if not report:return
    sync,arb,binance=report['synchronization'],report['arbitrage'],report['binance']
    st.caption(f"{report['window']['day_utc']} UTC · ETH/USDC")
    a,b=st.columns(2)
    a.metric(t('Comparable observations','可比较时点'),f"{sync['matched_points']:,}")
    b.metric(t('Positive net-spread observations','扣费后价差为正的时点'),f"{arb['positive_snapshot_seconds_any_direction']:,}")
    rows=[]
    for key,label in [('buy_bybit_sell_okx',('Buy Bybit → sell OKX','Bybit 买入 → OKX 卖出')),('buy_okx_sell_bybit',('Buy OKX → sell Bybit','OKX 买入 → Bybit 卖出'))]:
        r=arb[key];rows.append(dict(route=t(*label),positive=r['positive_points'],share=r['positive_share_pct'],best=r['best_single_snapshot_net_usdc']))
    table(rows,{'route': ('Route','方向'),'positive': ('Positive observations','正价差时点'),'share': ('Positive share (%)','正价差占比（%）'),'best': ('Best net spread (USDC)','最高单笔净价差（USDC）')})
    st.caption(t('Each point compares buying and selling the same ETH amount after both fees, with balances on both exchanges. Individual spreads are not added together as profit.','每个时点比较同等 ETH 数量的买入与卖出，并扣除两边手续费，资金分别在两所。单次价差不累加为收益。'))
    aligned=pd.read_parquet(Path(report['result_path']));sample=aligned.iloc[::max(1,len(aligned)//5000)]
    chart(sample,'utc',{'buy_bybit_sell_okx_net_usdc': ('Buy Bybit / sell OKX','Bybit 买入／OKX 卖出'),'buy_okx_sell_bybit_net_usdc': ('Buy OKX / sell Bybit','OKX 买入／Bybit 卖出')},('Net spread (USDC)','扣费后价差（USDC）'))
    if binance['matched_trade_references']:
        st.subheader(t('Binance traded-price comparison','Binance 成交价比较'))
        st.caption(t('Compare the latest Binance trade with each exchange midpoint. Order-book execution comparisons use Bybit and OKX.','比较 Binance 最近成交价与各所中间价。按盘口计算成交的比较使用 Bybit 和 OKX。'))
        chart(sample,'utc',{'binance_vs_bybit_mid_bps': ('Compared with Bybit','相对 Bybit'),'binance_vs_okx_mid_bps': ('Compared with OKX','相对 OKX')},('Price difference (bps)','价差（bps）'))
    download(report,f'cross-{job_id}.json',f'cross_json_{context}_{job_id}')


def render_static_report(report,context='active'):
    """展示已保存的跨所分配结果，语言切换只重绘表格，不重新求解。"""
    result=report['result'];st.success(word(result['status']))
    a,b=st.columns(2)
    a.metric(t('Filled ETH','成交 ETH'),f"{float(result['filled_base']):.8f}")
    b.metric(t('Payment / proceeds (USDC)','支出／收入（USDC）'),f"{float(result['net_quote']):,.4f}")
    table([dict(venue=v.upper(),**r) for v,r in result['allocation'].items()],{'venue': ('Exchange','交易所'),'base': ('ETH','ETH'),'gross_quote': ('Trade amount (USDC)','成交金额（USDC）'),'fee_quote': ('Fees (USDC)','手续费（USDC）'),'net_quote': ('Payment / proceeds (USDC)','支出／收入（USDC）')})
    st.caption(t('More of the order goes to the better price after fees, within each exchange balance and available depth.','优先分配到含费价格更好的交易所，并受该所余额和挂单数量限制。'))
    download(report,f"static-{report['run_id']}.json",'static_download_'+context)


def render_mpc_report(report,context='active'):
    """展示已保存的动态执行比较与逐次决策，切换语言不触发回放。"""
    table([dict(strategy=name,**v) for name,v in report['results'].items()],FILL_COLUMNS)
    st.caption(t('All plans use the same fees, balances and per-step limit. Lower payment is better for buys; higher proceeds are better for sells.','所有方案使用相同手续费、余额和单次成交上限。买入看支出更低，卖出看收入更高。'))
    rows=[]
    for item in report['results']['mpc']['decisions']:
        schedule=item.get('plan',{}).get('schedule',[]);forecast=schedule[0].get('forecast',{}) if schedule else {}
        rows.append(dict(time=item['decision_at_utc'],planned=item['planned_quantity'],filled=item.get('actual_filled_quantity',0),move=forecast.get('adverse_mid_bps'),cost=forecast.get('execution_cost_bps')))
    table(rows,{'time': ('Decision time (UTC)','决策时间（UTC）'),'planned': ('Planned ETH','计划 ETH'),'filled': ('Filled ETH','成交 ETH'),'move': ('Forecast price disadvantage (bps)','预测不利价格变化（bps）'),'cost': ('Forecast execution cost (bps)','预测执行成本（bps）')})
    download(report,f"mpc-{report['run_id']}.json",'mpc_download_'+context)


def render_passive_report(result,context='active'):
    """展示已保存的三种限价队列结果，语言切换保持模拟输出。"""
    table([dict(scenario=r['name'],**r) for r in result['scenarios']],FILL_COLUMNS)
    st.caption(t('Different queues show how orders ahead affect fills; these are scenarios rather than measured probabilities.','不同队列展示前方订单对成交的影响，是不同情景，不是测得的概率。'))
    download(result,'limit-order.json','passive_download_'+context)


@st.fragment(run_every='2s')
def render_background_task(identifier, result_key=None, renderer=None):
    """轮询独立后台任务，页面重绘不再次提交；显示取消、失败原因和完成结果。"""
    if not identifier:return
    task=get_task(identifier)
    if not task:return
    if task['status'] in ('queued','running'):
        progress(task)
        st.caption(t('Cancellation takes effect at the next calculation checkpoint.','取消将在下一个计算检查点生效。'))
        if st.button(t('Cancel run','取消运行'),key='task_cancel_'+identifier):cancel(identifier)
    elif task['status'] in ('failed','interrupted'):
        st.error(t('Run failed: ','运行未完成：')+describe_failure(task.get('error'),language=='中文'))
    elif task['status']=='completed':
        if result_key:st.session_state[result_key]=task['result']
        if renderer:renderer(task['result'])
        elif task['kind']=='limit' and st.session_state.get('limit_activated')!=identifier:
            st.session_state['s3_activate']=Path(task['result']['report_path'])
            st.session_state['limit_activated']=identifier
            st.rerun()
        else:st.success(t('Completed.','已完成。'))
    else:st.info(word(task['status']))


def render_channel_report(report):
    """展示单笔跨交易所／池报价与 gas 成本，不把 WETH 与原生 ETH 默认为同一结算资产。"""
    table(report['rows'],{'channel': ('Channel','渠道'),'asset': ('Received / sold asset','收到／卖出资产'),'status': ('Availability','可用情况'),
        'quantity': ('ETH / WETH','ETH／WETH'),'trade_quote': ('Trade amount (USDC)','成交金额（USDC）'),'fee_usdc': ('Exchange fees (USDC)','交易所手续费（USDC）'),
        'gas_usdc': ('Gas value (USDC)','Gas 折合（USDC）'),'total_quote': ('Total payment / proceeds (USDC)','总支出／收入（USDC）'),'state_time': ('Market state time (UTC)','行情状态时间（UTC）')})
    for row in report['rows']:
        if row.get('reason'):st.warning(row['channel']+': '+describe_failure(row['reason'],language=='中文'))
    st.caption(t('The pool quote includes its trading fee. Gas is estimated from your gas-unit setting and the historical block fee. Uniswap settles WETH; approval and wrapping costs are not included.','池报价已包含池手续费。Gas 按你设置的用量和历史区块费估算；Uniswap 使用 WETH 结算，不含授权或包装成本。'))


def render_chain_report(report,context='active'):
    """展示逐事件下载摘要和有限预览，时间戳按区块展示，不制造区块内每笔独立时间。"""
    st.metric(t('Pool events','池事件数量'),report['event_count'])
    table(report['preview'],{'event': ('Event','事件'),'block_time_utc': ('Block time (UTC)','区块时间（UTC）'),
        'transaction_index': ('Order within block','区块内交易顺序'),'log_index': ('Event order','事件顺序'),
        'usdc_pool_delta': ('Pool USDC change','池 USDC 变化'),'weth_pool_delta': ('Pool WETH change','池 WETH 变化'),'tick': ('Price tick','价格刻度')})
    st.caption(t('Trades in the same block share its timestamp. The table preserves their order; it does not assign individual second timestamps.','同一区块内的兑换共用区块时间，表格保留先后顺序，不为每笔分配独立秒级时间。'))
    if Path(report['events_path']).exists():
        st.download_button(t('Download all pool events','下载全部池事件'),Path(report['events_path']).read_bytes(),file_name='pool-events.json',key='event_download_'+context+'_'+report['created_at'])

if page=='执行研究工作台':
    st.header(t('Simulate a historical order','模拟一笔历史订单'))
    st.write(t('Choose a time and an order. Compare trading at the start with equal-size batches.','选择时间与订单，比较开始时一次成交和等额分批成交。'))
    known=local_days();latest=date.fromisoformat(known[-1]) if known else date.today()-timedelta(days=2)
    if st.button(t('Find the latest Bybit date','查找最新可用 Bybit 日期'),key='probe_latest'):
        try:
            with st.spinner(t('Checking dates…','正在查找日期…')):
                st.session_state['experiment_default_day']=date.fromisoformat(probe_latest()['day'])
        except Exception as exc:error_message(exc)
    # 方向和输入单位放在表单外，选择后立即刷新金额控件，避免提交时还显示旧单位。
    side=st.radio(t('Direction','方向'),['buy','sell'],format_func=word,horizontal=True,key='experiment_side_v2')
    side={'Buy ETH':'buy','买入 ETH':'buy','Sell ETH':'sell','卖出 ETH':'sell'}.get(side,side)
    mode=st.radio(t('Order size expressed as','订单规模输入方式'),['quote_budget','base_quantity'] if side=='buy' else ['base_quantity'],format_func=lambda v:t('USDC budget including fees','含手续费的 USDC 预算') if v=='quote_budget' else t('ETH quantity','ETH 数量'),key='experiment_mode_v2')
    mode={'USDC budget including fees':'quote_budget','含手续费的 USDC 预算':'quote_budget','ETH quantity':'base_quantity','ETH 数量':'base_quantity'}.get(mode,mode)
    with st.form('execution_experiment_form'):
        venue=st.selectbox(t('Exchange','交易所'),['bybit','okx'],format_func=str.upper,key='experiment_venue')
        st.caption(t('ETH/USDC · Upload an OKX archive on Exchange comparison before using a new OKX date.','ETH/USDC · 使用新的 OKX 日期前，请在交易所比较页上传档案。'))
        zone=st.selectbox(t('Time zone','时区'),['Asia/Shanghai','UTC'],key='experiment_zone')
        day=st.session_state.get('experiment_default_day',latest)
        dates=st.date_input(t('Date range (up to 7 days)','日期范围（最多 7 天）'),value=(day,day),max_value=date.today(),key='experiment_dates')
        clock=st.time_input(t('Start time','开始时间'),day_time(12),key='experiment_time')
        horizon=st.number_input(t('Finish within (minutes)','完成期限（分钟）'),1,1440,10,key='experiment_horizon')
        amount=st.number_input(t('USDC budget','USDC 预算') if mode=='quote_budget' else t('ETH quantity','ETH 数量'),min_value=.00000001,value=5000.0 if mode=='quote_budget' else .5,format='%.8f',key='experiment_amount_'+mode)
        fee=st.number_input(t('Trading fee (bps)','交易手续费（bps）'),0.0,100.0,10.0,.5,key='experiment_fee',help=t('10 bps = 0.1%. Use your account fee.','10 bps = 0.1%，请填写账户费率。'))
        delay=st.number_input(t('Order delay (ms)','下单延迟（毫秒）'),0,5000,250,50,key='experiment_delay')
        age=st.number_input(t('Maximum quote age (ms)','报价最长有效时间（毫秒）'),100,5000,3000,100,key='experiment_age')
        slices=st.number_input(t('Number of equal batches','等额分批次数'),2,60,10,key='experiment_slices')
        step=st.text_input(t('Quantity increment (ETH)','数量步长（ETH）'),'0.00000001',key='experiment_step')
        completion=st.slider(t('Minimum completion alert (%)','最低完成比例提醒（%）'),0,100,95,key='experiment_completion')
        start=st.form_submit_button(t('Prepare data and simulate','准备数据并运行模拟'),type='primary')
    if start:
        try:
            if len(dates)!=2 or (dates[1]-dates[0]).days not in range(7) or float(step)<=0:raise ValueError('Invalid date range or increment')
            if any(j['status']=='running' for j in recent_jobs()):
                st.warning(t('Wait for the current run or cancel it first.','请等待当前运行完成，或先取消它。'))
            else:
                config=dict(venue=venue,symbol='ETHUSDC',timezone=zone,start_date=dates[0].isoformat(),end_date=dates[1].isoformat(),start_time=clock.isoformat(),horizon_seconds=horizon*60,side=side,amount_mode=mode,amount=str(amount),fee_bps=str(fee),order_latency_ms=delay,max_book_age_ms=age,quantity_step=step.strip(),twap_slices=slices,min_completion_pct=completion)
                st.session_state['active_experiment_id']=submit(config)
        except Exception as exc:error_message(exc)
    @st.fragment(run_every='2s')
    def live_experiment():
        """只轮询当前实验，不在刷新时重复提交订单。"""
        if st.session_state.get('active_experiment_id'):render_experiment_result(st.session_state['active_experiment_id'])
    live_experiment()
    with st.expander(t('Previous simulations','历史模拟')):
        for job in recent_jobs():
            with st.expander(f"{job.get('created_at','')[:19]} · {word(job['status'])} · {job.get('config',{}).get('start_date','')}"):
                if job['status'] in ('completed','failed'):render_experiment_result(job['id'],'history')
                else:st.write(word(job['status']))

elif page=='跨所数据与套利':
    st.header(t('Compare exchanges on the same day','比较同一天的不同交易所'))
    st.write(t('Compare Bybit and OKX buy/sell costs and net price differences. Binance provides traded-price context.','比较 Bybit 与 OKX 买卖成本和扣费价差，同时观察 Binance 成交价格。'))
    selected=st.date_input(t('Date (UTC)','日期（UTC）'),date(2026,10,1),max_value=date.today(),key='cross_venue_day')
    day=selected.isoformat();market=ROOT/'data'/'experiments'/'market';source=market/'okx'/'ETH-USDC'/day/'source.tar.gz'
    table([dict(venue=v,data=t('Trades','逐笔成交') if v=='Binance' else t('Order book','买卖盘口'),status=t('Ready','已准备') if ready else t('Upload archive','上传档案') if v=='OKX' else t('Download when run','运行时下载')) for v,ready in [('Bybit',(market/'bybit'/'ETHUSDC'/day/'books.parquet').exists()),('OKX',source.exists()),('Binance',(market/'binance'/'ETHUSDC'/day/'trades.parquet').exists())]],{'venue': ('Exchange','交易所'),'data': ('Available data','数据类型'),'status': ('Availability','可用情况')})
    if not source.exists():
        st.markdown(t('[Get the OKX historical archive](https://www.okx.com/en-us/historical-data) for spot ETH-USDC, 400 levels, and the selected UTC date.','[获取 OKX 历史档案](https://www.okx.com/en-us/historical-data)，选择现货 ETH-USDC、400 档和所选 UTC 日期。'))
        upload=st.file_uploader(t('Upload OKX archive','上传 OKX 档案'),type=['gz'],key=f'okx_upload_{day}')
        if upload and st.button(t('Save archive','保存档案'),key=f'okx_save_{day}'):
            try:ingest_okx_upload(day,upload.name,upload);st.rerun()
            except Exception as exc:error_message(exc)
    with st.form('cross_venue_form'):
        quantity=st.number_input(t('ETH amount per trade','每笔交易 ETH 数量'),min_value=.00000001,value=.1,format='%.8f',key='cross_quantity')
        bfee=st.number_input(t('Bybit fee (bps)','Bybit 手续费（bps）'),0.0,100.0,10.0,.5,key='cross_bfee')
        ofee=st.number_input(t('OKX fee (bps)','OKX 手续费（bps）'),0.0,100.0,10.0,.5,key='cross_ofee')
        delay=st.number_input(t('Order delay (ms)','下单延迟（毫秒）'),0,5000,250,50,key='cross_delay')
        age=st.number_input(t('Maximum quote age (ms)','报价最长有效时间（毫秒）'),100,10000,1500,100,key='cross_age')
        trade_age=st.number_input(t('Maximum Binance trade age (ms)','Binance 成交参照最长有效时间（毫秒）'),100,30000,3000,500,key='cross_trade_age')
        start=st.form_submit_button(t('Prepare data and compare','准备数据并比较'),type='primary')
    if start:
        try:
            if not source.exists():st.warning(t('Upload the OKX archive for this date first.','请先上传该日期的 OKX 档案。'))
            elif any(j['status'] in ('queued','running') for j in recent_cross_jobs()) or any(j['status']=='running' for j in recent_jobs()):st.warning(t('Wait for the current run or cancel it first.','请等待当前运行完成，或先取消它。'))
            else:st.session_state['active_cross_venue_id']=submit_cross_venue(dict(day=day,quantity_eth=str(quantity),bybit_fee_bps=str(bfee),okx_fee_bps=str(ofee),assumed_latency_ms=delay,max_book_age_ms=age,max_binance_trade_age_ms=trade_age))
        except Exception as exc:error_message(exc)
    @st.fragment(run_every='2s')
    def live_cross_venue():
        """轮询所选跨所任务，完成后显示同日比较图表。"""
        if st.session_state.get('active_cross_venue_id'):render_cross_venue_job(st.session_state['active_cross_venue_id'])
    live_cross_venue()
    with st.expander(t('Previous comparisons','历史比较')):
        for item in recent_cross_jobs(12):
            if st.button(f"{item.get('created_at','')[:19]} · {item.get('config',{}).get('day','')} · {word(item['status'])}",key=f"open_cross_{item['id']}"):
                st.session_state['active_cross_venue_id']=item['id'];st.rerun()

elif page=='优化求解与限价情景':
    st.header(t('Find an execution plan','比较与选择执行方案'))
    choices={'静态多场所路由': ('Trade across exchanges now','现在跨所成交'),'滚动执行（MPC）': ('Execute over time','分时动态执行'),'被动限价队列情景': ('Test a limit order','测试限价挂单'),'限价方案优化（S3）': ('Compare limit-order plans','比较限价方案')}
    choice=st.radio(t('What would you like to compare?','你想比较什么？'),list(choices),format_func=lambda v:t(*choices[v]),horizontal=True,key='optimizer_component')
    if choice=='静态多场所路由':
        st.caption(t('Split an order between Bybit and OKX using prices, fees and balances at your chosen time.','按所选时刻的价格、手续费和各所余额，在 Bybit 与 OKX 之间分配订单。'))
        with st.form('static_route_form'):
            day=st.date_input(t('Date (UTC)','日期（UTC）'),date(2026,10,1),max_value=date.today(),key='static_day')
            clock=st.time_input(t('Trade time (UTC)','成交时间（UTC）'),day_time(12),key='static_time')
            side=st.selectbox(t('Direction','方向'),['buy','sell'],format_func=word,key='static_side')
            mode=st.selectbox(t('Order goal','订单目标'),['base_quantity','quote_budget'] if side=='buy' else ['base_quantity'],format_func=lambda v:t('ETH quantity','ETH 数量') if v=='base_quantity' else t('USDC budget','USDC 预算'),key='static_amount_mode')
            amount=st.number_input(t('USDC budget','USDC 预算') if mode=='quote_budget' else t('ETH quantity','ETH 数量'),min_value=.00000001,value=5000.0 if mode=='quote_budget' else .1,format='%.8f',key='static_amount_'+mode)
            bfee=st.number_input(t('Bybit fee (bps)','Bybit 手续费（bps）'),0.0,100.0,10.0,.5,key='static_bfee')
            ofee=st.number_input(t('OKX fee (bps)','OKX 手续费（bps）'),0.0,100.0,10.0,.5,key='static_ofee')
            step=st.number_input(t('Quantity increment (ETH)','数量步长（ETH）'),min_value=.00000001,value=.00000001,format='%.8f',key='static_step')
            balances={}
            for venue in ['bybit','okx']:
                balances[venue]=str(st.number_input(t('Available','可用')+' '+venue.upper()+' '+('USDC' if side=='buy' else 'ETH'),min_value=0.0,value=5000.0 if side=='buy' else 1.0,key='static_balance_'+venue+side))
            delay=st.number_input(t('Order delay (ms)','下单延迟（毫秒）'),0,5000,250,50,key='static_latency')
            age=st.number_input(t('Maximum quote age (ms)','报价最长有效时间（毫秒）'),100,10000,1500,100,key='static_stale')
            start=st.form_submit_button(t('Find allocation','计算分配方案'),type='primary')
        if start:
            try:
                st.session_state['static_task']=submit_task('static',dict(day=day.isoformat(),utc_time=clock.isoformat(timespec='seconds'),side=side,amount_mode=mode,amount=amount,fees_bps={'bybit':bfee,'okx':ofee},quantity_step=step,quote_balances=balances if side=='buy' else None,base_balances=balances if side=='sell' else None,latency_ms=delay,max_age_ms=age))
            except Exception as exc:error_message(exc)
        render_background_task(st.session_state.get('static_task'),'static_result',render_static_report)

    elif choice=='滚动执行（MPC）':
        st.caption(t('Compare adaptive execution, early execution and equal batches on Bybit. Adaptive execution reassesses whether to trade or wait as prices change.','比较 Bybit 上的动态执行、尽早执行和等额分批。动态执行随行情变化重新判断成交还是等待。'))
        models=list_conditional_models()
        with st.expander(t('Prediction settings and performance','预测设置与效果')):
            st.write(t('Train on September 1–4 and compare predictions on September 5. A separate date measures performance on new data.','使用 9 月 1—4 日训练，在 5 日比较预测效果，再用新的日期检验表现。'))
            if st.button(t('Train a prediction model','训练预测模型'),key='train_conditional_model'):
                try:
                    st.session_state['training_task']=submit_task('training',{})
                except Exception as exc:error_message(exc)
            render_background_task(st.session_state.get('training_task'))
            table([dict(created=m['created_at'][:19],train=', '.join(m['training']['train_days']),validation=m['training']['validation_day']) for m in models],{'created': ('Created','创建时间'),'train': ('Training dates','训练日期'),'validation': ('Comparison date','比较日期')})
            if models:
                accept_day=st.date_input(t('New evaluation date (UTC)','新的评估日期（UTC）'),date.today()-timedelta(days=2),max_value=date.today()-timedelta(days=1),key='accept_day')
                accept_model=st.selectbox(t('Prediction version','预测版本'),[m['model_id'] for m in models],format_func=lambda v:next(m['created_at'][:19] for m in models if m['model_id']==v),key='accept_model')
                st.caption(t('Use a date not previously downloaded or evaluated. Each new date is evaluated once.','请选择未下载、未评估过的日期，每个新日期只评估一次。'))
                if st.button(t('Evaluate on new data','用新数据评估'),key='accept_start'):
                    try:st.session_state['acceptance_id']=submit_acceptance(accept_day.isoformat(),accept_model)
                    except Exception as exc:error_message(exc)
                @st.fragment(run_every=2)
                def show_acceptance_progress():
                    """只展示新日期评估的进度和取消入口，不渲染任务字典或运行日志。"""
                    active=st.session_state.get('acceptance_id');job=acceptance_job(active) if active else None
                    if job and job['status'] in ('queued','running'):
                        progress(job)
                        if st.button(t('Cancel evaluation','取消评估'),key='accept_cancel'):cancel_acceptance(active)
                    elif job and job['status']=='failed':
                        st.error(t('Evaluation failed: ', '评估失败：') + describe_failure(job.get('reason') or job.get('error'), language == '中文'))
                    elif job:st.write(word(job['status']))
                show_acceptance_progress()
            for entry in list_acceptance():
                if entry['report']:
                    st.subheader(entry['specification']['day']+' UTC')
                    table([dict(target=k,**v) for k,v in entry['report']['metrics'].items()],{'target': ('Prediction','预测目标'),'deployed_mae': ('Model average error (bps)','模型平均误差（bps）'),'persistence_mae': ('Baseline average error (bps)','基线平均误差（bps）')})
                    st.caption(t('Lower error is better. The baseline assumes recent conditions continue.','误差越低越好。基线假设近期行情状态延续。'))
                    download(entry['report'],f"evaluation-{entry['specification']['run_id']}.json",'accept_download_'+entry['specification']['run_id'])
                elif entry['failure']:
                    st.error(t('Evaluation failed: ', '评估失败：') + describe_failure(entry['failure'].get('reason'), language == '中文'))
        days=bybit_days()
        if not days:st.info(t('No historical order books are available yet.','暂无可用历史盘口。'))
        else:
            with st.form('mpc_replay_form'):
                day=st.selectbox(t('Date (UTC)','日期（UTC）'),days,index=days.index('2026-10-01') if '2026-10-01' in days else len(days)-1,key='mpc_day')
                clock=st.time_input(t('Start time (UTC)','开始时间（UTC）'),day_time(12),key='mpc_time')
                side=st.selectbox(t('Direction','方向'),['buy','sell'],format_func=word,key='mpc_side')
                qty=st.number_input(t('ETH quantity','ETH 数量'),min_value=.01,value=.30,step=.01,key='mpc_qty')
                horizon=st.selectbox(t('Finish within (s)','完成期限（秒）'),[30,60,120,300],index=1,key='mpc_horizon')
                interval=st.selectbox(t('Review every (s)','重新决策间隔（秒）'),[5,10,15,30],index=1,key='mpc_interval')
                cap=st.slider(t('Maximum share per step (%)','每次最多成交占总单比例（%）'),10,100,50,10,key='mpc_child_pct')
                fee=st.number_input(t('Trading fee (bps)','交易手续费（bps）'),0.0,100.0,10.0,.5,key='mpc_fee')
                risk=st.slider(t('Penalty for waiting risk','等待风险权重'),0.0,3.0,.5,.1,key='mpc_risk')
                balance=st.number_input(t('Available USDC','可用 USDC') if side=='buy' else t('Available ETH','可用 ETH'),min_value=0.0,value=5000.0 if side=='buy' else 1.0,key='mpc_balance_'+side)
                delay=st.number_input(t('Order delay (ms)','下单延迟（毫秒）'),0,5000,250,50,key='mpc_latency')
                age=st.number_input(t('Maximum quote age (ms)','报价最长有效时间（毫秒）'),100,10000,1500,100,key='mpc_stale')
                model=st.selectbox(t('Forecast','预测方式'),[None]+[m['model_id'] for m in models],format_func=lambda v:t('Use recent market conditions','延续近期行情') if v is None else next(m['created_at'][:19] for m in models if m['model_id']==v),key='mpc_model')
                start=st.form_submit_button(t('Compare execution plans','比较执行方案'),type='primary')
            if start:
                try:
                    with st.spinner(t('Comparing plans…','正在比较方案…')):
                        st.session_state['mpc_task']=submit_task('mpc',dict(day=day,utc_time=clock.isoformat(timespec='seconds'),side=side,quantity=qty,horizon_seconds=horizon,interval_seconds=interval,max_child_pct=cap,fee_bps=fee,risk_aversion=risk,quote_balance=balance if side=='buy' else 0,base_balance=balance if side=='sell' else 0,latency_ms=delay,max_book_age_ms=age,quantity_step='0.01',model_id=model))
                except Exception as exc:error_message(exc)
        if st.session_state.get('mpc_result'):
            render_mpc_report(st.session_state['mpc_result'])

    elif choice=='被动限价队列情景':
        st.caption(t('Try a limit price and waiting time on Bybit. Compare fills with longer, medium and shorter queues ahead of your order.','在 Bybit 测试挂单价格和等待时间，比较前方排队较长、中等和较短时的成交情况。'))
        days=sorted(p.stem.removesuffix('.trades') for p in (home/'trades').glob('*.trades.parquet'))
        if not days:st.info(t('No matching trade history is available.','暂无匹配的历史成交数据。'))
        else:
            with st.form('passive_limit_form'):
                day=st.selectbox(t('Date (UTC)','日期（UTC）'),days,index=min(2,len(days)-1),key='passive_day')
                clock=st.time_input(t('Order time (UTC)','下单时间（UTC）'),day_time(4),key='passive_time')
                side=st.selectbox(t('Direction','方向'),['buy','sell'],format_func=word,key='passive_side')
                try:
                    books,trades=cached_bybit_passive_day(day);stamp=datetime.combine(date.fromisoformat(day),clock,tzinfo=timezone.utc).timestamp()
                    current=books[books.available_at<=stamp+.250].iloc[-1]
                    default=float(json.loads(current.bids_json if side=='buy' else current.asks_json)[0][0])
                except Exception:default=2400.0
                qty=st.number_input(t('ETH quantity','ETH 数量'),min_value=.00000001,value=.5,format='%.8f',key='passive_qty')
                price=st.number_input(t('Limit price (USDC/ETH)','挂单价格（USDC/ETH）'),min_value=.01,value=round(default,2),step=.01,key='passive_limit_price')
                tick=st.number_input(t('Price increment (USDC)','价格步长（USDC）'),min_value=.00000001,value=.01,format='%.8f',key='passive_tick')
                horizon=st.number_input(t('Wait up to (s)','最多等待（秒）'),1,3600,60,5,key='passive_horizon')
                cancel_at=st.number_input(t('Cancel after (s; 0 = deadline)','提前撤单时间（秒；0 = 到期）'),0,3600,0,5,key='passive_cancel')
                delay=st.number_input(t('Order delay (ms)','下单延迟（毫秒）'),0,5000,250,50,key='passive_latency')
                start=st.form_submit_button(t('Test limit order','测试限价单'),type='primary')
            if start:
                try:
                    stamp=datetime.combine(date.fromisoformat(day),clock,tzinfo=timezone.utc).timestamp()
                    st.session_state['passive_task']=submit_task('passive',dict(day=day,decision_at=stamp,side=side,quantity=qty,limit_price=price,horizon_seconds=horizon,price_tick=tick,latency_ms=delay,cancel_after_seconds=cancel_at or None))
                except Exception as exc:error_message(exc)
        render_background_task(st.session_state.get('passive_task'),'passive_result',render_passive_report)

    else:
        st.caption(t('Compare trading immediately with waiting at a limit price, repricing once and completing the remainder. Add your original plan for comparison.','比较立即成交、限价等待、一次改价及补齐剩余数量，并加入你的原方案作对比。'))
        days=sorted(p.stem.removesuffix('.trades') for p in (home/'trades').glob('*.trades.parquet'))
        if not days:
            st.info(t('No matching trade history is available.','暂无匹配的历史成交数据。'));st.stop()
        with st.form('limit_optimizer_form'):
            day=st.selectbox(t('Date (UTC)','日期（UTC）'),days,key='s3_day')
            clock=st.time_input(t('Order time (UTC)','下单时间（UTC）'),day_time(12),key='s3_time')
            side=st.selectbox(t('Direction','方向'),['buy','sell'],format_func=word,key='s3_side')
            qty=st.number_input(t('ETH quantity','ETH 数量'),min_value=.00000001,value=.3,format='%.8f',key='s3_qty')
            waits=st.multiselect(t('Waiting times to compare (s)','待比较等待时长（秒）'),[5,10,20,30,60,120,300],default=[10,30],key='s3_waits')
            offsets=st.multiselect(t('Price offsets to compare (increments)','待比较价格偏移（步数）'),[0,1,2,5,10],default=[0,1,2],key='s3_offsets')
            st.caption(t('Zero offset uses the best bid for buys or best ask for sells. More increments set a less aggressive price.','零偏移用买一价挂买单、卖一价挂卖单。偏移越大，报价越不积极。'))
            maker=st.number_input(t('Limit-order fee (bps)','挂单手续费（bps）'),0.0,100.0,2.0,key='s3_maker')
            taker=st.number_input(t('Immediate-trade fee (bps)','主动成交手续费（bps）'),0.0,100.0,10.0,key='s3_taker')
            risk=st.slider(t('Penalty for waiting risk','等待风险权重'),0.0,5.0,.5,key='s3_risk')
            quote=st.number_input(t('Available USDC','可用 USDC'),min_value=0.0,value=5000.0,key='s3_quote')
            base=st.number_input(t('Available ETH','可用 ETH'),min_value=0.0,value=1.0,key='s3_base')
            tick=st.number_input(t('Price increment (USDC)','价格步长（USDC）'),min_value=.00000001,value=.01,format='%.8f',key='s3_tick')
            delay=st.number_input(t('Order delay (ms)','下单延迟（毫秒）'),0,5000,250,key='s3_delay')
            cancel_delay=st.number_input(t('Cancellation confirmation delay (ms)','撤单确认延迟（毫秒）'),0,5000,250,key='s3_cancel')
            age=st.number_input(t('Maximum quote age (ms)','报价最长有效时间（毫秒）'),100,10000,3000,key='s3_age')
            step=st.number_input(t('Quantity increment (ETH)','数量步长（ETH）'),min_value=.00000001,value=.00000001,format='%.8f',key='s3_step')
            st.subheader(t('Your original plan','你的原方案'))
            original_wait=st.selectbox(t('Original waiting time (s)','原方案等待时长（秒）'),waits or [10],key='s3_reference_wait')
            original_offset=st.selectbox(t('Original price offset','原方案价格偏移'),offsets or [0],key='s3_reference_offset')
            amend=st.checkbox(t('Cancel and reprice halfway through','等待中途撤单并重新报价'),key='s3_reference_amend')
            start=st.form_submit_button(t('Compare limit-order plans','比较限价方案'),type='primary')
        if start:
            try:
                st.session_state['limit_task']=submit_task('limit',dict(day=day,utc_time=clock.isoformat(timespec='seconds'),side=side,quantity=qty,waits=waits,offsets=offsets,maker_bps=maker,taker_bps=taker,risk_weight=risk,tick=str(tick),quantity_step=str(step),quote_balance=quote,base_balance=base,latency_ms=delay,cancel_latency_ms=cancel_delay,max_book_age_ms=age,reference_plan=dict(kind='passive_then_taker',wait_seconds=original_wait,offset_ticks=original_offset,amend=amend)))
            except Exception as exc:error_message(exc)
        render_background_task(st.session_state.get('limit_task'))
        saved=sorted(LIMIT_RUN_ROOT.glob('*/report.json'),key=lambda p:p.stat().st_mtime,reverse=True) if LIMIT_RUN_ROOT.exists() else []
        if saved:
            if 's3_activate' in st.session_state:
                activated=st.session_state.pop('s3_activate');st.session_state['s3_history_generation']=activated.parent.name;st.session_state['s3_history_default']=activated
            generation=st.session_state.get('s3_history_generation','initial');preferred=st.session_state.get('s3_history_default')
            def saved_label(path):
                """以日期、时间、方向和数量标记历史实验，隐藏内部运行标识。"""
                report=read(path);config=report['config']
                return f"{config['day']} {config['utc_time']} UTC · {word(config['side'])} · {config['quantity']} ETH · {report['created_at'][11:19]}"
            path=st.selectbox(t('Saved limit-order comparisons','已保存的限价实验'),saved,index=saved.index(preferred) if preferred in saved else 0,format_func=saved_label,key='s3_history_'+generation)
            report=read(path);selected=report['selection']['selected']
            st.subheader(t('Selected plan','选定方案'))
            if selected['kind']=='immediate':st.write(t('Trade immediately.','立即成交。'))
            else:
                st.write(t('Wait at a limit price, then trade any remainder.','限价等待，再主动成交剩余数量。'))
                st.write(t('Waiting time (s)','等待时长（秒）'),selected['wait_seconds'])
                st.write(t('Price offset (increments)','价格偏移（步数）'),selected.get('offset_ticks',0))
                st.write(t('Reprice halfway through','中途改价'),t('Yes','是') if selected.get('amend') else t('No','否'))
            rows=[dict(strategy=t('Selected plan','选定方案'),scenario=name,**{k:v for k,v in r.items() if k!='scenario'}) for name,r in report['results'].items()]
            rows += [dict(strategy=t('Your original plan','原方案'),scenario=name,**{k:v for k,v in r.items() if k!='scenario'}) for name,r in (report.get('reference_results') or {}).items()]
            rows.append(dict(strategy=t('Trade immediately','立即成交'),**report['immediate_baseline']))
            table(rows,FILL_COLUMNS)
            st.caption(t('Compare payment for buys or proceeds for sells, plus completion and waiting time. Queue scenarios represent different amounts of competition ahead.','买入比较支出、卖出比较收入，同时看完成比例和等待时间。排队情景代表前方竞争数量的不同假设。'))
            with st.expander(t('Simulated trades','模拟成交明细')):
                rows=[dict(scenario=name,time=pd.Timestamp(fill['at'],unit='s',tz='UTC').isoformat(),**fill) for name,r in report['results'].items() for fill in r['fills']]
                table(rows,{'scenario': ('Queue scenario','排队情景'),'time': ('Time (UTC)','时间（UTC）'),'quantity': ('ETH','ETH'),'price': ('Price (USDC/ETH)','价格（USDC/ETH）'),'fee': ('Fees (USDC)','手续费（USDC）')})
            download(report,f"limit-plan-{report['run_id']}.json",'s3_download')
            if st.button(t('Repeat this saved comparison','按所选历史参数复跑'),key='s3_rerun'):
                try:
                    st.session_state['limit_task']=submit_task('limit',report['config']);st.rerun()
                except Exception as exc:error_message(exc)

elif page=='历史研究与 ML':
    st.header(t('Compare predictions with actual outcomes','比较预测与实际结果'))
    st.caption(t('Forecast the cost of buying 0.5 ETH in one minute and the next-minute price volatility. Cost is relative to the midpoint at execution time.','预测一分钟后买入 0.5 ETH 的盘口成本，以及未来一分钟价格波动。成本相对成交时买卖中间价计算。'))
    metrics=read(out/'test_metrics.json')
    if metrics:
        for task,values in metrics.items():
            st.subheader(word(task))
            table([dict(model=name,**value) for name,value in values.items()],{'model': ('Prediction method','预测方法'),'mae': ('Average error (bps)','平均误差（bps）'),'baseline_mae': ('Baseline average error (bps)','基线平均误差（bps）'),'rmse': ('Root mean square error (bps)','均方根误差（bps）')})
        pred=pd.read_parquet(out/'test_predictions.parquet').iloc[::10];pred['UTC']=pd.to_datetime(pred.t,unit='s',utc=True)
        task=st.selectbox(t('Chart','图表'),['execution_cost','volatility'],format_func=word,key='historical_forecast')
        chart(pred,'UTC',{task+'_actual': ('Actual','实际结果'),task+'_model': ('Prediction','模型预测'),task+'_baseline': ('Recent-market baseline','近期行情基线')},('Basis points (bps)','基点（bps）'))
        st.caption(t('Closer to the actual curve means lower error. Training: September 1–4; comparison: September 5; evaluation: September 6–7, 2026.','预测越接近实际曲线，误差越小。2026 年 9 月 1—4 日训练，5 日比较模型，6—7 日评估。'))
    else:st.info(t('No prediction results are available yet.','暂无预测结果。'))

elif page=='成交量与订单流':
    st.header(t('How active was trading, and who was more aggressive?','成交有多活跃，买卖哪边更积极？'))
    report=read(home/'trades'/'report.json')
    if report:
        a,b=st.columns(2);a.metric(t('Trades','成交笔数'),f"{report['total_trades']:,}");b.metric(t('Volume (ETH)','成交量（ETH）'),f"{report['total_volume_eth']:,.1f}")
        flow=pd.read_parquet(home/'trades'/'hourly_flow.parquet');flow['UTC']=pd.to_datetime(flow.available_at,unit='s',utc=True)
        chart(flow,'UTC',{'volume_eth': ('Hourly volume','每小时成交量')},('ETH','ETH'),bar=True)
        st.caption(t('Higher bars mean more ETH changed hands during that hour.','柱子越高，该小时成交的 ETH 越多。'))
        chart(flow,'UTC',{'flow_imbalance': ('Buying minus selling pressure','买卖力量差')},('Imbalance','买卖失衡'))
        st.caption(t('Positive values mean more aggressive buying; negative values mean more aggressive selling.','正值表示主动买入更多，负值表示主动卖出更多。'))
    else:st.info(t('No trade history analysis is available yet.','暂无历史成交分析。'))

elif page=='执行回放与风险':
    st.header(t('Historical execution costs','历史执行成本'))
    metrics=read(out/'paper_metrics.json')
    if metrics:
        table([dict(strategy=k,fills=v['fills'],rejections=v['rejections'],cost=v['mean_is_bps'],pnl=v['ledger']['pnl']) for k,v in metrics.items()],{'strategy': ('Plan','方案'),'fills': ('Trades filled','成交次数'),'rejections': ('Orders not filled','未成交次数'),'cost': ('Average cost (bps)','平均成本（bps）'),'pnl': ('Portfolio change (USDC)','资产价值变化（USDC）')})
        orders=pd.read_parquet(out/'paper_orders.parquet');orders['UTC']=pd.to_datetime(orders.decision_t,unit='s',utc=True)
        data=orders[orders.latency_seconds==.25].copy();data['Plan']=data.policy.map(word)
        st.plotly_chart(px.line(data,x='UTC',y='all_in_is_bps',color='Plan',labels={'UTC':t('Time (UTC)','时间（UTC）'),'all_in_is_bps':t('Cost including fees (bps)','含费成本（bps）'),'Plan':t('Plan','方案')}),width='stretch')
        st.caption(t('Lower cost means trading closer to the starting midpoint. Waiting also changes the ETH purchase or sale price.','成本越低，成交越接近开始时的中间价。等待也会改变 ETH 买卖价格。'))
        with st.expander(t('Individual order results','逐笔订单结果')):
            table(orders,{'UTC': ('Time (UTC)','时间（UTC）'),'policy': ('Plan','方案'),'quantity': ('ETH','ETH'),'all_in_is_bps': ('Cost including fees (bps)','含费成本（bps）'),'status': ('Outcome','成交情况')})
    else:st.info(t('No execution results are available yet.','暂无执行结果。'))

elif page=='DeFi 与 LP 历史':
    st.header(t('Providing liquidity versus holding assets','提供流动性与直接持币比较'))
    report=read(home/'dex'/'report.json')
    if report:
        st.caption(t('Uniswap V3 ETH/USDC observations every four hours. Compare a roughly 1,000 USDC liquidity position with holding the same starting assets.','Uniswap V3 ETH/USDC 池每四小时一次的历史观测，比较约 1,000 USDC 的流动性仓位与持有相同初始资产。'))
        path=pd.read_parquet(home/'dex'/'lp_path.parquet');path['UTC']=pd.to_datetime(path.t,unit='s',utc=True)
        chart(path,'UTC',{'lp_value': ('Liquidity position value','流动性仓位价值'),'hodl_value': ('Holding value','直接持币价值')},('Portfolio value (USDC)','资产价值（USDC）'))
        st.caption(t('The gap shows whether providing liquidity outperformed holding the same assets.','两条曲线差距表示提供流动性相对直接持币的表现。'))
        chart(path,'UTC',{'fees_marked_usdc': ('Accumulated fees','累计手续费收入'),'pnl': ('Position profit/loss','仓位盈亏'),'excess_vs_hodl': ('Gain over holding','相对持币多获得的价值')})
        download(report,'pool-analysis.json','pool_download')
    else:st.info(t('No pool analysis is available yet.','暂无池分析。'))

# 统一实验历史与成交导入是操作入口，不包含实时行情、数据质量日志或工程指令。
st.divider()
with st.expander(t('All experiments — history and repeat','全部实验：历史与复跑')):
    tasks=list_tasks()
    kinds={'execution': ('Order simulation','订单模拟'),'cross': ('Exchange comparison','交易所比较'),
           'static': ('Exchange allocation','跨所分配'),'mpc': ('Adaptive execution','动态执行'),
           'limit': ('Limit-order comparison','限价比较'),'passive': ('Limit-order test','限价测试'),
           'training': ('Prediction training','预测训练'),'acceptance': ('New-date evaluation','新日期评估'),
           'review': ('Uploaded trades','上传成交复盘'),'chain_events': ('Pool trades','池逐笔兑换'),'channels': ('Exchange / pool costs','交易所／池成本')}
    if tasks:
        next_task=st.session_state.pop('all_task_next',None)
        if next_task in [v['id'] for v in tasks]:st.session_state['all_task_history']=next_task
        selected=st.selectbox(t('Saved experiment','已保存实验'),[v['id'] for v in tasks],
            format_func=lambda value:next(f"{v['created_at'][:19]} · {t(*kinds[v['kind']])} · {word(v['status'])}" for v in tasks if v['id']==value),key='all_task_history')
        item=get_task(selected)
        if item['status'] in ('queued','running'):
            progress(item)
            if st.button(t('Cancel this experiment','取消此实验'),key='all_cancel'):cancel(selected);st.rerun()
            if st.button(t('Resume background processing','恢复后台处理'),key='all_resume'):
                try:ensure_worker();st.success(t('Background processing is available. Interrupted experiments retain their settings.','后台处理已恢复，中断实验会保留参数。'))
                except Exception as exc:error_message(exc)
        elif item['status'] in ('failed','interrupted'):
            st.error(describe_failure(item['error'],language=='中文'))
        if item['result']:
            if item['kind']=='execution':render_experiment_result(selected,'unified')
            elif item['kind']=='cross':render_cross_venue_job(selected,'unified')
            elif item['kind']=='static':render_static_report(item['result'],'unified')
            elif item['kind']=='mpc':render_mpc_report(item['result'],'unified')
            elif item['kind']=='passive':render_passive_report(item['result'],'unified')
            elif item['kind']=='channels':render_channel_report(item['result'])
            elif item['kind']=='chain_events':render_chain_report(item['result'],'unified')
            elif item['kind']=='review':
                table(item['result']['summary'],{'side': ('Direction','方向'),'trades': ('Trades','成交次数'),'quantity': ('ETH','ETH'),'average_price': ('Average price (USDC/ETH)','成交均价（USDC/ETH）'),'fee_quote': ('Fees (USDC)','手续费（USDC）'),'net_quote_change': ('USDC change','USDC 变化')})
            download(item['result'],f"experiment-{selected}.json",'unified_result')
        st.download_button(t('Save experiment settings','保存实验参数'),json.dumps(dict(kind=item['kind'],config=item['config']),ensure_ascii=False,indent=2).encode('utf-8'),file_name='experiment-settings.json',key='unified_config')
        if item['status'] not in ('queued','running') and item['kind']!='acceptance':
            if st.button(t('Repeat with these settings','使用这些参数复跑'),key='all_retry'):
                try:
                    repeated=retry_task(selected)
                    st.session_state['last_repeated_task']=repeated
                    st.session_state['all_task_next']=repeated
                    st.rerun()
                except Exception as exc:error_message(exc)
    else:st.caption(t('No experiments yet.','暂无实验。'))
    render_background_task(st.session_state.get('last_repeated_task'))

if page=='执行研究工作台':
    with st.expander(t('Review your own trade fills','导入自己的成交记录复盘')):
        st.caption(t('Upload ETH/USDC fills from one exchange. Fees must be expressed in USDC; directions must be buy or sell. The summary measures uploaded cash flows, not account profit.','上传单一交易所的 ETH/USDC 成交记录。手续费使用 USDC，方向填 buy 或 sell。汇总计算上传成交的资金变化，不代表账户盈亏。'))
        uploaded=st.file_uploader(t('Trade file (CSV)','成交文件（CSV）'),type=['csv'],key='review_upload')
        if uploaded:
            try:
                if uploaded.size>2_000_000:raise ValueError('Trade file must not exceed 2 MB')
                frame=pd.read_csv(uploaded)
                with st.form('review_mapping'):
                    venue=st.selectbox(t('Exchange','交易所'),['bybit','okx'],format_func=str.upper,key='review_venue')
                    zone=st.selectbox(t('Time zone for times without a UTC offset','没有时区偏移时使用的时区'),['UTC','Asia/Shanghai'],key='review_zone')
                    mapping={}
                    for key,labels in {'timestamp': ('Trade time column','成交时间列'),'side': ('Buy/sell column','买卖方向列'),'quantity': ('ETH quantity column','ETH 数量列'),'price': ('USDC/ETH price column','USDC/ETH 价格列'),'fee': ('USDC fee column','USDC 手续费列')}.items():
                        mapping[key]=st.selectbox(t(*labels),list(frame.columns),index=list(frame.columns).index(key) if key in frame.columns else 0,key='review_map_'+key)
                    identifier=st.selectbox(t('Trade ID column (optional)','成交标识列（可选）'),[None]+list(frame.columns),format_func=lambda value:t('Use row number','使用行号') if value is None else value,key='review_map_id')
                    if identifier:mapping['id']=identifier
                    run_review=st.form_submit_button(t('Review trades','复盘成交'),type='primary')
                if run_review:
                    from core.order_review import normalize_fills
                    records=normalize_fills(frame,mapping,zone,venue)
                    st.session_state['review_task']=submit_task('review',dict(records=records))
            except Exception as exc:error_message(exc)
        render_background_task(st.session_state.get('review_task'))
        if st.session_state.get('review_task'):
            review=get_task(st.session_state['review_task'])
            if review and review['result']:
                table(review['result']['summary'],{'side': ('Direction','方向'),'quantity': ('ETH','ETH'),'average_price': ('Average price (USDC/ETH)','成交均价（USDC/ETH）'),'fee_quote': ('Fees (USDC)','手续费（USDC）'),'net_quote_change': ('USDC change','USDC 变化')})

if page=='跨所数据与套利':
    with st.expander(t('Compare an exchange trade with Uniswap','比较交易所与 Uniswap 单笔成本')):
        with st.form('channel_cost_form'):
            chain_day=st.date_input(t('Date (UTC)','日期（UTC）'),date(2026,10,1),max_value=date.today()-timedelta(days=1),key='channel_day')
            chain_clock=st.time_input(t('Trade time (UTC)','成交时间（UTC）'),day_time(12),key='channel_time')
            chain_side=st.selectbox(t('Direction','方向'),['buy','sell'],format_func=word,key='channel_side')
            chain_qty=st.number_input(t('ETH / WETH quantity','ETH／WETH 数量'),min_value=.000001,value=.3,key='channel_qty')
            bfee=st.number_input(t('Bybit fee (bps)','Bybit 手续费（bps）'),0.,100.,10.,key='channel_bfee')
            ofee=st.number_input(t('OKX fee (bps)','OKX 手续费（bps）'),0.,100.,10.,key='channel_ofee')
            gas=st.number_input(t('Total swap gas units','兑换总 Gas 用量'),21000,1000000,200000,10000,key='channel_gas')
            tip=st.number_input(t('Priority fee (gwei)','优先费（gwei）'),0.,100.,1.,key='channel_tip')
            delay=st.number_input(t('Block availability delay (s)','区块可知延迟（秒）'),1,300,12,key='channel_delay')
            chain_age=st.number_input(t('Maximum chain-state age (s)','链上状态最长有效时间（秒）'),12,600,60,key='channel_age')
            accepted=st.checkbox(t('I accept WETH settlement on Uniswap','接受 Uniswap 使用 WETH 结算'),key='channel_weth')
            start=st.form_submit_button(t('Compare total costs','比较总成本'),type='primary')
        if start:
            try:st.session_state['channel_task']=submit_task('channels',dict(day=chain_day.isoformat(),utc_time=chain_clock.isoformat(timespec='seconds'),side=chain_side,quantity=chain_qty,fees_bps={'bybit':bfee,'okx':ofee},gas_units=gas,priority_fee_gwei=tip,block_delay_seconds=delay,max_chain_age_seconds=chain_age,weth_accepted=accepted))
            except Exception as exc:error_message(exc)
        render_background_task(st.session_state.get('channel_task'),renderer=render_channel_report)

if page=='DeFi 与 LP 历史':
    with st.expander(t('Download individual pool trades','下载池逐笔兑换')):
        st.caption(t('Choose up to one hour of ETH/USDC pool activity. Download swaps and liquidity changes in their recorded order.','选择最多一小时的 ETH/USDC 池活动，按记录顺序下载兑换及流动性变化。'))
        with st.form('pool_events_form'):
            event_day=st.date_input(t('Date (UTC)','日期（UTC）'),date(2026,10,1),max_value=date.today()-timedelta(days=1),key='event_day')
            event_clock=st.time_input(t('Start time (UTC)','开始时间（UTC）'),day_time(12),key='event_time')
            minutes=st.number_input(t('Window (minutes)','窗口长度（分钟）'),1,60,10,key='event_minutes')
            start=st.form_submit_button(t('Download pool activity','下载池活动'),type='primary')
        if start:
            beginning=datetime.combine(event_day,event_clock,tzinfo=timezone.utc)
            try:st.session_state['event_task']=submit_task('chain_events',dict(start_utc=beginning.isoformat(),end_utc=(beginning+timedelta(minutes=minutes)).isoformat()))
            except Exception as exc:error_message(exc)
        render_background_task(st.session_state.get('event_task'),renderer=render_chain_report)
