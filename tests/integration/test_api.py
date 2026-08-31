from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.container import build_container
from app.domain.enums import TaskStatus
from app.domain.models import AssetManifest, AssetRecord
from app.main import create_app
from app.services.wechat.client import WeChatAPIError


def api_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        object_storage_path=tmp_path / "outputs",
    )
    container = build_container(settings)
    return TestClient(create_app(settings, container))


def test_task_create_list_get_and_draft_safety_gate(tmp_path: Path):
    client = api_client(tmp_path)

    created = client.post(
        "/api/v1/tasks",
        json={
            "mode": "fixed_topic",
            "request": "写一篇 LangGraph 检查点文章",
            "topic": "LangGraph 检查点",
        },
    )
    task = created.json()

    assert created.status_code == 201
    assert task["status"] == "CREATED"
    assert client.get(f"/api/v1/tasks/{task['id']}").status_code == 200
    assert client.get("/api/v1/tasks").json()[0]["id"] == task["id"]

    blocked = client.post(
        f"/api/v1/tasks/{task['id']}/push-draft",
        json={"thumb_media_id": "thumb-test"},
    )
    assert blocked.status_code == 403
    assert "草稿写入未启用" in blocked.json()["detail"]


def test_task_delete_removes_local_task_topic_record_and_artifacts(tmp_path: Path):
    client = api_client(tmp_path)
    task = client.post(
        "/api/v1/tasks",
        json={
            "mode": "fixed_topic",
            "request": "删除本地任务",
            "topic": "删除本地任务",
        },
    ).json()
    artifact_dir = tmp_path / "outputs" / task["id"]
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "article.latest.json").write_text("{}", encoding="utf-8")

    response = client.delete(f"/api/v1/tasks/{task['id']}")

    assert response.status_code == 204
    assert client.get(f"/api/v1/tasks/{task['id']}").status_code == 404
    assert not artifact_dir.exists()
    with pytest.raises(KeyError):
        client.app.state.container.topic_records.get(task["id"])


def test_task_delete_removes_local_record_for_wechat_draft_without_calling_wechat(tmp_path: Path):
    client = api_client(tmp_path)
    task = client.post(
        "/api/v1/tasks",
        json={
            "mode": "fixed_topic",
            "request": "保留微信草稿",
            "topic": "保留微信草稿",
        },
    ).json()
    task_id = task["id"]
    for status in (
        TaskStatus.PLANNED,
        TaskStatus.RESEARCHED,
        TaskStatus.WRITTEN,
        TaskStatus.ASSETS_READY,
        TaskStatus.REVIEWED,
        TaskStatus.FORMATTED,
        TaskStatus.WECHAT_DRAFTED,
    ):
        client.app.state.container.tasks.transition(task_id, status)
    artifact_dir = tmp_path / "outputs" / task_id
    artifact_dir.mkdir(parents=True)

    response = client.delete(f"/api/v1/tasks/{task_id}")

    assert response.status_code == 204
    assert client.get(f"/api/v1/tasks/{task_id}").status_code == 404
    assert not artifact_dir.exists()


