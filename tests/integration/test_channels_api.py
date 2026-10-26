from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.container import build_container
from app.main import create_app


def build_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'channels.db'}",
        object_storage_path=tmp_path / "outputs",
    )
    return TestClient(create_app(settings, build_container(settings)))


def test_seed_creates_five_channels_with_realistic_distribution(tmp_path: Path):
    container = build_container(
        Settings(
            _env_file=None,
            database_url=f"sqlite:///{tmp_path / 'seed.db'}",
            object_storage_path=tmp_path / "outputs",
            seed_demo_data=True,
        )
    )

    accounts = {account.key.value: account for account in container.channels.list_accounts()}
    assert set(accounts) == {"xiaohongshu", "shipinhao", "douyin", "kuaishou", "wechat"}
    assert all(account.followers > 0 for account in accounts.values())

    posts = container.channels.list_posts(limit=500)
    assert len(posts) >= 100
    channels = {post.channel.value for post in posts}
    assert channels == set(accounts)
    # 失败记录必须带原因；已发布记录带发布时间
    failed = [post for post in posts if post.status.value == "failed"]
    assert failed and all(post.last_error for post in failed)
    published = [post for post in posts if post.status.value == "published"]
    assert published and all(post.published_at for post in published)
    # 种子是确定性的：同参数重建得到一致的数量
    assert len(container.scripts.list()) == 2


def test_channel_posts_crud_and_status_flow(tmp_path: Path):
    client = build_client(tmp_path)

    created = client.post(
        "/api/v1/channel-posts",
        json={
            "channel": "douyin",
            "content_type": "短视频",
            "title": "MCP 协议 3 分钟入门",
            "excerpt": "一条视频讲清 MCP",
            "category": "实战教程",
            "status": "draft",
        },
    )
    assert created.status_code == 201
    post_id = created.json()["id"]

    publish_before_review = client.post(f"/api/v1/channel-posts/{post_id}/retry")
    assert publish_before_review.status_code == 409

    published = client.post(f"/api/v1/channel-posts/{post_id}/publish")
    assert published.status_code == 200
    assert published.json()["status"] == "published"
    assert published.json()["published_at"]

    metrics = client.post(
        f"/api/v1/channel-posts/{post_id}/metrics",
        json={"views": 12000, "likes": 800, "comments": 90, "shares": 60, "favorites": 30},
    )
    assert metrics.status_code == 200
    assert metrics.json()["views"] == 12000

    listed = client.get("/api/v1/channel-posts", params={"channel": "douyin", "q": "MCP"})
    assert listed.status_code == 200
    assert any(item["id"] == post_id for item in listed.json())

    deleted = client.delete(f"/api/v1/channel-posts/{post_id}")
    assert deleted.status_code == 204
    assert client.post(f"/api/v1/channel-posts/{post_id}/publish").status_code == 404


def test_channel_post_status_filter_and_export(tmp_path: Path):
    client = build_client(tmp_path)
    client.post(
        "/api/v1/channel-posts",
        json={
            "channel": "xiaohongshu",
            "content_type": "图文笔记",
            "title": "AI 工具合集",
            "status": "pending_review",
        },
    )
    page = client.get("/api/v1/channel-posts", params={"status_filter": "pending_review"})
    assert page.status_code == 200
    assert page.json() and all(item["status"] == "pending_review" for item in page.json())

    report = client.get("/api/v1/channels/report.csv", params={"days": 7})
    assert report.status_code == 200
    assert "标题" in report.text
    assert "AI 工具合集" in report.text


