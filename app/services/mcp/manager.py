from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config.settings import Settings
from app.domain.enums import ProbeStatus
from app.domain.models import McpServerConfig, McpServerStatus, McpToolInfo
from app.services.mcp.client import McpClient

PROBE_CACHE_TTL_SECONDS = 60.0


class McpManager:
    """Configuration, probing and tool invocation for MCP servers.

    Servers are declared in a local JSON file (``mcp_servers.json``, gitignored;
    see ``mcp_servers.example.json``). Probes are real connectivity checks and
    are cached briefly so the console stays responsive.
    """

    def __init__(self, settings: Settings, client_factory=None):
        self.settings = settings
        self._client_factory = client_factory or (
            lambda url, headers=None: McpClient(url, headers=headers or {})
        )
        self._probe_cache: dict[str, tuple[float, McpServerStatus]] = {}

    # -- configuration -----------------------------------------------------

    def config_path(self) -> Path:
        return self.settings.mcp_servers_path

    def list_configs(self) -> list[McpServerConfig]:
        path = self.config_path()
        if not path.exists():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return [McpServerConfig.model_validate(item) for item in raw.get("servers", [])]

    def save_configs(self, configs: list[McpServerConfig]) -> None:
        payload = {"servers": [config.model_dump(mode="json") for config in configs]}
        path = self.config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get_config(self, name: str) -> McpServerConfig:
        for config in self.list_configs():
            if config.name == name:
                return config
        raise KeyError(name)

    def set_enabled(self, name: str, enabled: bool) -> McpServerConfig:
        configs = self.list_configs()
        updated = None
        for index, config in enumerate(configs):
            if config.name == name:
                configs[index] = config.model_copy(update={"enabled": enabled})
                updated = configs[index]
                break
        if updated is None:
            raise KeyError(name)
        self.save_configs(configs)
        self._probe_cache.pop(name, None)
        return updated

    # -- probing -----------------------------------------------------------

    async def probe(self, name: str) -> McpServerStatus:
        config = self.get_config(name)
        if not config.enabled:
            return McpServerStatus(
                name=config.name,
                url=str(config.url),
                transport=config.transport,
                enabled=False,
                status=ProbeStatus.NOT_RUN,
                message="MCP server is disabled",
            )
        started = time.perf_counter()
        try:
            client = self._client_factory(str(config.url))
            await client.initialize()
            tools = await client.list_tools()
            latency = int((time.perf_counter() - started) * 1000)
            status = McpServerStatus(
                name=config.name,
                url=str(config.url),
                transport=config.transport,
                enabled=config.enabled,
                status=ProbeStatus.AVAILABLE,
                tools=[
                    McpToolInfo(
                        name=str(tool.get("name", "")),
                        description=tool.get("description"),
                        input_schema=tool.get("inputSchema") or {},
                    )
                    for tool in tools
                ],
                latency_ms=latency,
                probed_at=datetime.now(UTC),
            )
        except Exception as error:
            status = McpServerStatus(
                name=config.name,
                url=str(config.url),
                transport=config.transport,
                enabled=config.enabled,
                status=ProbeStatus.ERROR,
                message=f"{type(error).__name__}: {error}",
                probed_at=datetime.now(UTC),
            )
        self._probe_cache[name] = (time.monotonic(), status)
        return status

    def snapshot(self) -> list[McpServerStatus]:
        result: list[McpServerStatus] = []
        now = time.monotonic()
        for config in self.list_configs():
            cached = self._probe_cache.get(config.name)
            if cached is not None and now - cached[0] < PROBE_CACHE_TTL_SECONDS:
                status = cached[1].model_copy(
                    update={"enabled": config.enabled, "url": str(config.url)}
                )
            else:
                status = McpServerStatus(
                    name=config.name,
                    url=str(config.url),
                    transport=config.transport,
                    enabled=config.enabled,
                    status=ProbeStatus.NOT_RUN,
                )
            result.append(status)
        return result

    async def list_tools(self, name: str) -> list[McpToolInfo]:
        status = await self.probe(name)
        if status.status != ProbeStatus.AVAILABLE:
            raise RuntimeError(status.message or "MCP server is not available")
        return status.tools

    async def call_tool(self, name: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        config = self.get_config(name)
        if not config.enabled:
            raise RuntimeError(f"MCP server {name} is disabled")
        client = self._client_factory(str(config.url))
        await client.initialize()
        return await client.call_tool(tool, arguments or {})
