from __future__ import annotations

import re
from typing import Any

import httpx

from app.config.settings import Settings
from app.services.wechat.error_mapper import map_wechat_error


class WeChatAPIError(RuntimeError):
    def __init__(self, code: int, message: str):
        info = map_wechat_error(code)
        safe_message = message.replace("access_token", "token")
        super().__init__(f"WeChat API error {code}: {safe_message}")
        self.code = code
        self.category = info.category
        self.retryable = info.retryable
        self.operator_action = info.operator_action
        self.errmsg = safe_message

    def guidance(self) -> str:
        """Actionable guidance for the user; for whitelist errors includes the current egress IP."""
        detail = f"微信接口错误 {self.code}:{self.operator_action}"
        if self.code == 40164:
            match = re.search(r"invalid ip ([\d.]+)", self.errmsg)
            if match:
                detail += f"（当前出口 IP：{match.group(1)}）"
        return detail


class WeChatClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self._client = client

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: object | None = None,
        files: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            base_url=self.settings.wechat_api_base,
            timeout=httpx.Timeout(timeout, connect=10.0),
            # 微信按出口 IP 校验白名单；固定直连避免系统代理导致 IP 漂移
            trust_env=False,
        )
        try:
            response = await client.request(
                method,
                path,
                params=params,
                json=json,
                files=files,
                data=data,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise WeChatAPIError(-1, "network timeout") from exc
        finally:
            if owns_client:
                await client.aclose()
        if response.status_code >= 500:
            raise WeChatAPIError(-1, f"HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise WeChatAPIError(-1, "invalid JSON response") from exc
        code = int(payload.get("errcode", 0))
        if code:
            raise WeChatAPIError(code, str(payload.get("errmsg", "unknown error")))
        return payload
