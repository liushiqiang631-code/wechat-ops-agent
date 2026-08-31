from __future__ import annotations

import base64
import re

import httpx

from app.config.settings import Settings
from app.services.images.siliconflow import GeneratedImage


class DashScopeImageError(RuntimeError):
    def __init__(self, message: str, *, code: str, retryable: bool):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class DashScopeImageClient:
    """Text-to-image client for Alibaba Cloud Model Studio (百炼).

    Uses the synchronous multimodal-generation endpoint with the model id
    ``qwen-image-3.0-pro`` (per the official API reference). The response image
    may arrive as a public URL or as a base64 ``data:image/...`` URI; both are
    handled here so the materializer never has to guess.
    """

    provider_name = "dashscope"
    GENERATION_PATH = "/services/aigc/multimodal-generation/generation"
    _DATA_URI = re.compile(r"^data:image/([a-zA-Z0-9.+-]+);base64,(.*)$", re.S)

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self._client = client

    def _headers(self) -> dict[str, str]:
        if self.settings.dashscope_api_key is None:
            raise DashScopeImageError(
                "DashScope API key is not configured",
                code="not_configured",
                retryable=False,
            )
        return {
            "Authorization": f"Bearer {self.settings.dashscope_api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            base_url=self.settings.dashscope_api_base,
            timeout=httpx.Timeout(180.0, connect=15.0),
        )
        try:
            response = await client.request(method, path, headers=self._headers(), **kwargs)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise DashScopeImageError(
                "DashScope request failed due to a network timeout",
                code="network_error",
                retryable=True,
            ) from exc
        finally:
            if owns_client:
                await client.aclose()
        if response.status_code == 429:
            raise DashScopeImageError(
                "DashScope rate limit reached (qwen-image-3.0-pro is 1 RPM)",
                code="rate_limited",
                retryable=True,
            )
        if response.status_code in {401, 403}:
            raise DashScopeImageError(
                "DashScope authentication failed",
                code="authentication_failed",
                retryable=False,
            )
        if response.status_code >= 500:
            raise DashScopeImageError(
                "DashScope image service is temporarily unavailable",
                code="service_unavailable",
                retryable=True,
            )
        if response.is_error:
            detail = response.text[:200]
            raise DashScopeImageError(
                f"DashScope image request failed with HTTP {response.status_code}: {detail}",
                code="request_failed",
                retryable=False,
            )
        return response

    async def generate(self, prompt: str, *, image_size: str | None = None) -> GeneratedImage:
        payload = {
            "model": self.settings.dashscope_image_model,
            "input": {
                "messages": [{"role": "user", "content": [{"text": prompt}]}]
            },
            "parameters": {
                "prompt_extend": True,
                "n": 1,
                "size": image_size or self.settings.dashscope_image_size,
            },
        }
        response = await self._request(
            "POST", self.GENERATION_PATH, json=payload
        )
        data = response.json()
        choices = ((data.get("output") or {}).get("choices")) or []
        content = ((choices[0] or {}).get("message") or {}).get("content") or []
        image = next((item.get("image") for item in content if item.get("image")), None)
        if not image:
            raise DashScopeImageError(
                f"DashScope returned no image: {str(data)[:200]}",
                code="empty_result",
                retryable=True,
            )
        match = self._DATA_URI.match(image)
        if match:
            try:
                body = base64.b64decode(match.group(2))
            except (ValueError, base64.binascii.Error) as exc:
                raise DashScopeImageError(
                    "DashScope returned invalid base64 image data",
                    code="invalid_output",
                    retryable=False,
                ) from exc
            return GeneratedImage(
                url="",
                model=self.settings.dashscope_image_model,
                image_bytes=body,
                content_type=f"image/{match.group(1).lower()}",
            )
        return GeneratedImage(url=image, model=self.settings.dashscope_image_model)
