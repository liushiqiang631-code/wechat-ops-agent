from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.container import build_container
from app.domain.enums import TaskMode, TaskStatus
from app.domain.models import (
    ArticleDocument,
    ArticleSection,
    RepurposedContent,
    TaskSpec,
    TitleProposal,
)
from app.main import create_app


def advance(container, task_id: str, *statuses: TaskStatus) -> None:
    for status in statuses:
        container.tasks.transition(task_id, status)


def _article_payload() -> dict:
    return ArticleDocument(
        titles=["LangGraph 检查点"],
        selected_title="LangGraph 检查点",
        digest="失败恢复设计。",
        audience="AI 应用开发者",
        sections=[
            ArticleSection(type="paragraph", content="先看进程中断。"),
            ArticleSection(type="paragraph", content="检查点保存可恢复状态。"),
        ],
        references=["https://docs.langchain.com/oss/python/langgraph/persistence"],
        ending="把失败恢复设计成正常路径。",
    ).model_dump(mode="json")


def _html_payload() -> dict:
    return {"html": "<section><h1>LangGraph 检查点</h1><p>先看进程中断。</p></section>"}


def build_client(tmp_path: Path) -> tuple[TestClient, object]:
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite:///{tmp_path / 'features.db'}",
        object_storage_path=tmp_path / "outputs",
        business_timezone="Asia/Shanghai",
    )
    container = build_container(settings)

    async def fake_titles(topic, request):
        return TitleProposal(
            topic=topic,
            candidates=[
                {"title": "LangGraph 检查点：把失败变成可恢复状态", "rationale": "工程视角"},
                {"title": "如何构建可恢复的 Agent 流水线", "rationale": "实操导向"},
                {"title": "Agent 工程中的恢复机制", "rationale": "概念清晰"},
            ],
        )

    async def fake_repurpose(task_id, article):
        return RepurposedContent(
            task_id=task_id,
            video_script="开场钩子：进程断了怎么办。",
            xiaohongshu_post="标题：检查点为什么重要\n三点总结。",
            moments_blurb="把失败变成可恢复状态。",
        )

    container.titles.run = fake_titles  # type: ignore[method-assign]
    container.repurpose.run = fake_repurpose  # type: ignore[method-assign]
    return TestClient(create_app(settings, container)), container


def test_title_proposal_choose_and_review_flow(tmp_path: Path):
    client, container = build_client(tmp_path)

    created = client.post(
        "/api/v1/tasks",
        json={"mode": "fixed_topic", "request": "写 LangGraph 检查点", "topic": "LangGraph 检查点"},
    )
    task = created.json()
    assert task["status"] == "CREATED"
    assert container.topic_records.get(task["id"]).topic == "LangGraph 检查点"

    proposed = client.post(f"/api/v1/tasks/{task['id']}/propose-titles")
    assert proposed.status_code == 200
    assert len(proposed.json()["candidates"]) == 3

    chosen = client.post(
        f"/api/v1/tasks/{task['id']}/choose-title",
        json={"title": "LangGraph 检查点：把失败变成可恢复状态"},
    )
    assert chosen.status_code == 200
    assert chosen.json()["title_hint"] == "LangGraph 检查点：把失败变成可恢复状态"

    # Produce article + html artifacts so review page and repurpose work.
    container.artifacts.write_json(task["id"], "article", _article_payload())
    container.artifacts.write_json(task["id"], "wechat_html", _html_payload())
    advance(
        container,
        task["id"],
        TaskStatus.PLANNED,
        TaskStatus.RESEARCHED,
        TaskStatus.WRITTEN,
        TaskStatus.ASSETS_READY,
        TaskStatus.REVIEWED,
        TaskStatus.FORMATTED,
    )

    markdown = client.get(f"/api/v1/articles/{task['id']}/draft-markdown")
    assert markdown.status_code == 200
    assert "# LangGraph 检查点" in markdown.json()["markdown"]

    repurposed = client.post(f"/api/v1/articles/{task['id']}/repurpose")
    assert repurposed.status_code == 200
    assert repurposed.json()["video_script"]
    assert repurposed.json()["xiaohongshu_post"]
    assert container.artifacts.read_json(task["id"], "repurposed")["moments_blurb"]

    reviewed = client.post(f"/api/v1/articles/{task['id']}/mark-reviewed")
    assert reviewed.status_code == 200
    assert reviewed.json()["status"] == "HUMAN_REVIEWED"

    review_page = client.get(f"/review/{task['id']}")
    assert review_page.status_code == 200
    assert "排版预览" in review_page.text
    assert 'id="review-markdown"' in review_page.text


