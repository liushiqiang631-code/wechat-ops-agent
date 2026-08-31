from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from app.config.settings import Settings
from app.container import build_container
from app.domain.enums import TaskMode
from app.domain.models import MetricRecord, PublicationRecord, TaskSpec
from app.services.analytics.topic_feedback import (
    backfill_published_metrics,
    normalize_title,
    sync_topic_record,
)


def test_normalize_title_strips_punctuation_and_case():
    assert normalize_title("LangGraph 检查点，实战！") == normalize_title("langgraph检查点实战")
    assert normalize_title("  MCP 边界（一） ") == "mcp边界一"


def make_record(*, title: str, reads: int, days_ago: int) -> MetricRecord:
    return MetricRecord(
        metric_date=datetime.now().astimezone() - timedelta(days=days_ago),
        article_id=title,
        article_title=title,
        reads=reads,
        shares=2,
        favorites=1,
        followers_gained=1,
        source_type="csv",
        source_record_id=f"row-{title}",
    )


def test_backfill_links_published_task_to_imported_metrics_by_title(tmp_path: Path):
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'feedback.db'}",
        object_storage_path=tmp_path / "outputs",
        business_timezone="Asia/Shanghai",
    )
    container = build_container(settings)
    task = container.tasks.create(
        TaskSpec(
            mode=TaskMode.FIXED_TOPIC,
            request="LangGraph 检查点实战",
            topic="LangGraph 检查点实战",
        )
    )
    sync_topic_record(container, task)

    # Imported metrics whose title matches (spanning several days).
    container.metrics.insert(
        [
            make_record(title="LangGraph 检查点实战", reads=100, days_ago=3),
            make_record(title="LangGraph 检查点实战", reads=50, days_ago=2),
            make_record(title="不相关的文章", reads=999, days_ago=1),
        ]
    )
    publication = PublicationRecord(
        task_id=task.id,
        article_url="https://mp.weixin.qq.com/s/abc",
        published_at=datetime.now().astimezone(),
        draft_media_id="m1",
    )
    container.publications.register(publication)

    measured = backfill_published_metrics(container, task.id)

    assert measured.reads == 150
    assert measured.shares == 4
    assert measured.article_url == "https://mp.weixin.qq.com/s/abc"
    assert measured.measured_at is not None
    persisted = container.topic_records.get(task.id)
    assert persisted.reads == 150


def test_sync_topic_record_keeps_created_task_visible():
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path2()}/sync.db",
        object_storage_path=f"{tmp_path2()}/out",
    )
    container = build_container(settings)
    task = container.tasks.create(
        TaskSpec(mode=TaskMode.FIXED_TOPIC, request="写 Agent Skills", topic="Agent Skills")
    )

    sync_topic_record(container, task)

    record = container.topic_records.get(task.id)
    assert record.topic == "Agent Skills"
    assert record.published_at is None


def tmp_path2() -> str:
    import tempfile

    return tempfile.mkdtemp()
