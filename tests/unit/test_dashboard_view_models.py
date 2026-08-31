from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.config.settings import Settings
from app.container import build_container
from app.domain.enums import TaskMode, TaskStatus
from app.domain.models import MetricRecord, TaskRecord
from app.web.view_models import (
    build_dashboard_context,
    build_data_context,
    build_tasks_context,
    metric_cards,
    task_view,
)

NOW = datetime(2026, 7, 18, 12, tzinfo=UTC)


def record(
    *,
    days_ago: int,
    reads: int,
    shares: int = 0,
    followers_gained: int = 1,
) -> MetricRecord:
    return MetricRecord(
        metric_date=NOW - timedelta(days=days_ago),
        article_id=f"article-{days_ago}",
        article_title=f"Article {days_ago}",
        reads=reads,
        shares=shares,
        favorites=0,
        followers_gained=followers_gained,
        source_type="csv",
        source_record_id=f"row-{days_ago}",
    )


def test_metric_cards_use_real_current_and_previous_30_day_windows():
    records = [
        record(days_ago=2, reads=80, shares=8, followers_gained=3),
        record(days_ago=10, reads=100, shares=10, followers_gained=2),
        record(days_ago=40, reads=50, shares=2, followers_gained=1),
    ]

    cards = metric_cards(records, now=NOW)

    reads = next(card for card in cards if card["key"] == "reads")
    share_rate = next(card for card in cards if card["key"] == "share_rate")
    followers = next(card for card in cards if card["key"] == "followers")
    assert reads["value"] == 180
    assert reads["display_value"] == "180"
    assert reads["change_direction"] == "up"
    assert reads["change_text"] == "+260.0%"
    assert share_rate["display_value"] == "10.0%"
    assert followers["value"] == 5


def test_metric_cards_show_explicit_empty_state():
    cards = metric_cards([], now=NOW)

    assert all(card["has_data"] is False for card in cards)
    assert all(card["display_value"] == "—" for card in cards)
    assert all(card["change_direction"] == "neutral" for card in cards)


def test_task_view_translates_status_and_marks_available_action():
    created = task_view(
        TaskRecord(
            mode=TaskMode.FIXED_TOPIC,
            request="写一篇 Agent 任务恢复文章",
            status=TaskStatus.CREATED,
        )
    )
    formatted = task_view(
        TaskRecord(
            mode=TaskMode.FIXED_TOPIC,
            request="写一篇 Agent 任务恢复文章",
            status=TaskStatus.FORMATTED,
        )
    )
    human_reviewed = task_view(
        TaskRecord(
            mode=TaskMode.FIXED_TOPIC,
            request="写一篇 Agent 任务恢复文章",
            status=TaskStatus.HUMAN_REVIEWED,
        )
    )
    drafted = task_view(
        TaskRecord(
            mode=TaskMode.FIXED_TOPIC,
            request="写一篇 Agent 任务恢复文章",
            status=TaskStatus.WECHAT_DRAFTED,
        )
    )

    assert created["status_label"] == "等待运行"
    assert created["action"] == "run"
    assert created["current_stage_index"] == 0
    assert created["can_push_draft"] is False
    assert formatted["status_label"] == "等待人工审阅"
    assert formatted["action"] == "preview"
    assert formatted["current_stage_index"] == 6
    assert formatted["can_push_draft"] is True
    assert human_reviewed["can_push_draft"] is True
    assert drafted["can_push_draft"] is False


def test_dashboard_context_reads_real_capability_blocker(tmp_path: Path):
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'dashboard.db'}",
        object_storage_path=tmp_path / "outputs",
        wechat_app_id="wx-test",
        wechat_app_secret="secret-test",
    )
    capability_dir = settings.object_storage_path / "capabilities"
    capability_dir.mkdir(parents=True)
    (capability_dir / "capability_report.json").write_text(
        json.dumps(
            {
                "generated_at": NOW.isoformat(),
                "checks": [
                    {
                        "name": "access_token",
                        "status": "blocked",
                        "error_code": 40164,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    container = build_container(settings)

    workbench = build_dashboard_context(container, now=NOW)
    data = build_data_context(container, now=NOW)
    tasks = build_tasks_context(container, now=NOW)

    assert workbench["wechat_status"]["tone"] == "warning"
    assert workbench["wechat_status"]["label"] == "等待配置 IP 白名单"
    assert workbench["model_status"]["configured"] is False
    assert workbench["pipeline_stages"][0] == "需求"
    assert workbench["active_task"] is None
    assert "metric_cards" not in workbench

    assert data["metric_cards"][0]["display_value"] == "—"
    assert data["has_data"] is False
    assert data["data_quality"].total_records == 0
    assert len(data["windows"]) == 3
    assert data["windows"][1]["period"] == "近 30 天"

    assert tasks["task_views"] == []
    assert "active_task" not in tasks


def test_dashboard_context_ignores_stale_ip_whitelist_blocker(tmp_path: Path):
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'dashboard.db'}",
        object_storage_path=tmp_path / "outputs",
        wechat_app_id="wx-test",
        wechat_app_secret="secret-test",
    )
    capability_dir = settings.object_storage_path / "capabilities"
    capability_dir.mkdir(parents=True)
    (capability_dir / "capability_report.json").write_text(
        json.dumps(
            {
                "generated_at": (NOW - timedelta(hours=2)).isoformat(),
                "checks": [
                    {
                        "name": "access_token",
                        "status": "blocked",
                        "error_code": 40164,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    container = build_container(settings)

    workbench = build_dashboard_context(container, now=NOW)

    assert workbench["wechat_status"]["tone"] == "success"
    assert workbench["wechat_status"]["label"] == "微信已配置"
    assert "message" not in workbench["wechat_status"]
