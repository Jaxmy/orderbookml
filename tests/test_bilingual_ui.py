"""双语看板验收：页面只显示业务内容，切换语言后订单参数保持可用。"""
import json
import re
from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest
from core.io import ROOT

PAGES=['执行研究工作台','跨所数据与套利','优化求解与限价情景','历史研究与 ML','成交量与订单流','执行回放与风险','DeFi 与 LP 历史']


def assert_business_ui(app, language):
    """检查所有可见业务文字和图表，防止工程报告、代码和错误重新进入看板。"""
    assert not app.exception
    assert not app.get('json') and not app.get('code')
    texts=[item.value for kind in ['title','header','subheader','caption','markdown','info','warning','success','error'] for item in app.get(kind)]
    for text in texts:
        assert 'SHA-256' not in text and 'D:\\' not in text and 'not_implemented' not in text
        if language=='English':
            assert not re.search('[\u4e00-\u9fff]',text),text
    for frame in app.dataframe:
        if language=='English':
            assert not re.search('[\u4e00-\u9fff]',str(frame.value.columns)+frame.value.to_string()),frame.value
    for plot in app.get('plotly_chart'):
        spec=json.loads(plot.proto.spec)
        if language=='English':
            for trace in spec['data']:
                assert not re.search('[\u4e00-\u9fff]',trace.get('name',''))
            for axis in ['xaxis','yaxis']:
                assert not re.search('[\u4e00-\u9fff]',str(spec['layout'].get(axis,{}).get('title',{})))


@pytest.mark.parametrize('language',['English','中文'])
def test_bilingual_pages_and_analysis_choices(language,monkeypatch,tmp_path):
    """逐页检查中英文渲染，并确认删除的模块不在导航且四个订单分析入口均正常。"""
    from tests.ui_queue import use_inline_queue
    use_inline_queue(monkeypatch,tmp_path)
    app=AppTest.from_file(str(ROOT/'market_app.py')).run(timeout=30)
    assert app.selectbox(key='ui_language').value=='English'
    app.selectbox(key='ui_language').set_value(language).run(timeout=30)
    assert len(app.sidebar.radio[0].options)==7
    for page in PAGES:
        app.sidebar.radio[0].set_value(page).run(timeout=30)
        assert_business_ui(app,language)
    app.sidebar.radio[0].set_value('优化求解与限价情景').run(timeout=30)
    for choice in ['静态多场所路由','滚动执行（MPC）','被动限价队列情景','限价方案优化（S3）']:
        app.radio(key='optimizer_component').set_value(choice).run(timeout=30)
        assert_business_ui(app,language)


def test_language_switch_keeps_order_values_and_executes_static_and_mpc(monkeypatch,tmp_path):
    """切换语言保留已提交的参数，并通过真实缓存验证静态、动态和限价模拟仍能运行。"""
    from tests.ui_queue import use_inline_queue
    use_inline_queue(monkeypatch,tmp_path)
    app=AppTest.from_file(str(ROOT/'market_app.py')).run(timeout=30)
    app.sidebar.radio[0].set_value('优化求解与限价情景').run(timeout=30)
    app.number_input(key='static_amount_base_quantity').set_value(.3)
    next(b for b in app.button if b.label=='Find allocation').click().run(timeout=40)
    assert not app.error
    assert_business_ui(app,'English')
    assert app.metric[0].value=='0.30000000'
    app.selectbox(key='ui_language').set_value('中文').run(timeout=30)
    assert app.number_input(key='static_amount_base_quantity').value==.3
    assert app.metric[0].value=='0.30000000'
    assert_business_ui(app,'中文')
    app.radio(key='optimizer_component').set_value('滚动执行（MPC）').run(timeout=30)
    next(b for b in app.button if b.label=='比较执行方案').click().run(timeout=40)
    assert not app.error
    assert_business_ui(app,'中文')
    assert len(app.dataframe[-2].value)==3
    app.selectbox(key='ui_language').set_value('English').run(timeout=30)
    assert len(app.dataframe[-2].value)==3
    assert_business_ui(app,'English')
    app.selectbox(key='ui_language').set_value('中文').run(timeout=30)
    app.radio(key='optimizer_component').set_value('被动限价队列情景').run(timeout=30)
    next(b for b in app.button if b.label=='测试限价单').click().run(timeout=40)
    assert not app.error
    assert_business_ui(app,'中文')
    assert len(app.dataframe[0].value)==3
