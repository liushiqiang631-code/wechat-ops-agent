from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.container import build_container
from app.main import create_app


def test_console_splits_workbench_tasks_and_data_across_pages(tmp_path: Path):
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'ui.db'}",
        object_storage_path=tmp_path / "outputs",
    )
    client = TestClient(create_app(settings, build_container(settings)))

    workbench = client.get("/")
    tasks = client.get("/tasks")
    data = client.get("/data")
    css = client.get("/static/app.css")

    for page in (workbench, tasks, data):
        assert page.status_code == 200
        assert "示例技术观察站" in page.text
        assert 'class="app-shell"' in page.text
        assert 'id="task-drawer"' in page.text
        assert 'id="import-drawer"' in page.text
        assert 'id="preview-dialog"' in page.text
        assert 'id="toast-region"' in page.text
        assert 'rel="icon" href="data:image/svg+xml,' in page.text
        assert "正式发布由人工完成" in page.text
        assert "api_key" not in page.text.lower()

    # 工作台：欢迎面板 + 当前流水线 + 最近任务，不含完整指标区
    assert 'class="welcome-panel"' in workbench.text
    assert 'aria-label="内容任务进度"' in workbench.text
    assert "创建内容任务" in workbench.text
    assert 'data-open-drawer="task-drawer"' in workbench.text
    assert 'aria-label="近 30 天运营指标"' not in workbench.text

    # 内容任务：独立任务列表页
    assert 'class="task-list"' in tasks.text
    assert 'aria-label="内容任务进度"' not in tasks.text
    assert 'href="/tasks"' in tasks.text
    assert 'href="/data"' in tasks.text

    # 数据复盘：指标卡 + 数据质量 + 窗口表
    assert 'aria-label="近 30 天运营指标"' in data.text
    assert "数据质量" in data.text
    assert "7 / 30 / 90 天窗口" in data.text
    assert "尚未导入数据" in data.text
    assert "18,642" not in data.text

    assert css.status_code == 200
    assert "--wechat-green:" in css.text
    assert "--aurora-violet: #5b54e7;" in css.text
    assert "--mint: #51c9ab;" in css.text
    assert ".aurora-track" in css.text
    assert ".workbench-grid" in css.text
    assert ".review-grid" in css.text
    assert ".windows-table" in css.text
    assert '.drawer[aria-hidden="false"]' in css.text
    assert "@media (max-width: 767px)" in css.text
    assert ":focus-visible" in css.text
    assert "prefers-reduced-motion" in css.text
