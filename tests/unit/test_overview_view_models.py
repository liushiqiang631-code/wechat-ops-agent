from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.config.settings import Settings
from app.container import build_container
from app.domain.enums import TaskMode, TaskStatus
from app.domain.models import AssetManifest, AssetRecord, MetricRecord, TaskRecord
from app.services.analytics.topic_feedback import sync_topic_record
from app.web.view_models import (
    build_dashboard_context,
    build_topics_context,
    calendar_month_grid,
    cover_gallery,
    daily_series,
    fans_summary,
    overview_kpis,
    trend_change_summary,
    trend_chart,
    workflow_view,
)

NOW = datetime(2026, 7, 18, 12, tzinfo=UTC)


def build_container_for(tmp_path: Path):
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'overview.db'}",
        object_storage_path=tmp_path / "outputs",
    )
    return build_container(settings)


def metric_record(*, days_ago: int, reads: int = 100, followers: int = 3) -> MetricRecord:
    return MetricRecord(
        metric_date=NOW - timedelta(days=days_ago),
        article_id="article-1",
        article_title="示例文章",
        reads=reads,
        shares=5,
        favorites=2,
        followers_gained=followers,
        source_type="csv",
        source_record_id=f"row-{days_ago}",
    )


def test_overview_kpis_stay_empty_without_data(tmp_path: Path):
    container = build_container_for(tmp_path)

    cards = overview_kpis(container, reference=NOW)

    by_key = {card["key"]: card for card in cards}
    assert by_key["generated"]["display_value"] == "0"
    assert by_key["generated"]["has_data"] is False
    assert by_key["drafts"]["has_data"] is False
    assert by_key["assets"]["display_value"] == "—"
    assert by_key["followers"]["display_value"] == "—"
    assert by_key["followers"]["has_data"] is False


def _create_task(container, *, request: str, created_at: datetime, target: TaskStatus):
    created = container.tasks.create(
        TaskRecord(
            mode=TaskMode.FIXED_TOPIC,
            request=request,
            created_at=created_at,
        )
    )
    sequence = [
        TaskStatus.DATA_SYNCED,
        TaskStatus.PLANNED,
        TaskStatus.RESEARCHED,
        TaskStatus.WRITTEN,
        TaskStatus.ASSETS_READY,
    ]
    for status in sequence:
        container.tasks.transition(created.id, status)
        if status == target:
            break
    return created


def test_overview_kpis_count_tasks_drafts_and_followers(tmp_path: Path):
    container = build_container_for(tmp_path)
    container.tasks.create(
        TaskRecord(
            mode=TaskMode.FIXED_TOPIC,
            request="写一篇关于恢复机制的文章",
            created_at=NOW,
        )
    )
    _create_task(
        container,
        request="昨天创建的任务",
        created_at=NOW - timedelta(days=1),
        target=TaskStatus.WRITTEN,
    )
    _create_task(
        container,
        request="初稿后已配图的任务",
        created_at=NOW - timedelta(days=1),
        target=TaskStatus.ASSETS_READY,
    )
    records = [
        metric_record(days_ago=0, followers=12),
        metric_record(days_ago=1, followers=4),
    ]
    container.metrics.insert(records)

    cards = overview_kpis(container, reference=NOW)

    by_key = {card["key"]: card for card in cards}
    assert by_key["generated"]["value"] == 1
    assert by_key["generated"]["has_data"] is True
    assert by_key["assets"]["value"] == 50.0
    assert by_key["assets"]["display_value"] == "50%"
    assert by_key["followers"]["display_value"] == "+12"
    assert by_key["followers"]["change_direction"] == "up"


def test_workflow_view_maps_statuses_to_six_steps(tmp_path: Path):
    container = build_container_for(tmp_path)

    empty = workflow_view(container, reference=NOW)
    assert [step["state"] for step in empty["steps"]] == ["waiting"] * 6
    assert empty["badge"] == "待命"

    _create_task(
        container,
        request="写一篇关于恢复机制的文章",
        created_at=NOW,
        target=TaskStatus.ASSETS_READY,
    )
    running = workflow_view(container, reference=NOW)
    states = [step["state"] for step in running["steps"]]
    assert states == ["done", "done", "done", "active", "pending", "pending"]
    assert running["steps"][4]["detail"].endswith("正式群发由人工完成")
    assert running["badge"] == "运行中"


def test_daily_series_buckets_reads_and_shares_per_day():
    records = [
        metric_record(days_ago=0, reads=120),
        metric_record(days_ago=0, reads=30),
        metric_record(days_ago=9, reads=999),
    ]

    series = daily_series(records, days=7, reference=NOW)

    assert len(series) == 7
    assert series[-1]["reads"] == 150
    assert series[0]["reads"] == 0
    assert all(item["has_data"] is False for item in series[:-1])


