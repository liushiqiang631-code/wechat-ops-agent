from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.container import build_container
from app.domain.enums import TaskStatus
from app.main import create_app


def build_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite:///{tmp_path / 'interactions.db'}",
        object_storage_path=tmp_path / "outputs",
    )
    return TestClient(create_app(settings, build_container(settings)))


def test_console_script_has_accessible_drawers_and_real_actions(tmp_path: Path):
    script = build_client(tmp_path).get("/static/app.js")

    assert script.status_code == 200
    assert "openDrawer" in script.text
    assert "closeDrawer" in script.text
    assert "previouslyFocused" in script.text
    assert 'event.key === "Escape"' in script.text
    assert "pendingActions" in script.text
    assert "/api/v1/metrics/import" in script.text
    assert "/api/v1/tasks" in script.text
    assert "showModal()" in script.text
    assert "window.alert" not in script.text


def test_drawer_actions_match_task_and_import_api_contracts(tmp_path: Path):
    client = build_client(tmp_path)

    created = client.post(
        "/api/v1/tasks",
        json={
            "mode": "fixed_topic",
            "request": "解释 Agent 工程中的恢复机制",
            "topic": "解释 Agent 工程中的恢复机制",
        },
    )
    imported = client.post(
        "/api/v1/metrics/import",
        files={
            "file": (
                "metrics.csv",
                (
                    "日期,文章ID,标题,阅读人数,分享人数,收藏人数,新增关注\n"
                    "2026-07-18,article-1,恢复机制,100,8,5,3\n"
                ).encode("utf-8-sig"),
                "text/csv",
            )
        },
    )

    assert created.status_code == 201
    assert created.json()["status"] == "CREATED"
    assert imported.status_code == 200
    assert imported.json()["imported"] == 1


def test_tasks_page_shows_delete_for_local_task_and_wechat_draft(tmp_path: Path):
    client = build_client(tmp_path)
    local_task = client.post(
        "/api/v1/tasks",
        json={
            "mode": "fixed_topic",
            "request": "可删除的本地任务",
            "topic": "可删除的本地任务",
        },
    ).json()
    draft_task = client.post(
        "/api/v1/tasks",
        json={
            "mode": "fixed_topic",
            "request": "受保护的微信草稿",
            "topic": "受保护的微信草稿",
        },
    ).json()
    for status in (
        TaskStatus.PLANNED,
        TaskStatus.RESEARCHED,
        TaskStatus.WRITTEN,
        TaskStatus.ASSETS_READY,
        TaskStatus.REVIEWED,
        TaskStatus.FORMATTED,
        TaskStatus.WECHAT_DRAFTED,
    ):
        client.app.state.container.tasks.transition(draft_task["id"], status)

    page = client.get("/tasks")

    assert page.status_code == 200
    assert f'data-task-delete data-task-id="{local_task["id"]}"' in page.text
    assert f'data-task-delete data-task-id="{draft_task["id"]}"' in page.text
