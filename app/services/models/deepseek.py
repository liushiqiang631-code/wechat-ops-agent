from __future__ import annotations

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

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            base_url=self.settings.deepseek_api_base,
            timeout=httpx.Timeout(90.0, connect=15.0),
            trust_env=False,
        )
        try:
            response = await client.request(
                method,
                path,
                headers=self._headers(),
                **kwargs,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ModelServiceError(
                "DeepSeek request failed due to a network timeout",
                code="network_error",
                retryable=True,
            ) from exc
        finally:
            if owns_client:
                await client.aclose()
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
        return response

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

    async def _chat(self, messages: list[dict[str, str]]) -> dict:
        remaining = (
            self.settings.max_total_tokens
            - _TASK_TOKEN_USAGE.get()
            - _TASK_TOKEN_RESERVE.get()
        )
        estimated_prompt_tokens = sum(len(message.get("content", "")) for message in messages)
        max_completion_tokens = min(
            self.settings.deepseek_max_output_tokens, remaining - estimated_prompt_tokens
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
            "stream": False,
            "response_format": {"type": "json_object"},
            "thinking": {
                "type": "enabled" if self.settings.deepseek_thinking_enabled else "disabled"
            },
            "reasoning_effort": self.settings.deepseek_reasoning_effort,
            "max_tokens": max_completion_tokens,
        }
        response = await self._request("POST", "/chat/completions", json=payload)
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
        response = await self._chat(messages)
        try:
            raw = self._content_to_json(response["choices"][0]["message"]["content"])
            parsed = response_model.model_validate(raw)
        except (KeyError, IndexError, json.JSONDecodeError, ValidationError):
            # Give the model its own failed output so the repair turn can correct
            # the specific format problem instead of repeating it.
            raw_failed = response.get("choices", [{}])[0].get("message", {}).get("content") or ""
            messages.extend(
                [
                    {"role": "assistant", "content": raw_failed},
                    {
                        "role": "user",
                        "content": "The previous output was invalid. Return only corrected JSON.",
                    },
                ]
            )
            response = await self._chat(messages)
            try:
                raw = self._content_to_json(response["choices"][0]["message"]["content"])
                parsed = response_model.model_validate(raw)
            except (KeyError, IndexError, json.JSONDecodeError, ValidationError) as exc:
                raise ModelServiceError(
                    "DeepSeek returned invalid structured output after one repair",
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
