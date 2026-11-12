"""Streamlit AppTest 界面验收测试：应用启动 + 七个页面导航渲染。

完整的「上传 → 提取 → 匹配 → 审核 → 下载」交互由服务层测试（pipeline/review/report）
与人工验收步骤覆盖，此处覆盖界面层：启动无异常、七个页面均可渲染、历史页可读取已入库任务。
"""
from pathlib import Path

import pytest

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"

PAGES = [
    "首页：业务总览", "文档管理", "AI 信息提取", "三单匹配", "人工审核",
    "历史记录与报告", "系统状态与配置",
]


@pytest.mark.skipif(not APP_PATH.exists(), reason="app.py 不存在")
def test_app_runs_without_exception():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    assert not at.exception, f"应用抛出异常：{[e.value for e in at.exception]}"


@pytest.mark.skipif(not APP_PATH.exists(), reason="app.py 不存在")
@pytest.mark.parametrize("page", PAGES)
def test_app_pages_render_without_exception(page):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    at.sidebar.radio[0].set_value(page).run()
    assert not at.exception, f"页面「{page}」抛出异常：{[e.value for e in at.exception]}"


@pytest.mark.skipif(not APP_PATH.exists(), reason="app.py 不存在")
def test_app_history_page_reads_seeded_task(tmp_path, monkeypatch, no_ocr):
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    from invoice_matching.config import settings
    from invoice_matching.db import Database

    # 将应用数据库重定向到临时目录，避免污染真实 data/；并清空跨用例的缓存资源
    monkeypatch.setattr(settings, "db_path", tmp_path / "app.db")
    db = Database(tmp_path / "app.db")
    db.create_task("审计演示任务")
    db.close()
    st.cache_resource.clear()

    at = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    at.sidebar.radio[0].set_value("历史记录与报告").run()
    assert not at.exception
    # 历史页下拉框应列出已入库任务
    options = [o for s in at.selectbox for o in s.options]
    assert any("审计演示任务" in o for o in options)
