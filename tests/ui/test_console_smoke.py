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


def test_media_supports_legacy_local_and_timezone_aware_asset_times(tmp_path: Path):
    from datetime import UTC, datetime

    from app.domain.enums import TaskMode
    from app.domain.models import AssetManifest, AssetRecord, TaskRecord
    from app.web.view_models import cover_gallery

    settings = Settings(
        _env_file=None, database_url=f"sqlite:///{tmp_path / 'mixed-media.db'}",
        object_storage_path=tmp_path / "outputs", business_timezone="Asia/Shanghai",
    )
    container = build_container(settings)
    for asset_id, source, created_at in [
        ("product", "knowledge_base", datetime(2026, 10, 20, 10)),
        ("ai", "ai_generated", datetime(2026, 10, 20, 3, tzinfo=UTC)),
        ("web", "web_search", datetime.fromisoformat("2026-10-20T09:30:00+08:00")),
    ]:
        task = container.tasks.create(TaskRecord(mode=TaskMode.FIXED_TOPIC, request="配图素材"))
        manifest = AssetManifest(task_id=task.id, items=[AssetRecord(
            asset_id=asset_id, kind="concept", source=source, caption=asset_id,
            created_at=created_at,
        )])
        container.artifacts.write_json(task.id, "assets", manifest.model_dump(mode="json"))
    client = TestClient(create_app(settings, container), raise_server_exceptions=False)
    page = client.get("/media")
    assert page.status_code == 200
    assets = cover_gallery(container)["recent_assets"]
    assert [item["asset_id"] for item in assets] == ["ai", "product", "web"]
    assert [item["created_label"] for item in assets] == [
        "10-20 11:00", "10-20 10:00", "10-20 09:30",
    ]
    assert all(item["created_iso"].endswith("+08:00") for item in assets)


def test_all_console_pages_share_shell_and_boundaries(tmp_path: Path):
    client = build_client(tmp_path)

    pages = {
        path: client.get(path)
        for path in (
            "/",
            "/overview",
            "/topics",
            "/tasks",
            "/media",
            "/drafts",
            "/schedule",
            "/scripts",
            "/channels",
            "/channels/xiaohongshu",
            "/channels/wechat",
            "/data",
            "/performance",
            "/fans",
            "/compare",
            "/team",
            "/approvals",
            "/logs",
            "/calendar",
            "/workflow",
            "/settings",
        )
    }
    css = client.get("/static/app.css")

    for path, page in pages.items():
        assert page.status_code == 200, path
        assert 'class="app-shell"' in page.text, path
        assert 'class="side-nav"' in page.text, path
        assert 'id="task-drawer"' in page.text, path
        assert 'id="post-drawer"' in page.text, path
        assert 'id="import-drawer"' in page.text, path
        assert 'id="preview-dialog"' in page.text, path
        assert 'id="toast-region"' in page.text, path
        assert "全域内容运营平台" in page.text, path
        assert "正式发布由人工完成" in page.text, path
        assert "api_key" not in page.text.lower(), path
        # 绝不能出现密钥形态的值
        assert re.search(r"sk-[A-Za-z0-9]{8,}", page.text) is None, path

    unknown = client.get("/channels/unknown")
    assert unknown.status_code == 404

    assert css.status_code == 200
    assert "--wechat-green: #07c160;" in css.text
    assert ".publish-layout" in css.text
    assert ".timeline-day" in css.text
    assert ".overview-donut" in css.text
    assert ".kpi-grid" in css.text
    assert ".workbench" in css.text
    assert ".bottom-grid" in css.text
    assert ".review-grid" in css.text
    assert ".windows-table" in css.text
    assert '.drawer[aria-hidden="false"]' in css.text
    assert "@media (max-width: 767px)" in css.text
    assert ":focus-visible" in css.text
    assert "prefers-reduced-motion" in css.text


def test_publish_center_matches_design_layout(tmp_path: Path):
    client = build_client(tmp_path)
    page = client.get("/")

    assert page.status_code == 200
    # 侧边栏与顶栏（按设计稿）
    assert "全域内容运营平台" in page.text
    assert "让内容产生更大价值" in page.text
    assert "搜索内容、素材、话题或发布记录" in page.text
    # 页头与三大动作
    assert "内容发布中心" in page.text
    assert "导入素材" in page.text
    assert "导出报表" in page.text
    assert "创建发布" in page.text
    # 发布数据概览：四类状态 + 成功率
    assert "发布数据概览" in page.text
    assert "已发布" in page.text
    assert "待审核" in page.text
    assert "草稿" in page.text
    assert "发布失败" in page.text
    assert "发布成功率" in page.text
    # 发布记录时间线 + 右栏三卡片
    assert "发布记录" in page.text
    assert "待处理事项" in page.text
    assert "本周发布计划" in page.text
    assert "各平台数据表现" in page.text
    # 五个渠道都在侧边栏
    for label in ("小红书", "视频号", "抖音", "快手", "公众号"):
        assert label in page.text


def test_publish_center_stays_empty_without_demo_data(tmp_path: Path):
    """默认不生成示例数据：发布中心显示真实空态，渠道数据留占位。"""
    client = build_client(tmp_path)
    page = client.get("/")

    assert page.status_code == 200
    assert "暂无匹配的发布记录" in page.text
    assert "暂无数据" in page.text
    # 待处理事项仍来自真实流水线任务（本库没有任务时为空态提示）
    assert "当前没有待处理事项" in page.text or "待处理事项" in page.text
    assert "timeline-day" not in page.text


def test_publish_center_renders_seeded_demo_data_when_enabled(tmp_path: Path):
    """显式开启 SEED_DEMO_DATA 后，示例数据通过同一条真实计算路径呈现。"""
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'seeded.db'}",
        object_storage_path=tmp_path / "outputs",
        seed_demo_data=True,
    )
    client = TestClient(create_app(settings, build_container(settings)))
    page = client.get("/")

    assert page.status_code == 200
    for label in ("小红书", "视频号", "抖音", "快手", "公众号"):
        assert label in page.text
    assert "timeline-day" in page.text
    assert 'class="stat-value"' in page.text


def test_generated_articles_card_omits_day_over_day_change(tmp_path: Path):
    from datetime import UTC, datetime, timedelta

    from app.domain.enums import TaskMode
    from app.domain.models import TaskRecord

    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'kpi.db'}",
        object_storage_path=tmp_path / "outputs",
    )
    container = build_container(settings)
    container.tasks.create(
        TaskRecord(
            mode=TaskMode.FIXED_TOPIC,
            request="昨天创建的文章任务",
            created_at=datetime.now(UTC) - timedelta(days=1),
        )
    )
    client = TestClient(create_app(settings, container))

    page = client.get("/overview")

    assert page.status_code == 200
    generated_card = re.search(
        r'<article class="card kpi-card is-generated">(?P<card>.*?)</article>',
        page.text,
        re.DOTALL,
    )
    assert generated_card is not None
    assert "较昨日" not in generated_card.group("card")
    assert "-100.0%" not in generated_card.group("card")


def test_data_page_keeps_empty_state_without_fabricated_numbers(tmp_path: Path):
    client = build_client(tmp_path)
    page = client.get("/data")

    assert page.status_code == 200
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


def test_settings_page_shows_states_but_never_secrets(tmp_path: Path):
    client = build_client(tmp_path)
    page = client.get("/settings")

    assert page.status_code == 200
    assert "写作模型" in page.text
    assert "草稿上传" in page.text
    assert "自动文章修订最多两轮" in page.text
    assert "api_key" not in page.text.lower()
