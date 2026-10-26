from __future__ import annotations

import asyncio
import json

import httpx
import pytest
import respx
from pydantic import BaseModel

from app.config.settings import Settings
from app.services.models.deepseek import DeepSeekClient, ModelServiceError


class Output(BaseModel):
    answer: str


class Events(httpx.AsyncByteStream):
    def __init__(self, *, complete=True):
        self.complete = complete

    async def __aiter__(self):
        yield b': heartbeat\n\n'
        for event in [
            {"choices": [{"delta": {"reasoning_content": "private reasoning"}}]},
            {"choices": [{"delta": {"content": '{"answer":'}}]},
            {"choices": [{"delta": {"content": '"完整正文"}'}}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
            {"choices": [], "usage": {"total_tokens": 42, "completion_tokens": 12}},
        ]:
            yield ("data: " + json.dumps(event, ensure_ascii=False) + "\n\n").encode()
        if self.complete:
            yield b'data: [DONE]\n\n'


def streaming_client():
    return DeepSeekClient(Settings(
        _env_file=None, deepseek_api_key="test-key", text_model_streaming_enabled=True,
    ))


@respx.mock
@pytest.mark.asyncio
async def test_long_generation_receives_chunks_instead_of_waiting_for_full_body():
    def upstream(request):
        if not json.loads(request.content)["stream"]:
            raise httpx.ReadTimeout("long article exceeds 300 seconds", request=request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Events())

    respx.post("https://api.deepseek.com/chat/completions").mock(side_effect=upstream)
    result = await streaming_client().generate_structured(
        system="Return JSON", user="long article", response_model=Output,
    )
    assert result.data.answer == "完整正文"
    assert result.usage.total_tokens == 42
    assert result.usage.completion_tokens == 12


@respx.mock
@pytest.mark.asyncio
async def test_disconnected_stream_is_not_accepted_as_a_complete_article():
    respx.post("https://api.deepseek.com/chat/completions").mock(return_value=httpx.Response(
        200, headers={"content-type": "text/event-stream"}, stream=Events(complete=False),
    ))
    with pytest.raises(ModelServiceError) as caught:
        await streaming_client().generate_structured(
            system="Return JSON", user="article", response_model=Output,
        )
    assert caught.value.code == "incomplete_stream"
    assert caught.value.retryable is True


@respx.mock
@pytest.mark.asyncio
async def test_streaming_http_error_remains_actionable_without_exposing_secrets():
    respx.post("https://api.deepseek.com/chat/completions").mock(return_value=httpx.Response(
        401, json={"error": "test-key"},
    ))
    with pytest.raises(ModelServiceError) as caught:
        await streaming_client().generate_structured(
            system="Return JSON", user="article", response_model=Output,
        )
    assert caught.value.code == "authentication_failed"
    assert "test-key" not in str(caught.value)


@respx.mock
@pytest.mark.asyncio
async def test_schema_repair_receives_the_specific_missing_field():
    requests = []

    def upstream(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            return httpx.Response(200, json={"choices": [{"message": {"content": '{}'}}]})
        repair = payload["messages"][-1]["content"]
        assert 'answer' in repair
        assert 'missing' in repair.lower()
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"answer":"ok"}'}}]})

    respx.post("https://api.deepseek.com/chat/completions").mock(side_effect=upstream)
    client = DeepSeekClient(Settings(_env_file=None, deepseek_api_key="test-key"))
    result = await client.generate_structured(
        system="Return JSON", user="article", response_model=Output,
    )
    assert result.data.answer == "ok"
    assert len(requests) == 2


@respx.mock
@pytest.mark.asyncio
async def test_heartbeat_only_stream_has_whole_request_deadline_and_one_retry():
    class Heartbeats(httpx.AsyncByteStream):
        async def __aiter__(self):
            while True:
                yield b': heartbeat\n\n'
                await asyncio.sleep(0.005)

    attempts = []

    def upstream(request):
        attempts.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              stream=Heartbeats() if len(attempts) == 1 else Events())

    respx.post("https://api.deepseek.com/chat/completions").mock(side_effect=upstream)
    client = streaming_client()
    client.settings = client.settings.model_copy(update={"text_model_request_timeout": 0.02})
    result = await client.generate_structured(
        system="Return JSON", user="article", response_model=Output,
    )
    assert result.data.answer == "完整正文"
    assert len(attempts) == 2
