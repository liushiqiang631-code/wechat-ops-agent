from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.container import build_container
from app.domain.enums import TaskMode, TaskStatus
from app.domain.models import (
    ArticleDocument,
    ArticleSection,
    MetricRecord,
    PublicationRecord,
    TaskSpec,
)
from app.main import create_app
from app.services.analytics.importers import import_metrics, wechat_day_to_metrics
from app.services.analytics.topic_feedback import backfill_published_metrics, sync_topic_record
from app.services.citations.fetcher import SafeSourceFetcher
from app.services.formatting.renderer import render_wechat_html
from app.services.formatting.sentinels import check_html_sentinels


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite:///{tmp_path / 'r.db'}",
        object_storage_path=tmp_path / "outputs",
        business_timezone="Asia/Shanghai",
    )


def test_sentinel_passes_when_article_contains_escaped_characters():
    article = ArticleDocument(
        titles=["C++ 与 Rust 的工程取舍"],
        selected_title="C++ 与 Rust 的工程取舍",
        digest="对比 & 取舍。",
        audience="AI 应用开发者",
        sections=[
            ArticleSection(type="paragraph", content="A < B 是基本判断。"),
            ArticleSection(type="paragraph", content="包含 & 符号与引号 \" 的内容。"),
        ],
        references=["https://docs.langchain.com/oss/python/langgraph"],
        ending="结论：A < B，但 & 也很重要。",
    )

    html = render_wechat_html(article)
    report = check_html_sentinels(article, html)

    assert report.passed is True, report.missing


def test_reviewed_state_can_fail():
    assert TaskStatus.REVIEWED.can_transition_to(TaskStatus.FAILED)


def test_api_reimport_is_idempotent(tmp_path: Path):
    client = TestClient(create_app(_settings(tmp_path), build_container(_settings(tmp_path))))
    csv_body = (
        "日期,文章ID,标题,阅读人数,分享人数,收藏人数,新增关注\n"
        "2026-07-17,a-1,检查点,100,8,5,3\n"
    ).encode("utf-8-sig")

    def upload():
        return client.post(
            "/api/v1/metrics/import",
            files={"file": ("metrics.csv", csv_body, "text/csv")},
        )

    first, second = upload(), upload()

    assert first.json()["imported"] == 1
    assert second.json()["imported"] == 0


def test_import_skips_malformed_rows_and_counts_them(tmp_path: Path):
    path = tmp_path / "bad.csv"
    path.write_text(
        "日期,文章ID,标题,阅读人数,分享人数,收藏人数,新增关注\n"
        "2026-07-17,a-1,好的,100,8,5,3\n"
        "2026-07-17,a-2,带千分位,\"1,234\",8,5,3\n"
        "not-a-date,a-3,坏日期,50,1,1,1\n",
        encoding="utf-8-sig",
    )

    result = import_metrics(path)

    # Comma-formatted numbers are normalized; only the unparseable-date row is skipped.
    assert len(result.records) == 2
    assert result.records[0].article_id == "a-1"
    assert result.records[1].reads == 1234
    assert result.skipped_rows == 1


def test_wechat_followers_attached_once_per_day():
    records = wechat_day_to_metrics(
        [{"ref_date": "2026-07-17", "new_user": 5}],
        [
            {"ref_date": "2026-07-17", "msgid": 1, "title": "甲"},
            {"ref_date": "2026-07-17", "msgid": 2, "title": "乙"},
            {"ref_date": "2026-07-17", "msgid": 3, "title": "丙"},
        ],
    )

    followers = sum(record.followers_gained for record in records)
    assert followers == 5


def test_sync_preserves_backfilled_metrics(tmp_path: Path):
    container = build_container(_settings(tmp_path))
    task = container.tasks.create(
        TaskSpec(mode=TaskMode.FIXED_TOPIC, request="LangGraph 检查点", topic="LangGraph 检查点")
    )
    sync_topic_record(container, task)
    container.publications.register(
        PublicationRecord(
            task_id=task.id,
            article_url="https://mp.weixin.qq.com/s/abc",
            published_at=datetime.now().astimezone(),
            draft_media_id="m1",
        )
    )
    container.metrics.insert(
        [
            MetricRecord(
                metric_date=datetime.now().astimezone() - timedelta(days=1),
                article_id="a-1",
                article_title="LangGraph 检查点",
                reads=200,
                shares=10,
                favorites=5,
                followers_gained=2,
                source_type="csv",
                source_record_id="row-1",
            )
        ]
    )
    backfill_published_metrics(container, task.id)
    before = container.topic_records.get(task.id)

    # A later mark-published / choose-title re-sync must not wipe measured metrics.
    sync_topic_record(container, container.tasks.get(task.id))
    after = container.topic_records.get(task.id)

    assert before.reads == 200
    assert after.reads == 200
    assert after.measured_at is not None


@pytest.mark.asyncio
async def test_fetcher_rejects_redirect_to_private_host():
    async with respx.mock:
        respx.get("https://public.example.com/start").mock(
            return_value=httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})
        )
        respx.get("http://127.0.0.1/secret").mock(
            return_value=httpx.Response(200, text="INTERNAL SECRET")
        )
        fetcher = SafeSourceFetcher()

        with pytest.raises(ValueError, match="private"):
            await fetcher.fetch("https://public.example.com/start")


def test_capability_probe_missing_credentials_returns_structured_report(tmp_path: Path):
    settings = _settings(tmp_path)  # wechat_app_id/secret unset
    client = TestClient(create_app(settings, build_container(settings)))

    response = client.post("/api/v1/capabilities/probe")

    assert response.status_code == 200
    checks = response.json()["checks"]
    assert checks[0]["name"] == "access_token"
    assert checks[0]["status"] == "blocked"
    assert all(check["status"] == "not_run" for check in checks[1:])


def test_mark_published_unknown_task_returns_404(tmp_path: Path):
    client = TestClient(create_app(_settings(tmp_path), build_container(_settings(tmp_path))))

    response = client.post(
        "/api/v1/articles/does-not-exist/mark-published",
        json={
            "task_id": "does-not-exist",
            "article_url": "https://mp.weixin.qq.com/s/x",
            "published_at": "2026-07-10T12:00:00+08:00",
            "draft_media_id": "m1",
        },
    )

    assert response.status_code == 404
