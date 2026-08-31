from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.dependencies import get_container
from app.container import ApplicationContainer
from app.domain.models import McpServerConfig, McpServerStatus

router = APIRouter(prefix="/mcp", tags=["mcp"])


class McpToggleRequest(BaseModel):
    enabled: bool


class McpToolCallRequest(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


@router.get("/servers", response_model=list[McpServerStatus])
def list_servers(
    container: ApplicationContainer = Depends(get_container),
) -> list[McpServerStatus]:
    return container.mcp.snapshot()


@router.post("/servers/{name}/probe", response_model=McpServerStatus)
async def probe_server(
    name: str,
    container: ApplicationContainer = Depends(get_container),
) -> McpServerStatus:
    try:
        return await container.mcp.probe(name)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "MCP 服务器未配置") from exc


@router.patch("/servers/{name}", response_model=McpServerConfig)
def toggle_server(
    name: str,
    payload: McpToggleRequest,
    container: ApplicationContainer = Depends(get_container),
) -> McpServerConfig:
    try:
        return container.mcp.set_enabled(name, payload.enabled)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "MCP 服务器未配置") from exc


@router.get("/servers/{name}/tools")
async def server_tools(
    name: str,
    container: ApplicationContainer = Depends(get_container),
) -> dict:
    try:
        tools = await container.mcp.list_tools(name)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "MCP 服务器未配置") from exc
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return {"tools": [tool.model_dump(mode="json") for tool in tools]}


@router.post("/servers/{name}/tools/{tool_name}/call")
async def call_tool(
    name: str,
    tool_name: str,
    payload: McpToolCallRequest,
    container: ApplicationContainer = Depends(get_container),
) -> dict:
    try:
        return await container.mcp.call_tool(name, tool_name, payload.arguments)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "MCP 服务器未配置") from exc
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"MCP 工具调用失败: {exc}") from exc
