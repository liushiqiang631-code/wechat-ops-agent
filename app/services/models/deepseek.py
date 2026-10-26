from __future__ import annotations

import asyncio
import json
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config.settings import Settings

T = TypeVar("T", bound=BaseModel)
_TASK_TOKEN_USAGE: ContextVar[int] = ContextVar("deepseek_task_token_usage", default=0)
_TASK_TOKEN_RESERVE: ContextVar[int] = ContextVar("deepseek_task_token_reserve", default=0)


@dataclass(slots=True)
class TokenBudgetScope:
    usage_token: Token[int]
    reserve_token: Token[int]


class ModelServiceError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        retryable: bool,
        raw_output: str | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.raw_output = raw_output


@dataclass(slots=True)
class ModelUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass(slots=True)
class ModelResult[T]:
    data: T
    usage: ModelUsage
    model: str


class DeepSeekClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self._client = client

    def begin_token_budget(self) -> TokenBudgetScope:
        return TokenBudgetScope(
            usage_token=_TASK_TOKEN_USAGE.set(0),
            reserve_token=_TASK_TOKEN_RESERVE.set(0),
        )

    @staticmethod
    def end_token_budget(scope: TokenBudgetScope) -> None:
        _TASK_TOKEN_RESERVE.reset(scope.reserve_token)
        _TASK_TOKEN_USAGE.reset(scope.usage_token)

    @staticmethod
    def reserve_token_budget(tokens: int) -> None:
        _TASK_TOKEN_RESERVE.set(max(0, tokens))

    def assert_task_budget(
        self, *, target_words: int, source_count: int, revision_rounds: int
    ) -> None:
        """Reject infeasible content tasks before they spend model tokens.

        This is deliberately a conservative lower-bound estimate, not an
        accounting replacement. It protects one complete draft and every
        configured automatic revision from research/outline calls consuming
        the entire task allowance first.
        """
        draft_tokens = max(8_000, target_words * 3)
        required = 7_000 + 7_000 + source_count * 750 + draft_tokens * (1 + revision_rounds)
        if required > self.settings.max_total_tokens:
            raise ModelServiceError(
                "The configured task budget cannot reserve research, planning, "
                "and writing capacity",
                code="task_budget_insufficient",
                retryable=False,
            )

    def _headers(self) -> dict[str, str]:
        if self.settings.deepseek_api_key is None:
            raise ModelServiceError(
                "DeepSeek API key is not configured",
                code="not_configured",
                retryable=False,
            )
        return {
            "Authorization": f"Bearer {self.settings.deepseek_api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }

    async def _request(
        self, method: str, path: str, *, streaming: bool = False, **kwargs
    ) -> httpx.Response:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            base_url=self.settings.deepseek_api_base,
            timeout=httpx.Timeout(90.0, connect=15.0, read=self.settings.text_model_read_timeout),
            trust_env=False,
        )
        try:
            if streaming:
                async with asyncio.timeout(self.settings.text_model_request_timeout):
                    async with client.stream(
                        method, path, headers=self._headers(), **kwargs
                    ) as response:
                        self._check_response(response)
                        body = await self._collect_stream(response)
                        return httpx.Response(200, json=body, request=response.request)
            async with asyncio.timeout(self.settings.text_model_request_timeout):
                response = await client.request(method, path, headers=self._headers(), **kwargs)
        except (TimeoutError, httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ModelServiceError(
                "DeepSeek request failed due to a network timeout",
                code="network_error",
                retryable=True,
            ) from exc
        finally:
            if owns_client:
                await client.aclose()
        self._check_response(response)
        return response

    @staticmethod
    def _check_response(response: httpx.Response) -> None:
        if response.status_code == 429:
            raise ModelServiceError(
                "DeepSeek rate limit reached",
                code="rate_limited",
                retryable=True,
            )
        if response.status_code in {401, 403}:
            raise ModelServiceError(
                "DeepSeek authentication failed",
                code="authentication_failed",
                retryable=False,
            )
        if response.status_code >= 500:
            raise ModelServiceError(
                "DeepSeek service is temporarily unavailable",
                code="service_unavailable",
                retryable=True,
            )
        if response.is_error:
            raise ModelServiceError(
                f"DeepSeek request failed with HTTP {response.status_code}",
                code="request_failed",
                retryable=False,
            )

    @staticmethod
    async def _collect_stream(response: httpx.Response) -> dict:
        content: list[str] = []
        usage: dict = {}
        finished = False
        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                finished = True
                break
            try:
                event = json.loads(data)
            except json.JSONDecodeError as exc:
                raise ModelServiceError(
                    "Model returned an invalid stream event",
                    code="invalid_stream", retryable=True,
                ) from exc
            if event.get("error"):
                raise ModelServiceError(
                    "Model stream reported an upstream error",
                    code="service_unavailable", retryable=True,
                )
            if event.get("usage"):
                usage = event["usage"]
            for choice in event.get("choices", []):
                if choice.get("index", 0) == 0:
                    # Reasoning deltas keep the connection active but are not article text.
                    text = choice.get("delta", {}).get("content")
                    if text:
                        content.append(text)
        if not finished:
            raise ModelServiceError(
                "Model stream disconnected before completion; partial output was not saved",
                code="incomplete_stream", retryable=True,
            )
        return {"choices": [{"message": {"content": "".join(content)}}], "usage": usage}

    async def list_models(self) -> list[str]:
        response = await self._request("GET", "/models")
        return [item["id"] for item in response.json().get("data", []) if "id" in item]

    @staticmethod
    def _content_to_json(content: str) -> object:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            cleaned = cleaned.rsplit("```", 1)[0].strip()
        return json.loads(cleaned)

    async def _chat(
        self, messages: list[dict[str, str]], *, max_output_tokens: int | None = None
    ) -> dict:
        remaining = (
            self.settings.max_total_tokens
            - _TASK_TOKEN_USAGE.get()
            - _TASK_TOKEN_RESERVE.get()
        )
        estimated_prompt_tokens = sum(len(message.get("content", "")) for message in messages)
        max_completion_tokens = min(
            self.settings.deepseek_max_output_tokens,
            max_output_tokens or self.settings.deepseek_max_output_tokens,
            remaining - estimated_prompt_tokens,
        )
        if max_completion_tokens < 256:
            raise ModelServiceError(
                "Task token budget is exhausted",
                code="token_budget_exceeded",
                retryable=False,
            )
        payload = {
            "model": self.settings.deepseek_model,
            "messages": messages,
            "stream": self.settings.text_model_streaming_enabled,
            "response_format": {"type": "json_object"},
            "thinking": {
                "type": "enabled" if self.settings.deepseek_thinking_enabled else "disabled"
            },
            "reasoning_effort": self.settings.deepseek_reasoning_effort,
            "max_tokens": max_completion_tokens,
        }
        if self.settings.text_model_streaming_enabled:
            payload["stream_options"] = {"include_usage": True}
        for attempt in range(2):
            try:
                response = await self._request(
                    "POST", "/chat/completions", json=payload,
                    streaming=self.settings.text_model_streaming_enabled,
                )
                break
            except ModelServiceError as error:
                if attempt or error.code not in {"network_error", "incomplete_stream"}:
                    raise
        body = response.json()
        used = int(body.get("usage", {}).get("total_tokens", 0) or 0)
        total = _TASK_TOKEN_USAGE.get() + used
        _TASK_TOKEN_USAGE.set(total)
        if total > self.settings.max_total_tokens:
            raise ModelServiceError(
                "Task token budget was exceeded by the last model response",
                code="token_budget_exceeded",
                retryable=False,
            )
        return body

    async def generate_structured(
        self,
        *,
        system: str,
        user: str,
        response_model: type[T],
    ) -> ModelResult[T]:
        schema = json.dumps(response_model.model_json_schema(), ensure_ascii=False)
        messages = [
            {
                "role": "system",
                "content": (
                    f"{system}\nReturn exactly one JSON object matching this schema:\n{schema}"
                ),
            },
            {"role": "user", "content": user},
        ]
        output_limit = {
            "ResearchPack": 4096,
            "EditorialBlueprint": 4096,
            "ReviewReport": 4096,
            "VisualPlan": 4096,
            "ArticleSupplement": 4096,
        }.get(response_model.__name__)
        response = await self._chat(messages, max_output_tokens=output_limit)
        try:
            raw = self._content_to_json(response["choices"][0]["message"]["content"])
            parsed = response_model.model_validate(raw)
        except (KeyError, IndexError, json.JSONDecodeError, ValidationError) as validation_error:
            # Give the model its own failed output so the repair turn can correct
            # the specific format problem instead of repeating it.
            raw_failed = response.get("choices", [{}])[0].get("message", {}).get("content") or ""
            details = (
                json.dumps(validation_error.errors(
                    include_input=False, include_context=False, include_url=False,
                ), ensure_ascii=False)
                if isinstance(validation_error, ValidationError)
                else str(validation_error)
            )
            messages.extend(
                [
                    {"role": "assistant", "content": raw_failed},
                    {
                        "role": "user",
                        "content": (
                            "The previous output was invalid. Return only corrected JSON. "
                            "Fix these validation errors without changing supported facts:\n"
                            + details[:6000]
                        ),
                    },
                ]
            )
            response = await self._chat(messages, max_output_tokens=output_limit)
            try:
                raw = self._content_to_json(response["choices"][0]["message"]["content"])
                parsed = response_model.model_validate(raw)
            except (KeyError, IndexError, json.JSONDecodeError, ValidationError) as exc:
                raise ModelServiceError(
                    f"Model returned invalid {response_model.__name__} structured output "
                    "after one repair",
                    code="invalid_output",
                    retryable=True,
                    raw_output=(
                        response.get("choices", [{}])[0].get("message", {}).get("content")
                        or None
                    ),
                ) from exc
        usage_payload = response.get("usage", {})
        usage = ModelUsage(
            prompt_tokens=usage_payload.get("prompt_tokens", 0),
            completion_tokens=usage_payload.get("completion_tokens", 0),
            total_tokens=usage_payload.get("total_tokens", 0),
        )
        return ModelResult(data=parsed, usage=usage, model=self.settings.deepseek_model)

    async def health_probe(self) -> dict[str, object]:
        models = await self.list_models()
        return {
            "provider": "deepseek",
            "model": self.settings.deepseek_model,
            "available": self.settings.deepseek_model in models,
            "models": models,
        }
