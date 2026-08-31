from __future__ import annotations

import asyncio
import time

from app.config.settings import Settings
from app.services.wechat.client import WeChatClient


class TokenManager:
    def __init__(self, client: WeChatClient, settings: Settings):
        self.client = client
        self.settings = settings
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def get(self, *, force_refresh: bool = False) -> str:
        if not force_refresh and self._token and time.monotonic() < self._expires_at:
            return self._token
        async with self._lock:
            if not force_refresh and self._token and time.monotonic() < self._expires_at:
                return self._token
            if not self.settings.wechat_app_id or not self.settings.wechat_app_secret:
                raise RuntimeError("WeChat AppID/AppSecret are not configured")
            payload = await self.client.request_json(
                "GET",
                "/cgi-bin/token",
                params={
                    "grant_type": "client_credential",
                    "appid": self.settings.wechat_app_id,
                    "secret": self.settings.wechat_app_secret.get_secret_value(),
                },
            )
            self._token = str(payload["access_token"])
            ttl = max(int(payload.get("expires_in", 7200)) - 300, 60)
            self._expires_at = time.monotonic() + ttl
            return self._token

    def invalidate(self) -> None:
        self._token = None
        self._expires_at = 0.0
