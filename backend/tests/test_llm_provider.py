import dataclasses
import json

import httpx
import pytest
import respx

from app.services import llm_provider
from app.settings import get_settings


@pytest.fixture
def base_llm():
    return get_settings().llm


def _gemini_settings(base_llm):
    return dataclasses.replace(
        base_llm,
        provider="gemini",
        provider_type="gemini",
        remote=True,
        base_url="https://generativelanguage.googleapis.com/v1beta",
        model="gemma-4-31b-it",
        api_key_env="GEMINI_API_KEY",
        api_key="test-key",
        timeout_seconds=30,
        max_output_tokens=2048,
        temperature=0.2,
        top_p=0.95,
        top_k=64,
        thinking_level="minimal",
        allow_short_ascii_literals=True,
    )


@respx.mock
async def test_ollama_adapter_keeps_existing_chat_shape(base_llm):
    settings = dataclasses.replace(
        base_llm,
        provider="ollama",
        provider_type="ollama",
        base_url="http://ollama.test",
        model="gemma4:31b",
        api_key=None,
    )
    route = respx.post("http://ollama.test/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": '{"ok":true}'},
                "done_reason": "stop",
                "prompt_eval_count": 123,
                "eval_count": 45,
                "total_duration": 1_500_000_000,
            },
        )
    )

    async with httpx.AsyncClient() as client:
        reply = await llm_provider.generate_structured_json(
            client,
            settings,
            system_prompt="system",
            user_content="user",
            response_schema={"type": "object"},
            context_window=16384,
        )

    body = json.loads(route.calls[0].request.content)
    assert body["model"] == "gemma4:31b"
    assert body["messages"][0] == {"role": "system", "content": "system"}
    assert body["format"] == {"type": "object"}
    assert body["options"]["num_ctx"] == 16384
    assert body["options"]["num_predict"] == settings.max_output_tokens
    assert body["options"]["top_p"] == 0.95
    assert body["options"]["top_k"] == 64
    assert reply.content == '{"ok":true}'
    assert reply.prompt_tokens == 123
    assert reply.output_tokens == 45
    assert reply.total_duration_ms == 1500


@respx.mock
async def test_gemini_adapter_uses_generate_content_and_json_schema(base_llm):
    settings = _gemini_settings(base_llm)
    route = respx.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemma-4-31b-it:generateContent"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": '{"summary":"ok"}'}]},
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 321,
                    "candidatesTokenCount": 87,
                    "totalTokenCount": 408,
                },
            },
        )
    )

    schema = {"type": "object", "properties": {"summary": {"type": "string"}}}
    async with httpx.AsyncClient() as client:
        reply = await llm_provider.generate_structured_json(
            client,
            settings,
            system_prompt="system rule",
            user_content="<SQL_DATA>{}</SQL_DATA>",
            response_schema=schema,
            context_window=16384,
        )

    request = route.calls[0].request
    assert request.headers["x-goog-api-key"] == "test-key"
    body = json.loads(request.content)
    assert body["systemInstruction"]["parts"][0]["text"] == "system rule"
    assert body["contents"][0]["parts"][0]["text"] == "<SQL_DATA>{}</SQL_DATA>"
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["responseJsonSchema"] == schema
    assert body["generationConfig"]["maxOutputTokens"] == 2048
    assert body["generationConfig"]["temperature"] == 0.2
    assert body["generationConfig"]["topP"] == 0.95
    assert body["generationConfig"]["topK"] == 64
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "minimal"}
    assert reply.content == '{"summary":"ok"}'
    assert reply.prompt_tokens == 321
    assert reply.output_tokens == 87
    assert reply.total_tokens == 408
    assert reply.context_window is None
    assert reply.thinking_level == "minimal"


@respx.mock
async def test_gemini_max_tokens_maps_to_output_truncated(base_llm):
    settings = _gemini_settings(base_llm)
    respx.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemma-4-31b-it:generateContent"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": []}}],
                "usageMetadata": {"candidatesTokenCount": 2048},
            },
        )
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(llm_provider.LLMOutputTruncatedError) as exc:
            await llm_provider.generate_structured_json(
                client,
                settings,
                system_prompt="system",
                user_content="user",
                response_schema={"type": "object"},
                context_window=16384,
            )
    assert exc.value.output_tokens == 2048


async def test_gemini_missing_api_key_fails_as_configuration(base_llm):
    settings = dataclasses.replace(_gemini_settings(base_llm), api_key=None)
    async with httpx.AsyncClient() as client:
        with pytest.raises(llm_provider.LLMConfigurationError):
            await llm_provider.generate_structured_json(
                client,
                settings,
                system_prompt="system",
                user_content="user",
                response_schema={"type": "object"},
                context_window=16384,
            )


@respx.mock
async def test_gemini_health_uses_non_generating_models_get(base_llm):
    settings = _gemini_settings(base_llm)
    route = respx.get(
        "https://generativelanguage.googleapis.com/v1beta/models/gemma-4-31b-it"
    ).mock(return_value=httpx.Response(200, json={"name": "models/gemma-4-31b-it"}))

    assert await llm_provider.check_available(settings) is True
    assert route.call_count == 1
    assert route.calls[0].request.headers["x-goog-api-key"] == "test-key"
