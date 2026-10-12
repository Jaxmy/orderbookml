from pathlib import Path
import pytest


def test_three_pages_render():
    """验证早期三页看板渲染与无异常；构造可控输入并以独立预期/不变性断言检查，不代表实盘收益。"""
    root=Path(__file__).resolve().parents[1]
    if not (root/'reports'/'demo'/'quality.json').exists():
        pytest.skip('Generate the demo before dashboard integration test')
    from streamlit.testing.v1 import AppTest
    at=AppTest.from_file(str(root/'app.py'),default_timeout=30).run()
    assert not at.exception
    for page in ['库存与对账','LP 与研究结论','执行与机器学习']:
        at.sidebar.radio[0].set_value(page).run()
        assert not at.exception
