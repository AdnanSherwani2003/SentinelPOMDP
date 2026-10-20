"""OpenAI and Groq clients using the OpenAI-compatible Responses API."""
from __future__ import annotations

import os
import json
from time import perf_counter
from typing import Any, TypeVar

from pydantic import BaseModel

from .clients import LLMClientError, LLMResult
from .schemas import LLMUsage

T = TypeVar("T", bound=BaseModel)


class OpenAICompatibleResponsesClient:
    """Shared bounded adapter for compatible Responses API providers."""

    provider: str
    api_key_environment: str
    model_environment: str
    default_model: str
    base_url: str | None = None

    def __init__(self, *, model: str | None = None, api_key: str | None = None,
                 timeout_seconds: float = 30, max_retries: int = 2, client: Any = None) -> None:
        self.model = (model or os.getenv(self.model_environment)
                      or os.getenv("SENTINEL_LLM_MODEL") or self.default_model)
        if client is not None:
            self._client = client
            return
        key = api_key or os.getenv(self.api_key_environment)
        if not key:
            raise LLMClientError(f"{self.api_key_environment} is not configured")
        try:
            from openai import OpenAI
            client_options = {
                "api_key": key, "timeout": timeout_seconds, "max_retries": max_retries,
            }
            if self.base_url is not None:
                client_options["base_url"] = self.base_url
            self._client = OpenAI(**client_options)
        except Exception as exc:
            raise LLMClientError(
                f"{self.provider} client initialization failed: {type(exc).__name__}") from exc

    def generate_structured(self, *, system_prompt: str, payload: dict[str, Any],
                            response_model: type[T]) -> LLMResult:
        started = perf_counter()
        try:
            response = self._client.responses.parse(
                model=self.model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(payload, sort_keys=True)},
                ],
                text_format=response_model,
                max_output_tokens=1200,
            )
            parsed = response.output_parsed
            if parsed is None:
                raise LLMClientError("provider returned no parsed structured output")
            usage = getattr(response, "usage", None)
            input_tokens = getattr(usage, "input_tokens", None)
            output_tokens = getattr(usage, "output_tokens", None)
            total_tokens = getattr(usage, "total_tokens", None)
        except LLMClientError:
            raise
        except Exception as exc:
            raise LLMClientError(
                f"{self.provider} structured generation failed: {type(exc).__name__}") from exc
        return LLMResult(parsed=parsed, usage=LLMUsage(
            provider=self.provider, model=self.model, input_tokens=input_tokens,
            output_tokens=output_tokens, total_tokens=total_tokens,
            estimated_cost_usd=None, latency_ms=(perf_counter() - started) * 1000))


class OpenAIResponsesClient(OpenAICompatibleResponsesClient):
    """Official OpenAI endpoint. No tools are exposed to the model."""

    provider = "openai"
    api_key_environment = "OPENAI_API_KEY"
    model_environment = "SENTINEL_OPENAI_MODEL"
    default_model = "gpt-4o-mini"


class GroqResponsesClient(OpenAICompatibleResponsesClient):
    """Groq Cloud's OpenAI-compatible Responses endpoint, without model tools."""

    provider = "groq"
    api_key_environment = "GROQ_API_KEY"
    model_environment = "SENTINEL_GROQ_MODEL"
    default_model = "openai/gpt-oss-120b"
    base_url = "https://api.groq.com/openai/v1"
