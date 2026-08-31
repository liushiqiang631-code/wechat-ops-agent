from __future__ import annotations

import json

import httpx
import pytest
import respx
from pydantic import BaseModel

from app.config.settings import Settings
from app.services.models.deepseek import DeepSeekClient, ModelServiceError


class TinyOutput(BaseModel):
    answer: str


@pytest.fixture
def client() -> DeepSeekClient:
    settings = Settings(_env_file=None, deepseek_api_key="test-key")
    return DeepSeekClient(settings)


@respx.mock
@pytest.mark.asyncio
async def test_lists_official_v4_models(client: DeepSeekClient):
    respx.get("https://api.deepseek.com/models").mock(
        return_value=httpx.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {"id": "deepseek-v4-flash", "object": "model", "owned_by": "deepseek"},
                    {"id": "deepseek-v4-pro", "object": "model", "owned_by": "deepseek"},
                ],
            },
        )
    )

    models = await client.list_models()

    assert "deepseek-v4-pro" in models


@respx.mock
@pytest.mark.asyncio
async def test_structured_generation_uses_v4_pro_thinking_mode(client: DeepSeekClient):
    route = respx.post("https://api.deepseek.com/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"answer":"ok"}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            },
        )
    )

    result = await client.generate_structured(
        system="Return JSON.",
        user="health",
        response_model=TinyOutput,
    )

    request = route.calls[0].request
    payload = httpx.Request("POST", "https://example.invalid", content=request.content).content
    assert b'"model":"deepseek-v4-pro"' in payload
    assert b'"type":"enabled"' in payload
    assert result.data.answer == "ok"
    assert result.usage.total_tokens == 12


@respx.mock
@pytest.mark.asyncio
async def test_malformed_json_is_repaired_once(client: DeepSeekClient):
    route = respx.post("https://api.deepseek.com/chat/completions")
    route.side_effect = [
        httpx.Response(200, json={"choices": [{"message": {"content": "not-json"}}]}),
        httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"answer":"repaired"}'}}]},
        ),
    ]

    result = await client.generate_structured(
        system="Return JSON.",
        user="repair",
        response_model=TinyOutput,
    )

    assert result.data.answer == "repaired"
    assert len(route.calls) == 2


@respx.mock
@pytest.mark.asyncio
async def test_invalid_structured_output_keeps_the_last_raw_response(client: DeepSeekClient):
    route = respx.post("https://api.deepseek.com/chat/completions")
    route.side_effect = [
        httpx.Response(200, json={"choices": [{"message": {"content": "not-json"}}]}),
        httpx.Response(200, json={"choices": [{"message": {"content": "still-not-json"}}]}),
    ]

    with pytest.raises(ModelServiceError) as captured:
        await client.generate_structured(
            system="Return JSON.",
            user="repair",
            response_model=TinyOutput,
        )

    assert captured.value.code == "invalid_output"
    assert captured.value.raw_output == "still-not-json"


@pytest.mark.asyncio
async def test_reserved_writing_tokens_limit_research_stage_completion_budget(
    client: DeepSeekClient,
):
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"answer":"ok"}'}}],
                "usage": {"total_tokens": 1},
            },
        )

    transport = httpx.MockTransport(handler)
    fake_client = httpx.AsyncClient(
        base_url="https://api.deepseek.com", transport=transport
    )
    reserved = DeepSeekClient(
        Settings(_env_file=None, deepseek_api_key="test-key", max_total_tokens=10_000),
        client=fake_client,
    )
    scope = reserved.begin_token_budget()
    try:
        reserved.reserve_token_budget(7_000)
        await reserved.generate_structured(
            system="Return JSON.", user="x" * 100, response_model=TinyOutput
        )
    finally:
        reserved.end_token_budget(scope)
        await fake_client.aclose()

    assert json.loads(captured[0].content)["max_tokens"] < 3_000


def test_budget_preflight_rejects_a_task_that_cannot_reserve_writing_capacity():
    client = DeepSeekClient(
        Settings(_env_file=None, deepseek_api_key="test-key", max_total_tokens=20_000)
    )

    with pytest.raises(ModelServiceError, match="configured task budget") as captured:
        client.assert_task_budget(target_words=2_500, source_count=13, revision_rounds=2)

    assert captured.value.code == "task_budget_insufficient"


@respx.mock
@pytest.mark.asyncio
async def test_rate_limit_is_retryable_and_never_leaks_key(client: DeepSeekClient):
    respx.post("https://api.deepseek.com/chat/completions").mock(
        return_value=httpx.Response(429, json={"error": {"message": "rate limited"}})
    )

    with pytest.raises(ModelServiceError) as captured:
        await client.generate_structured(
            system="Return JSON.",
            user="limit",
            response_model=TinyOutput,
        )

    assert captured.value.retryable is True
    assert captured.value.code == "rate_limited"
    assert "test-key" not in str(captured.value)


@pytest.mark.asyncio
async def test_owned_client_does_not_implicitly_inherit_proxy_environment(
    monkeypatch: pytest.MonkeyPatch,
    client: DeepSeekClient,
):
    captured: dict[str, object] = {}

    class FakeAsyncClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        async def request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
            return httpx.Response(200, json={"data": []})

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr("app.services.models.deepseek.httpx.AsyncClient", FakeAsyncClient)

    assert await client.list_models() == []
    assert captured["trust_env"] is False
