from __future__ import annotations

import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.api.dependencies import get_container
from app.api.uploads import UploadTooLargeError, read_upload_limited
from app.container import ApplicationContainer
from app.services.wechat.client import WeChatAPIError

router = APIRouter(prefix="/media", tags=["media"])


@router.post("/cover")
async def upload_cover(
    file: UploadFile = File(...),
    container: ApplicationContainer = Depends(get_container),
) -> dict:
    """Upload a cover image to WeChat permanent material and return its media_id."""
    if not container.settings.wechat_draft_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "草稿写入未启用")
    suffix = (Path(file.filename or "cover.jpg").suffix or ".jpg").lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".gif"}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "仅支持 JPG、PNG 或 GIF 图片")
    try:
        body = await read_upload_limited(
            file,
            max_bytes=container.settings.cover_upload_max_bytes,
        )
    except UploadTooLargeError as exc:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, str(exc)) from exc
    if not body:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "封面图片为空")
    temporary_path: str | None = None
    try:
        with NamedTemporaryFile(suffix=suffix, delete=False) as temporary:
            temporary.write(body)
            temporary_path = temporary.name
        token = await container.token_manager.get()
        media_id = await container.media.upload_cover(token, Path(temporary_path))
        return {"media_id": media_id}
    except WeChatAPIError as exc:
        # Surface the actionable guidance (e.g. IP whitelist, material permissions)
        # instead of a generic 500.
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            exc.guidance(),
        ) from exc
    except (ValueError, FileNotFoundError) as exc:
        # MediaUploader._validate rejects unsupported types and oversized files.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)
