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
        database_url=f"sqlite:///{tmp_path / 'agent.db'}",
        object_storage_path=tmp_path / "outputs",
        mcp_servers_path=tmp_path / "mcp_servers.json",
    )
    return TestClient(create_app(settings, build_container(settings)))


def test_agent_capability_page_lists_skills_and_mcp(tmp_path: Path):
    client = build_client(tmp_path)

    page = client.get("/workflow")

    assert page.status_code == 200
    assert "工作流与能力" in page.text
    assert "human_writing" in page.text
    assert "MCP 服务器" in page.text
    # 配置指引可以提到环境变量名，但绝不能出现密钥形态的值
    assert re.search(r"sk-[A-Za-z0-9]{8,}", page.text) is None


def test_skills_api_lists_and_toggles_human_writing(tmp_path: Path):
    client = build_client(tmp_path)

    skills = client.get("/api/v1/skills")
    assert skills.status_code == 200
    names = {skill["name"] for skill in skills.json()}
    assert "human_writing" in names
    assert "writing" in names

    toggled = client.patch(
        "/api/v1/skills/human_writing",
        json={"enabled": False},
    )
    assert toggled.status_code == 200
    assert toggled.json()["enabled"] is False

    locked = client.patch("/api/v1/skills/writing", json={"enabled": False})
    assert locked.status_code == 409


def test_steps_endpoint_returns_404_before_any_run(tmp_path: Path):
    client = build_client(tmp_path)
    created = client.post(
        "/api/v1/tasks",
        json={"mode": "fixed_topic", "request": "写一篇测试文章", "topic": "测试"},
    )
    task_id = created.json()["id"]

    missing = client.get(f"/api/v1/tasks/{task_id}/steps")

    assert missing.status_code == 404


def test_mcp_api_lists_empty_servers_by_default(tmp_path: Path):
    client = build_client(tmp_path)

    servers = client.get("/api/v1/mcp/servers")

    assert servers.status_code == 200
    assert servers.json() == []
