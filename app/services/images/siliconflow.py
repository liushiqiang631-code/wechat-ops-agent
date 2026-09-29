from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from app.config.settings import Settings


class SiliconFlowImageError(RuntimeError):
    def __init__(self, message: str, *, code: str, retryable: bool):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(slots=True)
class GeneratedImage:
    url: str
    model: str
    seed: int | None = None
    fallback_used: bool = False
    # Some providers (e.g. DashScope) return base64-encoded bytes directly;
    # when set, the materializer writes them locally instead of downloading.
    image_bytes: bytes | None = None
    content_type: str | None = None


class SiliconFlowImageClient:
    """Text-to-image client for SiliconFlow (OpenAI-compatible image API).

    The configured model id (default ``Tongyi-MAI/Z-Image-Turbo``) is probed
    against the live ``/models`` endpoint. When the exact id is unavailable,
    the client falls back to the best available Qwen image model
    (``Qwen/Qwen-Image``) and reports the fallback in the result so evidence
    stays honest.
    """

    provider_name = "siliconflow"
    MODEL_PROBE_TTL_SECONDS = 600.0
    DEFAULT_SIZE = "1024x1024"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self._client = client
        self._model_probe: tuple[float, str, bool] | None = None

    def _headers(self) -> dict[str, str]:
        if self.settings.siliconflow_api_key is None:
            raise SiliconFlowImageError(
                "SiliconFlow API key is not configured",
                code="not_configured",
                retryable=False,
            )
        return {
            "Authorization": f"Bearer {self.settings.siliconflow_api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            base_url=self.settings.siliconflow_api_base,
            timeout=httpx.Timeout(120.0, connect=15.0),
        )
        try:
            response = await client.request(method, path, headers=self._headers(), **kwargs)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise SiliconFlowImageError(
                "SiliconFlow request failed due to a network timeout",
                code="network_error",
                retryable=True,
            ) from exc
        finally:
            if owns_client:
                await client.aclose()
        if response.status_code == 429:
            raise SiliconFlowImageError(
                "SiliconFlow rate limit reached",
                code="rate_limited",
                retryable=True,
            )
        if response.status_code in {401, 403}:
            raise SiliconFlowImageError(
                "SiliconFlow authentication failed",
                code="authentication_failed",
                retryable=False,
            )
        if response.status_code >= 500:
            raise SiliconFlowImageError(
                "SiliconFlow image service is temporarily unavailable",
                code="service_unavailable",
                retryable=True,
            )
        if response.is_error:
            raise SiliconFlowImageError(
                f"SiliconFlow image request failed with HTTP {response.status_code}",
                code="request_failed",
                retryable=False,
            )
        return response

    async def _available_models(self) -> list[str]:
        response = await self._request("GET", "/models")
        data = response.json().get("data", [])
        return [item.get("id") for item in data if isinstance(item, dict) and item.get("id")]

    async def resolve_model(self) -> tuple[str, bool]:
        """Return ``(model_id, fallback_used)`` for image generation."""
        now = time.monotonic()
        if (
            self._model_probe is not None
            and now - self._model_probe[0] < self.MODEL_PROBE_TTL_SECONDS
        ):
            return self._model_probe[1], self._model_probe[2]
        models = await self._available_models()
        configured = self.settings.siliconflow_image_model
        if configured in models:
            resolved: tuple[str, bool] = (configured, False)
        elif "Qwen/Qwen-Image" in models:
            resolved = ("Qwen/Qwen-Image", True)
        else:
            raise SiliconFlowImageError(
                f"no usable SiliconFlow image model; {configured!r} is unavailable",
                code="model_unavailable",
                retryable=False,
            )
        self._model_probe = (now, *resolved)
        return resolved

    async def generate(self, prompt: str, *, image_size: str = DEFAULT_SIZE) -> GeneratedImage:
        model, fallback_used = await self.resolve_model()
        payload = {
            "model": model,
            "prompt": prompt,
            "image_size": image_size,
            "batch_size": 1,
            "num_inference_steps": 20,
            "guidance_scale": 7.5,
            "output_format": "png",
        }
        response = await self._request("POST", "/images/generations", json=payload)
        data = response.json()
        images = data.get("images") or []
        if not images or not images[0].get("url"):
            raise SiliconFlowImageError(
                f"SiliconFlow returned no image url: {data}",
                code="empty_result",
                retryable=True,
            )
        return GeneratedImage(
            url=images[0]["url"],
            model=model,
            seed=data.get("seed"),
            fallback_used=fallback_used,
        )
