from __future__ import annotations

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2025-06-18"


class McpError(RuntimeError):
    def __init__(self, message: str, *, code: str, retryable: bool):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def _parse_sse(body: str) -> list[dict[str, Any]]:
    """Extract JSON messages from a text/event-stream payload."""
    messages: list[dict[str, Any]] = []
    for line in body.splitlines():
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload and payload != "[DONE]":
                try:
                    messages.append(json.loads(payload))
                except json.JSONDecodeError:
                    continue
    return messages


class McpClient:
    """Minimal Model Context Protocol client (streamable HTTP transport).

    Deterministic and dependency-free beyond httpx: initialize handshake,
    tools/list and tools/call. Used by the MCP manager for probing and
    invoking configured MCP servers from the operator console.
    """

    def __init__(
        self,
        url: str,
        *,
        timeout: float = 20.0,
        headers: dict[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
    ):
        self.url = url
        self.timeout = timeout
        self.headers = headers or {}
        self._client = client
        self.session_id: str | None = None

    def _request_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **self.headers,
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout, connect=10.0),
            follow_redirects=True,
        )
        try:
            response = await client.post(self.url, json=payload, headers=self._request_headers())
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise McpError(
                f"MCP server {self.url} unreachable", code="network_error", retryable=True
            ) from exc
        finally:
            if owns_client:
                await client.aclose()
        if response.status_code in {401, 403}:
            raise McpError(
                "MCP server rejected credentials",
                code="authentication_failed",
                retryable=False,
            )
        if response.status_code == 404:
            raise McpError("MCP endpoint not found", code="not_found", retryable=False)
        if response.status_code >= 500:
            raise McpError("MCP server error", code="server_error", retryable=True)
        if response.is_error:
            raise McpError(
                f"MCP request failed with HTTP {response.status_code}",
                code="request_failed",
                retryable=False,
            )
        session_id = response.headers.get("mcp-session-id")
        if session_id:
            self.session_id = session_id
        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            messages = _parse_sse(response.text)
            for message in reversed(messages):
                if message.get("id") == payload.get("id"):
                    return message
            raise McpError(
                "MCP server returned no result for the request",
                code="empty_result",
                retryable=True,
            )
        return response.json()

    async def initialize(self) -> dict[str, Any]:
        result = await self._post(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"sampling": {}, "roots": {"listChanged": False}},
                    "clientInfo": {"name": "wechat-ops-agent", "version": "0.1.0"},
                },
            }
        )
        self._raise_for_error(result)
        # Fire-and-forget initialized notification (best effort, no result).
        try:
            await self._post(
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                    "params": {},
                }
            )
        except Exception as error:  # pragma: no cover - best effort
            logger.warning("MCP initialized notification failed: %s", error)
        return result.get("result", {})

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self._post({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self._raise_for_error(result)
        return (result.get("result") or {}).get("tools", [])

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await self._post(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )
        self._raise_for_error(result)
        return result.get("result", {})

    @staticmethod
    def _raise_for_error(message: dict[str, Any]) -> None:
        error = message.get("error")
        if error:
            raise McpError(
                f"MCP error {error.get('code')}: {error.get('message', 'unknown')}",
                code="jsonrpc_error",
                retryable=True,
            )
