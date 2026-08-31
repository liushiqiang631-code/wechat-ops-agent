from __future__ import annotations

import mimetypes
from pathlib import Path

from app.services.wechat.client import WeChatClient


class MediaUploader:
    def __init__(self, client: WeChatClient):
        self.client = client

    @staticmethod
    def _validate(path: Path, max_bytes: int = 10 * 1024 * 1024) -> tuple[str, bytes]:
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(path)
        body = path.read_bytes()
        if len(body) > max_bytes:
            raise ValueError(f"media exceeds {max_bytes} bytes")
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if mime not in {"image/jpeg", "image/png", "image/gif", "image/bmp"}:
            raise ValueError(f"unsupported image type: {mime}")
        return mime, body

    async def upload_inline(self, token: str, path: Path) -> str:
        mime, body = self._validate(path, 2 * 1024 * 1024)
        payload = await self.client.request_json(
            "POST",
            "/cgi-bin/media/uploadimg",
            params={"access_token": token},
            files={"media": (Path(path).name, body, mime)},
        )
        return str(payload["url"])

    async def upload_cover(self, token: str, path: Path) -> str:
        mime, body = self._validate(path)
        payload = await self.client.request_json(
            "POST",
            "/cgi-bin/material/add_material",
            params={"access_token": token, "type": "image"},
            files={"media": (Path(path).name, body, mime)},
        )
        return str(payload["media_id"])