def test_trend_chart_reports_empty_and_serializes_series():
    empty_chart = trend_chart(daily_series([], days=7, reference=NOW))
    assert empty_chart["empty"] is True

    series = daily_series([metric_record(days_ago=1, reads=500)], days=7, reference=NOW)
    chart = trend_chart(series)
    assert chart["empty"] is False
    assert len(chart["bars"]) == 7
    assert len(chart["dots"]) == 7
    assert chart["y_ticks"][0]["ratio"] == 1.0


def test_trend_change_summary_handles_missing_baseline():
    change = trend_change_summary([], reference=NOW)
    assert change["reads_direction"] == "neutral"
    assert change["reads_text"] == "上周暂无对比"

    records = [
        metric_record(days_ago=0, reads=200),
        metric_record(days_ago=10, reads=50),
    ]
    change = trend_change_summary(records, reference=NOW)
    assert change["reads_direction"] == "up"


def test_calendar_month_grid_contains_today():
    weeks = calendar_month_grid(NOW)

    flat = [cell for week in weeks for cell in week]
    assert any(cell["is_today"] for cell in flat)
    assert all(any(cell["in_month"] for cell in week) for week in weeks)
    assert len(weeks[0]) == 7


def test_fans_summary_builds_distribution_from_real_records(tmp_path: Path):
    container = build_container_for(tmp_path)
    records = [
        MetricRecord(
            metric_date=NOW - timedelta(days=1),
            article_id="a-1",
            article_title="文章一",
            reads=300,
            shares=10,
            favorites=5,
            followers_gained=8,
            source_type="csv",
            source_record_id="r1",
        ),
        MetricRecord(
            metric_date=NOW - timedelta(days=2),
            article_id="a-2",
            article_title="文章二",
            reads=100,
            shares=4,
            favorites=1,
            followers_gained=2,
            source_type="csv",
            source_record_id="r2",
        ),
    ]
    container.metrics.insert(records)

    summary = fans_summary(container, reference=NOW)

    assert summary["has_data"] is True
    assert summary["cards"][0]["value"] == "+0"  # 最新数据在昨天，今天为 0
    assert summary["cards"][1]["value"] == "+10"
    assert summary["distribution"][0]["label"] == "文章一"
    assert summary["distribution"][0]["percent"] == 75.0


def test_dashboard_context_has_overview_sections(tmp_path: Path):
    container = build_container_for(tmp_path)

    context = build_dashboard_context(container, now=NOW)

    assert context["active_task"] is None
    assert len(context["kpi_cards"]) == 4
    assert len(context["workflow"]["steps"]) == 6
    assert context["article_preview"] is None
    assert len(context["covers"]["styles"]) == 3
    assert context["mini_calendar"]["weeks"]
    assert "trend" in context
    assert "trend_change" in context
    assert "fans" in context


def test_cover_gallery_lists_style_placeholders(tmp_path: Path):
    container = build_container_for(tmp_path)

    covers = cover_gallery(container)

    assert [style["key"] for style in covers["styles"]] == ["mountain", "desk", "coffee"]
    assert covers["recent_assets"] == []


def test_cover_gallery_shows_generation_time_newest_first(tmp_path: Path):
    container = build_container_for(tmp_path)
    task = container.tasks.create(
        TaskRecord(
            mode=TaskMode.FIXED_TOPIC,
            request="写一篇关于恢复机制的文章",
            created_at=NOW,
        )
    )
    older = AssetRecord(
        asset_id="cover1",
        kind="cover",
        caption="旧封面",
        created_at=NOW - timedelta(days=1),
    )
    newer = AssetRecord(asset_id="cover2", kind="concept", caption="新配图", created_at=NOW)
    container.artifacts.write_json(
        task.id,
        "assets",
        AssetManifest(task_id=task.id, items=[older, newer]).model_dump(mode="json"),
    )

    covers = cover_gallery(container)

    assets = covers["recent_assets"]
    assert [asset["asset_id"] for asset in assets] == ["cover2", "cover1"]
    assert assets[0]["created_label"].startswith("07-18")
    assert assets[1]["created_label"].startswith("07-17")
    assert "T12:00" in assets[0]["created_iso"]


def test_topics_context_lists_every_task_topic_even_unpublished(tmp_path: Path):
    container = build_container_for(tmp_path)
    created = container.tasks.create(
        TaskRecord(
            mode=TaskMode.FIXED_TOPIC,
            request="写一篇关于恢复机制的文章",
            created_at=NOW,
        )
    )
    sync_topic_record(container, created)

    context = build_topics_context(container, now=NOW)

    topics = context["topics"]
    assert topics["has_data"] is True
    assert topics["total"] == 1
    assert topics["measured"] == 0
    row = topics["rows"][0]
    assert row["topic"] == "写一篇关于恢复机制的文章"
    assert row["mode"] == "fixed_topic"
    assert row["created_at"] == "2026-07-18"
    assert row["published_at"] == "—"
    assert row["measured"] is False
