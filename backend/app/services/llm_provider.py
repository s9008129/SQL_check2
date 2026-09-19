"""Provider adapters for SQLCheck's advisory LLM.

This module is the only place that knows vendor HTTP shapes. ai_service keeps
all SQLCheck product rules, masking, prompt, structured-output validation and
rewrite verification; provider adapters only translate a single structured
generation request to/from a vendor API.

Supported v1 providers:
- ollama: local / formal-host Gemma 4 via /api/chat
- ollama_cloud: Ollama Cloud direct API via https://ollama.com/api/chat
- gemini: Google Gemini REST generateContent

Adding a provider should require one adapter here + one profile in llm.yaml,
not changes to rule_engine / scoring / frontend.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.settings import LLMSettings


@dataclass(frozen=True)
class ProviderReply:
    content: str
    provider: str
    model: str
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    total_duration_ms: int | None = None
    context_window: int | None = None
    think: bool | None = None
    thinking_level: str | None = None


class LLMConfigurationError(RuntimeError):
    """Selected provider is missing required configuration (for example API key)."""


class LLMOutputTruncatedError(RuntimeError):
    """Provider stopped because the configured output-token budget was reached."""

    def __init__(self, output_tokens: int | None = None, thinking_chars: int = 0):
        super().__init__("output truncated")
        self.output_tokens = output_tokens
        self.thinking_chars = thinking_chars


class LLMPromptTruncatedError(RuntimeError):
    """Local provider silently truncated the prompt/context."""

    def __init__(self, prompt_tokens: int, context_window: int):
        super().__init__("prompt truncated")
        self.prompt_tokens = prompt_tokens
        self.context_window = context_window


def _model_id(model: str) -> str:
    return model.removeprefix("models/")


def _ollama_headers(settings: LLMSettings) -> dict[str, str]:
    if settings.remote:
        if not settings.api_key:
            raise LLMConfigurationError(
                f"{settings.api_key_env or 'OLLAMA_API_KEY'} is required for remote Ollama"
            )
        return {
            "Authorization": f"Bearer {settings.api_key}",
            "Content-Type": "application/json",
        }
    return {}


def _ollama_body(
    settings: LLMSettings,
    *,
    system_prompt: str,
    user_content: str,
    response_schema: dict[str, Any],
    context_window: int,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": settings.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "format": response_schema,
        "stream": False,
        "think": settings.think,
        "options": {
            "temperature": settings.temperature if settings.temperature is not None else 0.2,
            **({"top_p": settings.top_p} if settings.top_p is not None else {}),
            **({"top_k": settings.top_k} if settings.top_k is not None else {}),
            "num_ctx": context_window,
            "num_predict": settings.max_output_tokens,
        },
    }
    if settings.keep_alive is not None:
        body["keep_alive"] = settings.keep_alive
    return body


async def _generate_ollama(
    client: httpx.AsyncClient,
    settings: LLMSettings,
    *,
    system_prompt: str,
    user_content: str,
    response_schema: dict[str, Any],
    context_window: int,
) -> ProviderReply:
    body = _ollama_body(
        settings,
        system_prompt=system_prompt,
        user_content=user_content,
        response_schema=response_schema,
        context_window=context_window,
    )
    headers = _ollama_headers(settings)
    started = time.perf_counter()
    resp = await client.post(
        f"{settings.base_url}/api/chat",
        headers=headers or None,
        json=body,
    )
    resp.raise_for_status()
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    data = resp.json()

    prompt_tokens = data.get("prompt_eval_count")
    if isinstance(prompt_tokens, int) and prompt_tokens >= context_window:
        raise LLMPromptTruncatedError(prompt_tokens, context_window)

    output_tokens = data.get("eval_count")
    if data.get("done_reason") == "length":
        thinking_chars = len((data.get("message") or {}).get("thinking") or "")
        raise LLMOutputTruncatedError(
            output_tokens if isinstance(output_tokens, int) else None,
            thinking_chars=thinking_chars,
        )

    message = data.get("message") or {}
    content = message.get("content")
    if not isinstance(content, str):
        raise KeyError("message.content")

    duration_raw = data.get("total_duration")
    duration_ms = duration_raw // 1_000_000 if isinstance(duration_raw, int) else elapsed_ms

    return ProviderReply(
        content=content,
        provider=settings.provider,
        model=settings.model,
        finish_reason=data.get("done_reason"),
        prompt_tokens=prompt_tokens if isinstance(prompt_tokens, int) else None,
        output_tokens=output_tokens if isinstance(output_tokens, int) else None,
        total_tokens=(
            prompt_tokens + output_tokens
            if isinstance(prompt_tokens, int) and isinstance(output_tokens, int)
            else None
        ),
        total_duration_ms=duration_ms,
        context_window=context_window,
        think=settings.think,
    )


def _gemini_body(
    settings: LLMSettings,
    *,
    system_prompt: str,
    user_content: str,
    response_schema: dict[str, Any],
) -> dict[str, Any]:
    generation_config: dict[str, Any] = {
        "responseMimeType": "application/json",
        "responseJsonSchema": response_schema,
        "maxOutputTokens": settings.max_output_tokens,
    }
    # Temperature is provider-profile controlled. The Mac parity profile uses
    # the same 0.2 value as formal-host Ollama/Gemma so model comparison is not
    # confounded by a different sampling temperature.
    if settings.temperature is not None:
        generation_config["temperature"] = settings.temperature
    if settings.top_p is not None:
        generation_config["topP"] = settings.top_p
    if settings.top_k is not None:
        generation_config["topK"] = settings.top_k
    if settings.thinking_level:
        generation_config["thinkingConfig"] = {"thinkingLevel": settings.thinking_level}

    return {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_content}]}],
        "generationConfig": generation_config,
    }


async def _generate_gemini(
    client: httpx.AsyncClient,
    settings: LLMSettings,
    *,
    system_prompt: str,
    user_content: str,
    response_schema: dict[str, Any],
) -> ProviderReply:
    if not settings.api_key:
        raise LLMConfigurationError(
            f"{settings.api_key_env or 'GEMINI_API_KEY'} is required for Gemini"
        )

    model = _model_id(settings.model)
    url = f"{settings.base_url}/models/{model}:generateContent"
    headers = {
        "x-goog-api-key": settings.api_key,
        "Content-Type": "application/json",
    }
    body = _gemini_body(
        settings,
        system_prompt=system_prompt,
        user_content=user_content,
        response_schema=response_schema,
    )

    started = time.perf_counter()
    resp = await client.post(url, headers=headers, json=body)
    resp.raise_for_status()
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    data = resp.json()

    candidates = data.get("candidates") or []
    if not candidates:
        raise KeyError("candidates")
    first = candidates[0] or {}
    finish_reason = first.get("finishReason")
    usage = data.get("usageMetadata") or {}
    output_tokens = usage.get("candidatesTokenCount")
    if finish_reason == "MAX_TOKENS":
        raise LLMOutputTruncatedError(output_tokens if isinstance(output_tokens, int) else None)

    parts = ((first.get("content") or {}).get("parts") or [])
    content = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
    if not content:
        raise KeyError("candidates[0].content.parts.text")

    prompt_tokens = usage.get("promptTokenCount")
    total_tokens = usage.get("totalTokenCount")

    return ProviderReply(
        content=content,
        provider=settings.provider,
        model=settings.model,
        finish_reason=str(finish_reason) if finish_reason is not None else None,
        prompt_tokens=prompt_tokens if isinstance(prompt_tokens, int) else None,
        output_tokens=output_tokens if isinstance(output_tokens, int) else None,
        total_tokens=total_tokens if isinstance(total_tokens, int) else None,
        total_duration_ms=elapsed_ms,
        context_window=None,
        think=None,
        thinking_level=settings.thinking_level,
    )


async def generate_structured_json(
    client: httpx.AsyncClient,
    settings: LLMSettings,
    *,
    system_prompt: str,
    user_content: str,
    response_schema: dict[str, Any],
    context_window: int,
) -> ProviderReply:
    """Dispatch one structured-output request to the selected provider."""

    if settings.provider_type == "ollama":
        return await _generate_ollama(
            client,
            settings,
            system_prompt=system_prompt,
            user_content=user_content,
            response_schema=response_schema,
            context_window=context_window,
        )
    if settings.provider_type == "gemini":
        return await _generate_gemini(
            client,
            settings,
            system_prompt=system_prompt,
            user_content=user_content,
            response_schema=response_schema,
        )
    raise LLMConfigurationError(f"Unsupported LLM provider type: {settings.provider_type}")


async def check_available(settings: LLMSettings) -> bool:
    """Fast, non-generating provider health check. Never raises."""

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            if settings.provider_type == "ollama":
                headers = _ollama_headers(settings)
                resp = await client.get(
                    f"{settings.base_url}/api/tags",
                    headers=headers or None,
                )
                if resp.status_code != 200:
                    return False
                data = resp.json()
                names = {m.get("name") for m in data.get("models", [])}
                return settings.model in names

            if settings.provider_type == "gemini":
                if not settings.api_key:
                    return False
                model = _model_id(settings.model)
                resp = await client.get(
                    f"{settings.base_url}/models/{model}",
                    headers={"x-goog-api-key": settings.api_key},
                )
                return resp.status_code == 200

            return False
    except Exception:
        return False
