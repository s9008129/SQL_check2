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




def _ollama_cloud_settings(base_llm):
    return dataclasses.replace(
        base_llm,
        provider="ollama_cloud",
        provider_type="ollama",
        remote=True,
        base_url="https://ollama.com",
        model="gemma4:31b",
        api_key_env="OLLAMA_API_KEY",
        api_key="ollama-test-key",
        timeout_seconds=30,
        max_output_tokens=3072,
        temperature=0.2,
        top_p=0.95,
        top_k=64,
        keep_alive=None,
        think=False,
        allow_short_ascii_literals=True,
    )

def _openrouter_settings(base_llm):
    return dataclasses.replace(
        base_llm,
        provider="openrouter",
        provider_type="openrouter",
        remote=True,
        base_url="https://openrouter.ai/api/v1",
        model="google/gemma-4-31b-it",
        api_key_env="OPENROUTER_API_KEY",
        api_key="openrouter-test-key",
        timeout_seconds=30,
        max_output_tokens=3072,
        temperature=0.2,
        top_p=0.95,
        top_k=64,
        keep_alive=None,
        think=False,
        thinking_level=None,
        allow_short_ascii_literals=True,
    )


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


@respx.mock
async def test_ollama_cloud_uses_bearer_auth_and_same_chat_shape(base_llm):
    settings = _ollama_cloud_settings(base_llm)
    route = respx.post("https://ollama.com/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": '{"ok":true}'},
                "done_reason": "stop",
                "prompt_eval_count": 123,
                "eval_count": 45,
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

    request = route.calls[0].request
    assert request.headers["authorization"] == "Bearer ollama-test-key"
    body = json.loads(request.content)
    assert body["model"] == "gemma4:31b"
    assert body["format"] == {"type": "object"}
    assert body["think"] is False
    assert body["options"]["temperature"] == 0.2
    assert body["options"]["top_p"] == 0.95
    assert body["options"]["top_k"] == 64
    assert body["options"]["num_ctx"] == 16384
    assert body["options"]["num_predict"] == 3072
    assert "keep_alive" not in body
    assert reply.provider == "ollama_cloud"
    assert reply.model == "gemma4:31b"


async def test_ollama_cloud_missing_api_key_fails_as_configuration(base_llm):
    settings = dataclasses.replace(_ollama_cloud_settings(base_llm), api_key=None)
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
async def test_ollama_cloud_health_uses_bearer_auth(base_llm):
    settings = _ollama_cloud_settings(base_llm)
    route = respx.get("https://ollama.com/api/tags").mock(
        return_value=httpx.Response(
            200,
            json={"models": [{"name": "gemma4:31b"}]},
        )
    )

    assert await llm_provider.check_available(settings) is True
    assert route.call_count == 1
    assert route.calls[0].request.headers["authorization"] == "Bearer ollama-test-key"


@respx.mock
async def test_openrouter_adapter_uses_chat_completions_and_strict_json_schema(base_llm):
    settings = _openrouter_settings(base_llm)
    route = respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": '{"summary":"ok"}'},
                    }
                ],
                "usage": {
                    "prompt_tokens": 321,
                    "completion_tokens": 87,
                    "total_tokens": 408,
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
    assert request.headers["authorization"] == "Bearer openrouter-test-key"
    body = json.loads(request.content)
    assert body["model"] == "google/gemma-4-31b-it"
    assert body["messages"][0] == {"role": "system", "content": "system rule"}
    assert body["messages"][1] == {"role": "user", "content": "<SQL_DATA>{}</SQL_DATA>"}
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "sqlcheck_response",
            "strict": True,
            "schema": schema,
        },
    }
    assert body["provider"] == {"require_parameters": True}
    assert body["stream"] is False
    assert body["max_tokens"] == 3072
    assert body["temperature"] == 0.2
    assert body["top_p"] == 0.95
    assert body["top_k"] == 64
    assert body["reasoning"] == {"enabled": False}
    assert reply.content == '{"summary":"ok"}'
    assert reply.prompt_tokens == 321
    assert reply.output_tokens == 87
    assert reply.total_tokens == 408
    assert reply.provider == "openrouter"


@respx.mock
async def test_openrouter_per_request_output_budget_overrides_profile_default(base_llm):
    settings = _openrouter_settings(base_llm)
    route = respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": '{"summary":"ok"}'},
                    }
                ],
                "usage": {
                    "prompt_tokens": 25,
                    "completion_tokens": 6,
                    "total_tokens": 31,
                },
            },
        )
    )

    async with httpx.AsyncClient() as client:
        await llm_provider.generate_structured_json(
            client,
            settings,
            system_prompt="system",
            user_content="user",
            response_schema={"type": "object"},
            context_window=16384,
            max_output_tokens=8192,
        )

    body = json.loads(route.calls[0].request.content)
    assert settings.max_output_tokens == 3072
    assert body["max_tokens"] == 8192


async def test_openrouter_missing_api_key_fails_as_configuration(base_llm):
    settings = dataclasses.replace(_openrouter_settings(base_llm), api_key=None)
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
async def test_openrouter_length_maps_to_output_truncated(base_llm):
    settings = _openrouter_settings(base_llm)
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"role": "assistant", "content": ""},
                    }
                ],
                "usage": {"completion_tokens": 3072},
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
    assert exc.value.output_tokens == 3072


@respx.mock
async def test_openrouter_health_uses_models_endpoint(base_llm):
    settings = _openrouter_settings(base_llm)
    route = respx.get("https://openrouter.ai/api/v1/models").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"id": "google/gemma-4-31b-it"},
                    {"id": "openai/gpt-5"},
                ]
            },
        )
    )

    assert await llm_provider.check_available(settings) is True
    assert route.call_count == 1
    assert route.calls[0].request.headers["authorization"] == "Bearer openrouter-test-key"
