from __future__ import annotations

import base64

import httpx
import pytest
import respx

from app.config.settings import Settings
from app.services.images.dashscope import DashScopeImageClient, DashScopeImageError

BASE = "https://dashscope.aliyuncs.com/api/v1"
PATH = f"{BASE}/services/aigc/multimodal-generation/generation"


def settings_with_key() -> Settings:
    return Settings(
        _env_file=None,
        image_model_provider="dashscope",
        dashscope_api_key="dashscope-secret",
        dashscope_api_base=BASE,
        dashscope_image_model="qwen-image-3.0-pro",
    )


def url_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "output": {
                "choices": [
                    {
                        "message": {
                            "content": [{"image": "https://dashscope-result.example/img.png"}]
                        }
                    }
                ]
            },
            "request_id": "req-1",
        },
    )


@respx.mock
@pytest.mark.asyncio
async def test_dashscope_generate_posts_native_payload_and_returns_url():
    route = respx.post(PATH).mock(return_value=url_response())
    client = DashScopeImageClient(settings_with_key())

    result = await client.generate("一个 Agent 架构示意图")

    assert result.url == "https://dashscope-result.example/img.png"
    assert result.image_bytes is None
    request = route.calls[0].request
    assert b'"model":"qwen-image-3.0-pro"' in request.content
    assert '"一个 Agent 架构示意图"'.encode() in request.content
    assert b'"size":"1024*1024"' in request.content
    assert b"dashscope-secret" not in request.content


@respx.mock
@pytest.mark.asyncio
async def test_dashscope_generate_decodes_base64_image():
    png = b"\x89PNG\r\n\x1a\nfake-png"
    data_uri = f"data:image/png;base64,{base64.b64encode(png).decode()}"
    respx.post(PATH).mock(
        return_value=httpx.Response(
            200,
            json={
                "output": {
                    "choices": [{"message": {"content": [{"image": data_uri}]}}]
                }
            },
        )
    )
    client = DashScopeImageClient(settings_with_key())

    result = await client.generate("prompt")

    assert result.image_bytes == png
    assert result.content_type == "image/png"
    assert result.url == ""


@respx.mock
@pytest.mark.asyncio
async def test_dashscope_auth_failure_is_not_retryable_and_never_leaks_key():
    respx.post(PATH).mock(return_value=httpx.Response(401, text="InvalidApiKey"))
    client = DashScopeImageClient(settings_with_key())

    with pytest.raises(DashScopeImageError) as captured:
        await client.generate("prompt")

    assert captured.value.code == "authentication_failed"
    assert captured.value.retryable is False
    assert "dashscope-secret" not in str(captured.value)


@respx.mock
@pytest.mark.asyncio
async def test_dashscope_rate_limit_is_retryable():
    respx.post(PATH).mock(return_value=httpx.Response(429, json={"code": "Throttling"}))
    client = DashScopeImageClient(settings_with_key())

    with pytest.raises(DashScopeImageError) as captured:
        await client.generate("prompt")

    assert captured.value.code == "rate_limited"
    assert captured.value.retryable is True


def test_dashscope_without_key_raises_not_configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    settings = Settings(_env_file=None, image_model_provider="dashscope")
    client = DashScopeImageClient(settings)

    with pytest.raises(DashScopeImageError) as captured:
        client._headers()

    assert captured.value.code == "not_configured"