def test_manual_script_and_conversion_to_article(tmp_path: Path):
    client = build_client(tmp_path)

    created = client.post(
        "/api/v1/scripts",
        json={
            "title": "3 个提升编码效率的 AI 实用技巧",
            "topic": "AI 编码效率",
            "channel": "shipinhao",
            "duration_seconds": 60,
            "audience": "开发者",
            "hook": "每天写代码，这三招帮你省一小时。",
            "beats": [
                {
                    "time_range": "00:00-00:30",
                    "shot": "屏幕录制",
                    "voiceover": "第一招，把样板代码交给 AI。",
                }
            ],
            "ending": "关注我，每周三个技巧。",
            "hashtags": ["AI编程"],
        },
    )
    assert created.status_code == 201
    assert created.json()["source"] == "manual"
    script_id = created.json()["id"]

    converted = client.post(f"/api/v1/scripts/{script_id}/to-article")
    assert converted.status_code == 201
    task_id = converted.json()["task_id"]
    assert converted.json()["script"]["status"] == "converted"

    # 转写后任务入库且是流水线任务；脚本不能再转一次
    task = client.get(f"/api/v1/tasks/{task_id}")
    assert task.status_code == 200
    assert "视频脚本" in task.json()["request"]
    assert client.post(f"/api/v1/scripts/{script_id}/to-article").status_code == 409

    to_post = client.post(
        f"/api/v1/scripts/{script_id}/to-post",
        json={"channel": "douyin", "status": "draft"},
    )
    assert to_post.status_code == 201
    assert to_post.json()["channel"] == "douyin"
    assert to_post.json()["script_id"] == script_id


def test_script_generation_requires_configured_model(tmp_path: Path):
    client = build_client(tmp_path)

    response = client.post(
        "/api/v1/scripts/generate",
        json={"topic": "结构化输出实战", "channel": "douyin", "duration_seconds": 60},
    )
    assert response.status_code == 409
    assert "DEEPSEEK_API_KEY" in response.json()["detail"]


def test_activity_log_records_real_operations(tmp_path: Path):
    client = build_client(tmp_path)
    client.post(
        "/api/v1/channel-posts",
        json={
            "channel": "kuaishou",
            "content_type": "短视频",
            "title": "零基础学 AI 编程",
            "status": "draft",
        },
    )

    logs = client.get("/api/v1/activity").json()
    assert logs and any(item["kind"] == "post_create" for item in logs)


def test_channel_pages_stay_empty_without_seeded_data(tmp_path: Path):
    """默认不种示例数据：渠道页与发布中心显示占位空态，而不是虚构数字。"""
    client = build_client(tmp_path)

    home = client.get("/")
    assert home.status_code == 200
    assert "暂无匹配的发布记录" in home.text
    # 四个状态计数真实为 0，不编造数字
    assert "暂无数据" in home.text

    for key, label in (
        ("xiaohongshu", "小红书"),
        ("douyin", "抖音"),
        ("kuaishou", "快手"),
        ("shipinhao", "视频号"),
    ):
        page = client.get(f"/channels/{key}")
        assert page.status_code == 200
        assert label in page.text
        # 未接入的渠道：占位符而不是粉丝数/浏览量
        assert "未接入" in page.text
        assert "暂无发布记录" in page.text

    channels_page = client.get("/channels")
    assert channels_page.status_code == 200
    assert channels_page.text.count("未接入") >= 5
    assert "2.8万" not in channels_page.text

    compare = client.get("/compare")
    assert compare.status_code == 200
    assert "—" in compare.text


def test_channel_page_renders_account_when_connected(tmp_path: Path):
    """接入（或登记）账号信息后，渠道页展示账号与统计而不是占位符。"""
    client = build_client(tmp_path)
    client.post(
        "/api/v1/channel-posts",
        json={
            "channel": "douyin",
            "content_type": "短视频",
            "title": "接入后的第一条内容",
            "status": "published",
        },
    )
    client.patch(
        "/api/v1/channels/douyin",
        json={"display_name": "Agent应用笔记", "handle": "Agent应用笔记", "followers": 1000},
    )

    page = client.get("/channels/douyin")
    assert page.status_code == 200
    assert "Agent应用笔记" in page.text
    assert "运营中" in page.text
    assert "1,000" in page.text