def test_cover_upload_gated_when_draft_disabled(tmp_path: Path):
    client = api_client(tmp_path)

    response = client.post(
        "/api/v1/media/cover",
        files={"file": ("cover.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 8, "image/png")},
    )

    assert response.status_code == 403
    assert "草稿写入未启用" in response.json()["detail"]


def test_task_asset_serves_file_named_in_asset_manifest(tmp_path: Path):
    client = api_client(tmp_path)
    task = client.post(
        "/api/v1/tasks",
        json={"mode": "fixed_topic", "request": "展示配图", "topic": "展示配图"},
    ).json()
    task_id = task["id"]
    asset_dir = tmp_path / "outputs" / task_id / "assets"
    asset_dir.mkdir(parents=True)
    image_bytes = b"\x89PNG\r\n\x1a\nimage-bytes"
    (asset_dir / "img-00.png").write_bytes(image_bytes)
    client.app.state.container.artifacts.write_json(
        task_id,
        "assets",
        AssetManifest(
            task_id=task_id,
            items=[
                AssetRecord(
                    asset_id="img-00",
                    kind="concept",
                    file_name="img-00.png",
                    content_type="image/png",
                )
            ],
        ).model_dump(mode="json"),
    )

    response = client.get(f"/api/v1/tasks/{task_id}/assets/img-00")

    assert response.status_code == 200
    assert response.content == image_bytes


def test_cover_upload_returns_media_id(tmp_path: Path):
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        object_storage_path=tmp_path / "outputs",
        wechat_draft_enabled=True,
    )
    container = build_container(settings)

    class FakeMedia:
        async def upload_cover(self, token, path):  # noqa: ARG002
            return "media-cover-1"

    class FakeTokenManager:
        async def get(self):
            return "token-test"

    container.media = FakeMedia()  # type: ignore[assignment]
    container.token_manager = FakeTokenManager()  # type: ignore[assignment]
    client = TestClient(create_app(settings, container))

    response = client.post(
        "/api/v1/media/cover",
        files={"file": ("cover.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 8, "image/png")},
    )

    assert response.status_code == 200
    assert response.json() == {"media_id": "media-cover-1"}


def test_cover_upload_surfaces_wechat_whitelist_error(tmp_path: Path):
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        object_storage_path=tmp_path / "outputs",
        wechat_draft_enabled=True,
    )
    container = build_container(settings)

    class FakeTokenManager:
        async def get(self):
            raise WeChatAPIError(40164, "invalid ip 61.186.30.10, not in whitelist")

    container.token_manager = FakeTokenManager()  # type: ignore[assignment]
    client = TestClient(create_app(settings, container))

    response = client.post(
        "/api/v1/media/cover",
        files={"file": ("cover.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 8, "image/png")},
    )

    assert response.status_code == 502
    assert "白名单" in response.json()["detail"]
    assert "61.186.30.10" in response.json()["detail"]


def test_metrics_import_returns_quality_and_windows(tmp_path: Path):
    client = api_client(tmp_path)
    csv_body = (
        "日期,文章ID,标题,阅读人数,分享人数,收藏人数,新增关注\n"
        "2026-07-17,a-1,LangGraph 检查点,100,8,12,3\n"
    ).encode("utf-8-sig")

    response = client.post(
        "/api/v1/metrics/import",
        files={"file": ("metrics.csv", csv_body, "text/csv")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["imported"] == 1
    assert payload["quality"]["confidence"] > 0
    assert "7d" in payload["windows"]


def test_final_version_diff_and_publication_registration(tmp_path: Path):
    client = api_client(tmp_path)
    task = client.post(
        "/api/v1/tasks",
        json={"mode": "fixed_topic", "request": "写 Agent Skills", "topic": "Skills"},
    ).json()
    container = client.app.state.container
    for task_status in (
        TaskStatus.PLANNED,
        TaskStatus.RESEARCHED,
        TaskStatus.WRITTEN,
        TaskStatus.ASSETS_READY,
        TaskStatus.REVIEWED,
        TaskStatus.FORMATTED,
    ):
        container.tasks.transition(task["id"], task_status)
    diff = client.post(
        f"/api/v1/articles/{task['id']}/final-version",
        json={
            "generated_markdown": "# 入门\n\n在当今时代，值得注意。\n\n总的来说，未来可期。",
            "final_markdown": "# 工程边界\n\n先看一个具体问题。",
        },
    )

    assert diff.status_code == 200
    assert diff.json()["title_changed"] is True
    assert client.get(f"/api/v1/articles/{task['id']}/editorial-diff").status_code == 200

    container.tasks.transition(task["id"], TaskStatus.HUMAN_REVIEWED)

    publication = client.post(
        f"/api/v1/articles/{task['id']}/mark-published",
        json={
            "task_id": task["id"],
            "article_url": "https://mp.weixin.qq.com/s/example",
            "published_at": "2026-07-18T20:00:00+08:00",
            "draft_media_id": "media-1",
        },
    )
    assert publication.status_code == 200
    assert publication.json()["task_id"] == task["id"]
