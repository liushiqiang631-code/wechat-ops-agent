from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from app.config.settings import Settings
from app.domain.enums import ProbeStatus
from app.services.mcp.client import McpClient, McpError
from app.services.mcp.manager import McpManager

MCP_URL = "https://mcp.example.com/mcp"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        mcp_servers_path=tmp_path / "mcp_servers.json",
    )


def write_config(settings: Settings) -> None:
    settings.mcp_servers_path.write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "name": "demo",
                        "url": MCP_URL,
                        "transport": "streamable_http",
                        "description": "demo server",
                        "enabled": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


@respx.mock
@pytest.mark.asyncio
async def test_client_initializes_then_lists_tools():
    respx.post(MCP_URL).mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"protocolVersion": "2025-06-18", "serverInfo": {"name": "demo"}},
                },
                headers={"mcp-session-id": "sess-1"},
            ),
            # fire-and-forget notifications/initialized
            httpx.Response(200, json={}),
            httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "result": {
                        "tools": [
                            {
                                "name": "read_file",
                                "description": "读取文件",
                                "inputSchema": {"type": "object"},
                            }
                        ]
                    },
                },
            ),
        ]
    )
    client = McpClient(MCP_URL)

    initialized = await client.initialize()
    tools = await client.list_tools()

    assert initialized["serverInfo"]["name"] == "demo"
    assert tools[0]["name"] == "read_file"
    assert respx.calls[2].request.headers.get("mcp-session-id") == "sess-1"


@respx.mock
@pytest.mark.asyncio
async def test_client_parses_sse_stream_responses():
    body = (
        "event: message\ndata: {\"jsonrpc\":\"2.0\",\"id\":1,"
        "\"result\":{\"ok\":true}}\n\n"
        "data: [DONE]\n"
    )
    respx.post(MCP_URL).mock(
        return_value=httpx.Response(
            200,
            content=body,
            headers={"content-type": "text/event-stream"},
        )
    )
    client = McpClient(MCP_URL)

    result = await client.initialize()

    assert result == {"ok": True}


@respx.mock
@pytest.mark.asyncio
async def test_client_jsonrpc_error_becomes_mcp_error():
    respx.post(MCP_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32000, "message": "boom"},
            },
        )
    )
    client = McpClient(MCP_URL)

    with pytest.raises(McpError) as captured:
        await client.initialize()

    assert captured.value.code == "jsonrpc_error"
    assert "boom" in str(captured.value)


class FakeMcpClient:
    def __init__(self, url):
        self.url = url
        self.initialized = False

    async def initialize(self):
        self.initialized = True
        return {"protocolVersion": "2025-06-18"}

    async def list_tools(self):
        return [{"name": "demo_tool", "description": "demo", "inputSchema": {}}]

    async def call_tool(self, name, arguments):
        return {"content": [{"type": "text", "text": "ok"}]}


@pytest.mark.asyncio
async def test_manager_probe_caches_available_status(settings: Settings):
    write_config(settings)
    manager = McpManager(settings, client_factory=lambda url: FakeMcpClient(url))

    first = await manager.probe("demo")
    second = manager.snapshot()[0]

    assert first.status == ProbeStatus.AVAILABLE
    assert first.tools[0].name == "demo_tool"
    assert first.latency_ms is not None
    assert second.status == ProbeStatus.AVAILABLE
    assert second.name == "demo"


@pytest.mark.asyncio
async def test_manager_reports_not_run_before_any_probe(settings: Settings):
    write_config(settings)
    manager = McpManager(settings, client_factory=lambda url: FakeMcpClient(url))

    statuses = manager.snapshot()

    assert len(statuses) == 1
    assert statuses[0].status == ProbeStatus.NOT_RUN


def test_manager_toggle_enabled_persists(settings: Settings):
    write_config(settings)
    manager = McpManager(settings, client_factory=lambda url: FakeMcpClient(url))

    updated = manager.set_enabled("demo", False)

    assert updated.enabled is False
    assert manager.get_config("demo").enabled is False


def test_manager_missing_server_raises_key_error(settings: Settings):
    write_config(settings)
    manager = McpManager(settings, client_factory=lambda url: FakeMcpClient(url))

    with pytest.raises(KeyError):
        manager.get_config("ghost")
