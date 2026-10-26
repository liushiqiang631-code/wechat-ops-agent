from __future__ import annotations

from fastapi import HTTPException, Request

from app.container import ApplicationContainer


def get_container(request: Request) -> ApplicationContainer:
    if request.app.state.container.settings.anonymous_spaces_enabled:
        container = getattr(request.state, "space_container", None)
        if container is None:
            raise HTTPException(401, "请先打开网页创建空间，或使用恢复码恢复已有空间")
        return container
    return request.app.state.container
