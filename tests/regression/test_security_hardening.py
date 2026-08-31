from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config.settings import Settings
from app.container import build_container
from app.domain.enums import TaskStatus
from app.domain.models import TaskSpec
from app.main import create_app
from app.services.citations.fetcher import SafeSourceFetcher
from app.services.mcp.manager import McpManager
from app.services.storage.artifacts import ArtifactStore


def test_artifact_store_rejects_task_id_that_escapes_root(tmp_path: Path) -> None:
    """Removing the storage containment check must make this test fail."""
    store = ArtifactStore(tmp_path / "outputs")

    with pytest.raises(ValueError, match="task id"):
        store.write_json("../escaped", "article", {"title": "unsafe"})

    assert not (tmp_path / "escaped" / "article.latest.json").exists()


def test_task_spec_rejects_path_like_id() -> None:
    """Relaxing task ID validation to allow path separators must fail this test."""
    with pytest.raises(ValidationError):
        TaskSpec(id="../outside", mode="fixed_topic", request="写一篇安全测试文章")


@pytest.mark.asyncio
async def test_source_fetcher_blocks_private_redirect_before_request() -> None:
    """Following a redirect before validating its target must fail this test."""
    requested_hosts: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(request.url.host or "")
        if request.url.host == "public.example":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})
        raise AssertionError("private redirect target was requested")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)
    try:
        fetcher = SafeSourceFetcher(client=client)
        with pytest.raises(ValueError, match="private source hosts"):
            await fetcher.fetch("https://public.example/source")
    finally:
        await client.aclose()

    assert requested_hosts == ["public.example"]


class _ForbiddenMcpClient:
    def __init__(self) -> None:
        raise AssertionError("disabled MCP server must not create a client")


@pytest.mark.asyncio
async def test_disabled_mcp_server_cannot_call_tools(tmp_path: Path) -> None:
    """Ignoring the enabled flag in call_tool must fail this test."""
    config_path = tmp_path / "mcp_servers.json"
    config_path.write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "name": "disabled",
                        "url": "https://mcp.example.com/mcp",
                        "enabled": False,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(_env_file=None, mcp_servers_path=config_path)
    manager = McpManager(settings, client_factory=lambda _url: _ForbiddenMcpClient())

    with pytest.raises(RuntimeError, match="disabled"):
        await manager.call_tool("disabled", "dangerous", {})


def test_publication_registration_requires_human_review(tmp_path: Path) -> None:
    """Persisting a publication before state validation must fail this test."""
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        object_storage_path=tmp_path / "outputs",
    )
    container = build_container(settings)
    client = TestClient(create_app(settings, container))
    task = client.post(
        "/api/v1/tasks",
        json={"mode": "fixed_topic", "request": "写一篇状态安全测试文章"},
    ).json()

    response = client.post(
        f"/api/v1/articles/{task['id']}/mark-published",
        json={
            "task_id": task["id"],
            "article_url": "https://mp.weixin.qq.com/s/example",
            "published_at": "2026-08-23T12:00:00+08:00",
            "draft_media_id": "draft-1",
        },
    )

    assert response.status_code == 409
    with pytest.raises(KeyError):
        container.publications.get_by_task(task["id"])


def test_review_round_limit_cannot_exceed_two() -> None:
    """Removing the upper bound on MAX_REVIEW_ROUNDS must fail this test."""
    with pytest.raises(ValidationError):
        Settings(_env_file=None, max_review_rounds=3)


def test_reviewed_final_version_cannot_be_silently_replaced(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite:///{tmp_path / 'review.db'}",
        object_storage_path=tmp_path / "outputs",
    )
    container = build_container(settings)
    client = TestClient(create_app(settings, container))
    task = client.post(
        "/api/v1/tasks",
        json={"mode": "fixed_topic", "request": "写一篇终稿状态测试"},
    ).json()
    for task_status in (
        TaskStatus.PLANNED,
        TaskStatus.RESEARCHED,
        TaskStatus.WRITTEN,
        TaskStatus.ASSETS_READY,
        TaskStatus.REVIEWED,
        TaskStatus.FORMATTED,
    ):
        container.tasks.transition(task["id"], task_status)

    first = client.post(
        f"/api/v1/articles/{task['id']}/final-version",
        json={"generated_markdown": "# 初稿", "final_markdown": "# 已审终稿 A"},
    )
    assert first.status_code == 200
    assert client.post(f"/api/v1/articles/{task['id']}/mark-reviewed").status_code == 200

    replaced = client.post(
        f"/api/v1/articles/{task['id']}/final-version",
        json={"generated_markdown": "# 初稿", "final_markdown": "# 未审终稿 B"},
    )

    assert replaced.status_code == 409
    saved = container.artifacts.read_json(task["id"], "final_version")
    assert saved["markdown"] == "# 已审终稿 A"
