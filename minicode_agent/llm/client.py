from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any, Protocol, Sequence

from minicode_agent.config import ModelConfig
from minicode_agent.llm.types import ModelResponse, ToolCall


class ModelError(RuntimeError):
    """A provider or protocol error safe to show to the user."""


class LLMClient(Protocol):
    def complete(
        self,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
    ) -> ModelResponse: ...


class OpenAICompatibleClient:
    """Adapter for Qwen DashScope and other OpenAI-compatible chat APIs."""

    def __init__(
        self,
        config: ModelConfig,
        credential_provider: Callable[[], str | None] | None = None,
    ) -> None:
        self.config = config
        self.credential_provider = credential_provider
        self._client: Any | None = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        api_key = self.credential_provider() if self.credential_provider else None
        api_key = api_key or os.getenv(self.config.api_key_env)
        if not api_key:
            raise ModelError(
                f"missing API credential: set environment variable {self.config.api_key_env}"
            )
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ModelError("the 'openai' package is not installed") from exc
        kwargs: dict[str, Any] = {
            "api_key": api_key,
            "timeout": self.config.request_timeout,
            "max_retries": 0,
        }
        if self.config.base_url:
            kwargs["base_url"] = self.config.base_url
        self._client = OpenAI(**kwargs)
        return self._client

    def complete(
        self,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
    ) -> ModelResponse:
        try:
            response = self._get_client().chat.completions.create(
                model=self.config.model,
                messages=list(messages),
                tools=list(tools) or None,
                tool_choice="auto" if tools else None,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            )
        except ModelError:
            raise
        except Exception as exc:
            raise ModelError(f"model request failed: {type(exc).__name__}: {exc}") from exc

        if not response.choices:
            raise ModelError("model returned no choices")
        choice = response.choices[0]
        message = choice.message
        calls: list[ToolCall] = []
        for raw_call in message.tool_calls or []:
            raw_arguments = raw_call.function.arguments or "{}"
            parse_error = None
            arguments: dict[str, Any] | None
            try:
                parsed = json.loads(raw_arguments)
                if not isinstance(parsed, dict):
                    raise ValueError("arguments must be a JSON object")
                arguments = parsed
            except (json.JSONDecodeError, ValueError) as exc:
                arguments = None
                parse_error = str(exc)
            calls.append(
                ToolCall(
                    id=raw_call.id,
                    name=raw_call.function.name,
                    arguments=arguments,
                    parse_error=parse_error,
                )
            )
        return ModelResponse(
            text=message.content or "",
            tool_calls=calls,
            finish_reason=choice.finish_reason,
        )


class QwenClient(OpenAICompatibleClient):
    """Qwen adapter using DashScope's native OpenAI-compatible tool protocol."""

    def __init__(
        self,
        config: ModelConfig,
        credential_provider: Callable[[], str | None] | None = None,
    ) -> None:
        if config.provider != "qwen":
            raise ValueError("QwenClient requires model.provider=qwen")
        if not config.base_url:
            config.base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        super().__init__(config, credential_provider)
