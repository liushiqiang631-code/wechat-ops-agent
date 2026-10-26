from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import get_container
from app.container import ApplicationContainer
from app.web.routes import _render
from app.web.view_models import build_settings_context

router = APIRouter(tags=["private-space"])


class RestoreRequest(BaseModel):
    recovery_code: str = Field(min_length=1, max_length=100)


@router.get("/space", response_class=HTMLResponse)
def space_page(
    request: Request,
    container: ApplicationContainer = Depends(get_container),
):
    context = build_settings_context(container)
    context["space_label"] = f"私人空间 · {container.workspace_id[:8].upper()}"
    context["has_recovery"] = request.state.space_manager.recovery_saved(container.workspace_id)
    return _render(request, "space.html", context, "space")


@router.get("/api/v1/space")
def current_space(request: Request):
    return {
        "id": request.state.space_id,
        "has_recovery": request.state.space_manager.recovery_saved(request.state.space_id),
    }


@router.post("/api/v1/space/recovery")
def generate_recovery(request: Request):
    manager = request.state.space_manager
    manager.rate_limit("rotate", request.state.space_id, 10, 3600)
    code = manager.rotate_recovery(request.state.space_id, request.state.space_token)
    return {"recovery_code": code}


@router.post("/api/v1/space/restore")
async def restore_space(payload: RestoreRequest, request: Request):
    manager = request.app.state.spaces
    client = request.client.host if request.client else "unknown"
    await run_in_threadpool(manager.rate_limit, "restore", client, 15, 900)
    _, token = await run_in_threadpool(manager.restore, payload.recovery_code.strip())
    response = JSONResponse({"ok": True})
    manager.set_cookie(response, token)
    return response