def test_mark_published_backfills_topic_performance_and_shows_on_data(tmp_path: Path):
    client, container = build_client(tmp_path)

    created = client.post(
        "/api/v1/tasks",
        json={
            "mode": "fixed_topic",
            "request": "LangGraph 检查点实战",
            "topic": "LangGraph 检查点实战",
        },
    )
    task = created.json()
    advance(
        container,
        task["id"],
        TaskStatus.PLANNED,
        TaskStatus.RESEARCHED,
        TaskStatus.WRITTEN,
        TaskStatus.ASSETS_READY,
        TaskStatus.REVIEWED,
        TaskStatus.FORMATTED,
        TaskStatus.HUMAN_REVIEWED,
    )

    published = client.post(
        f"/api/v1/articles/{task['id']}/mark-published",
        json={
            "task_id": task["id"],
            "article_url": "https://mp.weixin.qq.com/s/abc",
            "published_at": "2026-07-10T12:00:00+08:00",
            "draft_media_id": "m1",
        },
    )
    assert published.status_code == 200
    assert container.tasks.get(task["id"]).status == TaskStatus.PUBLISHED
    assert container.topic_records.get(task["id"]).published_at is not None

    client.post(
        "/api/v1/metrics/import",
        files={
            "file": (
                "metrics.csv",
                "日期,文章ID,标题,阅读人数,分享人数,收藏人数,新增关注\n"
                "2026-07-09,a-1,LangGraph 检查点实战,150,20,5,3\n".encode("utf-8-sig"),
                "text/csv",
            )
        },
    )

    backfilled = client.post(f"/api/v1/articles/{task['id']}/backfill-metrics")
    assert backfilled.status_code == 200
    assert backfilled.json()["reads"] == 150
    assert backfilled.json()["shares"] == 20

    data_page = client.get("/data")
    assert data_page.status_code == 200
    assert "选题表现" in data_page.text
    assert "已回填" in data_page.text


def test_backfill_rejects_ambiguous_articles_with_the_same_title(tmp_path: Path):
    client, container = build_client(tmp_path)
    task = client.post(
        "/api/v1/tasks",
        json={
            "mode": "fixed_topic",
            "request": "LangGraph 检查点实战",
            "topic": "LangGraph 检查点实战",
        },
    ).json()
    advance(
        container,
        task["id"],
        TaskStatus.PLANNED,
        TaskStatus.RESEARCHED,
        TaskStatus.WRITTEN,
        TaskStatus.ASSETS_READY,
        TaskStatus.REVIEWED,
        TaskStatus.FORMATTED,
        TaskStatus.HUMAN_REVIEWED,
    )
    assert (
        client.post(
            f"/api/v1/articles/{task['id']}/mark-published",
            json={
                "task_id": task["id"],
                "article_url": "https://mp.weixin.qq.com/s/abc",
                "published_at": "2026-07-10T12:00:00+08:00",
                "draft_media_id": "m1",
            },
        ).status_code
        == 200
    )
    csv_body = (
        "日期,文章ID,标题,阅读人数,分享人数,收藏人数,新增关注\n"
        "2026-07-09,a-1,LangGraph 检查点实战,150,20,5,3\n"
        "2026-07-09,a-2,LangGraph 检查点实战,80,10,2,1\n"
    ).encode("utf-8-sig")
    assert (
        client.post(
            "/api/v1/metrics/import",
            files={"file": ("metrics.csv", csv_body, "text/csv")},
        ).status_code
        == 200
    )

    backfilled = client.post(f"/api/v1/articles/{task['id']}/backfill-metrics")

    assert backfilled.status_code == 409
    assert "多个文章" in backfilled.json()["detail"]


def test_calendar_page_renders_plan_board_or_empty_state(tmp_path: Path):
    client, container = build_client(tmp_path)

    empty = client.get("/calendar")
    assert empty.status_code == 200
    assert "内容日历" in empty.text
    assert "还没有周计划" in empty.text

    # A weekly plan task with a plan artifact renders a board.
    task = container.tasks.create(TaskSpec(mode=TaskMode.WEEKLY_PLAN, request="安排下周内容"))
    container.artifacts.write_json(
        task.id,
        "weekly_plan",
        {
            "week_start": "2026-07-20",
            "items": [
                {"day": "周一", "topic": "检查点实战", "format": "深度长文", "purpose": "讲机制"},
                {"day": "周三", "topic": "MCP 边界", "format": "框架对比", "purpose": "厘清概念"},
            ],
            "rationale": [],
        },
    )
    container.tasks.create(
        TaskSpec(
            mode=TaskMode.FIXED_TOPIC,
            request="厘清概念",
            topic="MCP 边界",
            plan_id=task.id,
        )
    )

    page = client.get("/calendar")
    assert page.status_code == 200
    assert "检查点实战" in page.text
    assert "MCP 边界" in page.text
    assert "运行任务" in page.text or "建任务" in page.text
