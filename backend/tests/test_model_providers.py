import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from app.application.context import ContextMessage, ConversationContext
from app.application.model_provider import GenerationRequest
from app.application.response_plan import response_plan_json_schema
from app.domain.planning import ProviderId
from app.infrastructure.model_providers import (
    GeminiProvider,
    OllamaProvider,
    OpenAICompatibleProvider,
)


def request() -> GenerationRequest:
    current = ContextMessage(
        uuid4(),
        uuid4(),
        uuid4(),
        None,
        "hello",
        datetime.now(UTC),
        None,
        "Mai",
        True,
        False,
    )
    return GenerationRequest(
        uuid4(),
        ConversationContext(current, (), ()),
        "v1",
        "s1",
        "vi",
        100,
        "system",
        "user",
        response_plan_json_schema(),
    )


@pytest.mark.parametrize(
    "provider", [ProviderId.OPENAI, ProviderId.GROQ, ProviderId.OPENROUTER]
)
def test_openai_compatible_structured_contract(provider: ProviderId) -> None:
    captured: dict[str, object] = {}

    def handler(value: httpx.Request) -> httpx.Response:
        captured["url"] = str(value.url)
        captured["authorization"] = value.headers.get("authorization")
        captured["body"] = json.loads(value.content)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 4,
                    "total_tokens": 7,
                },
            },
            headers={"x-request-id": "safe-id"},
        )

    async def scenario() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        adapter = OpenAICompatibleProvider(
            provider,
            "fake-model",
            "https://provider.invalid/v1",
            "secret",
            httpx.Timeout(1),
            0.2,
            client,
        )
        result = await adapter.generate(request())
        await adapter.aclose()
        assert result.provider == provider and result.usage.total_tokens == 7

    asyncio.run(scenario())
    assert captured["url"] == "https://provider.invalid/v1/chat/completions"
    assert captured["authorization"] == "Bearer secret"
    assert captured["body"]["response_format"]["type"] == "json_schema"  # type: ignore[index]


def test_gemini_and_ollama_structured_contracts() -> None:
    def gemini_handler(value: httpx.Request) -> httpx.Response:
        assert value.headers["x-goog-api-key"] == "secret"
        assert value.url.path.endswith(":generateContent")
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": "{}"}]}, "finishReason": "STOP"}
                ],
                "usageMetadata": {"totalTokenCount": 5},
            },
        )

    def ollama_handler(value: httpx.Request) -> httpx.Response:
        assert value.url.path == "/api/chat"
        return httpx.Response(
            200,
            json={
                "message": {"content": "{}"},
                "prompt_eval_count": 2,
                "eval_count": 3,
            },
        )

    async def scenario() -> None:
        gemini = GeminiProvider(
            "fake",
            "https://gemini.invalid/v1",
            "secret",
            httpx.Timeout(1),
            0.2,
            httpx.AsyncClient(transport=httpx.MockTransport(gemini_handler)),
        )
        ollama = OllamaProvider(
            "fake",
            "http://ollama.invalid",
            httpx.Timeout(1),
            0.2,
            httpx.AsyncClient(transport=httpx.MockTransport(ollama_handler)),
        )
        assert (await gemini.generate(request())).usage.total_tokens == 5
        assert (await ollama.generate(request())).usage.input_tokens == 2

    asyncio.run(scenario())
