from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.container import build_container
from app.main import create_app


def build_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'ui.db'}",
        object_storage_path=tmp_path / "outputs",
    )
    return TestClient(create_app(settings, build_container(settings)))


def test_all_console_pages_share_shell_and_boundaries(tmp_path: Path):
    client = build_client(tmp_path)

    pages = {
        path: client.get(path)
        for path in (
            "/",
            "/topics",
            "/tasks",
            "/media",
            "/drafts",
            "/schedule",
            "/data",
            "/fans",
            "/calendar",
            "/workflow",
            "/settings",
        )
    }
    css = client.get("/static/app.css")

    for path, page in pages.items():
        assert page.status_code == 200, path
        assert "示例技术观察站" in page.text, path
        assert 'class="app-shell"' in page.text, path
        assert 'class="side-nav"' in page.text, path
        assert 'id="task-drawer"' in page.text, path
        assert 'id="import-drawer"' in page.text, path
        assert 'id="preview-dialog"' in page.text, path
        assert 'id="toast-region"' in page.text, path
        assert 'rel="icon" href="data:image/svg+xml,' in page.text, path
        assert "正式发布由人工完成" in page.text, path
        assert "api_key" not in page.text.lower(), path
        # 绝不能出现密钥形态的值
        assert re.search(r"sk-[A-Za-z0-9]{8,}", page.text) is None, path

    assert css.status_code == 200
    assert "--wechat-green: #07c160;" in css.text
    assert ".kpi-grid" in css.text
    assert ".workbench" in css.text
    assert ".bottom-grid" in css.text
    assert ".review-grid" in css.text
    assert ".windows-table" in css.text
    assert '.drawer[aria-hidden="false"]' in css.text
    assert "@media (max-width: 767px)" in css.text
    assert ":focus-visible" in css.text
    assert "prefers-reduced-motion" in css.text


def test_overview_page_matches_console_layout(tmp_path: Path):
    client = build_client(tmp_path)
    page = client.get("/")

    assert page.status_code == 200
    # 顶栏与侧边栏（按设计稿）
    assert "微信公众号运营助手 AGENT" in page.text
    assert "让优质内容持续发生" in page.text
    assert "搜索文章、选题、粉丝或功能" in page.text
    assert "AGENT 正在为你工作" in page.text
    # 四张 KPI 卡 + Agent 执行卡
    assert 'aria-label="今日运营指标"' in page.text
    assert "今日生成文章" in page.text
    assert "草稿箱保存" in page.text
    assert "配图完成率" in page.text
    assert "粉丝增长" in page.text
    # 主工作区四栏
    assert "AI 文章生成" in page.text
    assert "文章预览与编辑" in page.text
    assert "配图生成" in page.text
    assert "Agent 工作流" in page.text
    # 底部三栏
    assert "运营日历" in page.text
    assert "数据分析" in page.text
    assert "粉丝运营" in page.text
    # 工作流节点：定时提醒明确群发由人工完成
    assert "正式群发由人工完成" in page.text
    # 空数据不留假数字
    assert "12,560" not in page.text
    assert "+328" not in page.text


def test_data_page_keeps_empty_state_without_fabricated_numbers(tmp_path: Path):
    client = build_client(tmp_path)
    page = client.get("/data")

    assert page.status_code == 200
    assert 'aria-label="近 30 天运营指标"' in page.text
    assert "数据质量" in page.text
    assert "7 / 30 / 90 天窗口" in page.text
    assert "尚未导入数据" in page.text
    assert "18,642" not in page.text


def test_schedule_page_states_group_send_boundary(tmp_path: Path):
    client = build_client(tmp_path)
    page = client.get("/schedule")

    assert page.status_code == 200
    assert "系统边界" in page.text
    assert "不提供公众号正式发布或群发接口" in page.text
    assert "等待人工发布的文章" in page.text


def test_settings_page_shows_states_but_never_secrets(tmp_path: Path):
    client = build_client(tmp_path)
    page = client.get("/settings")

    assert page.status_code == 200
    assert "写作模型" in page.text
    assert "草稿上传" in page.text
    assert "不提供接口，由人工在微信后台完成" in page.text
    assert "自动文章修订最多两轮" in page.text
    assert "api_key" not in page.text.lower()
