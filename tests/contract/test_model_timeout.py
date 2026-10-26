from __future__ import annotations

import httpx
import pytest
import respx
from pydantic import BaseModel, ValidationError

from app.config.settings import Settings
from app.services.models.deepseek import DeepSeekClient, ModelServiceError


class TimeoutOutput(BaseModel):
    answer: str


@respx.mock
@pytest.mark.asyncio
async def test_default_timeout_allows_slow_reasoning_response():
    def upstream(request: httpx.Request) -> httpx.Response:
        # Replay a 120-second upstream stall without sleeping or making a paid call.
        timeout = request.extensions["timeout"]
        if timeout["read"] < 120:
            raise httpx.ReadTimeout("reasoning response exceeds read timeout", request=request)
        assert timeout["connect"] == 15.0
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"answer":"ok"}'}}]}
        )

    respx.post("https://api.deepseek.com/chat/completions").mock(side_effect=upstream)
    client = DeepSeekClient(Settings(_env_file=None, deepseek_api_key="test-key"))
    result = await client.generate_structured(
        system="Return JSON.", user="health", response_model=TimeoutOutput
    )
    assert result.data.answer == "ok"


@respx.mock
@pytest.mark.asyncio
async def test_read_timeout_uses_environment_setting(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TEXT_MODEL_READ_TIMEOUT", "420")

    def upstream(request: httpx.Request) -> httpx.Response:
        assert request.extensions["timeout"]["read"] == 420.0
        assert request.extensions["timeout"]["connect"] == 15.0
        raise httpx.ReadTimeout("simulated timeout", request=request)

    respx.post("https://api.deepseek.com/chat/completions").mock(side_effect=upstream)
    client = DeepSeekClient(Settings(_env_file=None, deepseek_api_key="test-key"))
    with pytest.raises(ModelServiceError) as captured:
        await client.generate_structured(
            system="Return JSON.", user="health", response_model=TimeoutOutput
        )
    assert captured.value.retryable is True
    assert captured.value.code == "network_error"
    assert isinstance(captured.value.__cause__, httpx.ReadTimeout)


@pytest.mark.parametrize("value", [0, -1, 1801])
def test_read_timeout_rejects_out_of_bounds(value: float):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, text_model_read_timeout=value)
