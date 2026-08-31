from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from app.config.settings import Settings
from app.services.wechat.client import WeChatAPIError, WeChatClient
from app.services.wechat.token_manager import TokenManager


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        wechat_app_id="wx-test",
        wechat_app_secret="wx-secret",
    )


@respx.mock
@pytest.mark.asyncio
async def test_token_manager_fetches_once_and_caches(settings: Settings):
    route = respx.get("https://api.weixin.qq.com/cgi-bin/token").mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "token-1", "expires_in": 7200},
        )
    )
    manager = TokenManager(WeChatClient(settings), settings)

    first = await manager.get()
    second = await manager.get()

    assert first == "token-1"
    assert second == "token-1"
    assert len(route.calls) == 1


@respx.mock
@pytest.mark.asyncio
async def test_ip_whitelist_error_is_classified_without_secret(settings: Settings):
    respx.get("https://api.weixin.qq.com/cgi-bin/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "errcode": 40164,
                "errmsg": "invalid ip 203.0.113.10, not in whitelist",
            },
        )
    )
    manager = TokenManager(WeChatClient(settings), settings)

    with pytest.raises(WeChatAPIError) as captured:
        await manager.get()

    assert captured.value.category == "ip_whitelist"
    assert captured.value.retryable is False
    assert "wx-secret" not in str(captured.value)


@respx.mock
@pytest.mark.asyncio
async def test_client_maps_no_permission_and_rate_limit(settings: Settings):
    client = WeChatClient(settings)
    permission_route = respx.post("https://api.weixin.qq.com/datacube/getusersummary").mock(
        return_value=httpx.Response(200, json={"errcode": 48001, "errmsg": "api unauthorized"})
    )
    rate_route = respx.post("https://api.weixin.qq.com/cgi-bin/draft/add").mock(
        return_value=httpx.Response(
            200, json={"errcode": 45009, "errmsg": "reach max api daily quota"}
        )
    )

    with pytest.raises(WeChatAPIError) as permission:
        await client.request_json(
            "POST",
            "/datacube/getusersummary",
            params={"access_token": "token"},
            json={"begin_date": "2026-07-17", "end_date": "2026-07-17"},
        )
    with pytest.raises(WeChatAPIError) as rate:
        await client.request_json(
            "POST",
            "/cgi-bin/draft/add",
            params={"access_token": "token"},
            json={"articles": []},
        )

    assert permission.value.category == "no_permission"
    assert permission.value.retryable is False
    assert rate.value.category == "rate_limit"
    assert rate.value.retryable is True
    assert permission_route.called and rate_route.called


@respx.mock
@pytest.mark.asyncio
async def test_media_and_draft_requests_use_expected_endpoints(settings: Settings, tmp_path: Path):
    from app.services.wechat.draft_service import DraftService
    from app.services.wechat.media_uploader import MediaUploader

    image = tmp_path / "probe.png"
    image.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\rIDAT\x08\xd7c\xf8\xff\xff?\x00\x05\xfe\x02\xfeA\x89\x89\x9b"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    respx.post("https://api.weixin.qq.com/cgi-bin/media/uploadimg").mock(
        return_value=httpx.Response(200, json={"url": "https://mmbiz.qpic.cn/probe.png"})
    )
    respx.post("https://api.weixin.qq.com/cgi-bin/material/add_material").mock(
        return_value=httpx.Response(200, json={"media_id": "thumb-1"})
    )
    draft_route = respx.post("https://api.weixin.qq.com/cgi-bin/draft/add").mock(
        return_value=httpx.Response(200, json={"media_id": "draft-1"})
    )
    client = WeChatClient(settings)
    media = MediaUploader(client)

    image_url = await media.upload_inline("token", image)
    thumb = await media.upload_cover("token", image)
    media_id = await DraftService(client).create(
        "token",
        {
            "title": "接口测试，请勿发布",
            "author": "示例技术观察站",
            "digest": "V0 能力验证",
            "content": "<p>接口测试，请勿发布。</p>",
            "thumb_media_id": thumb,
        },
    )

    assert image_url.startswith("https://mmbiz.qpic.cn/")
    assert thumb == "thumb-1"
    assert media_id == "draft-1"
    assert "接口测试" in draft_route.calls[0].request.content.decode("utf-8")
