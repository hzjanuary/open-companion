import asyncio
import json
import logging
from dataclasses import replace

import httpx
import pytest

from app.application.model_provider import ProviderError, TranscriptionRequest
from app.domain.media import EphemeralMedia, MediaKind
from app.domain.planning import ProviderErrorCategory, ProviderId
from app.infrastructure.model_providers import (
    GeminiProvider,
    OllamaProvider,
    OpenAICompatibleProvider,
)

from .test_model_providers import request


def audio():
    return TranscriptionRequest(
        EphemeralMedia(MediaKind.VOICE, "audio/ogg", b"bounded-opus")
    )


def adapter(client, provider=ProviderId.GROQ, timeout=1):
    return OpenAICompatibleProvider(
        provider,
        "approved",
        "https://provider.invalid/v1",
        "secret",
        httpx.Timeout(timeout),
        0,
        client,
    )


def test_transcription_multipart_and_unknown_usage(caplog):
    caplog.set_level(logging.DEBUG)
    captured = []

    def handler(req):
        captured.append(req)
        assert req.url.path == "/v1/audio/transcriptions"
        assert not req.url.query
        assert req.headers["authorization"] == "Bearer secret"
        assert b'filename="audio.ogg"' in req.content
        assert b"bounded-opus" in req.content
        return httpx.Response(200, json={"text": "derived transcript"})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await adapter(client).transcribe(audio())
            assert result.text == "derived transcript"
            assert result.usage.input_tokens is None
            assert result.usage.total_tokens is None
            assert "derived transcript" not in repr(result)
            assert "bounded-opus" not in repr(audio())

    asyncio.run(scenario())
    assert len(captured) == 1
    assert "derived transcript" not in caplog.text
    assert "bounded-opus" not in caplog.text
    assert "secret" not in caplog.text


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302, headers={"location": "https://untrusted.invalid"}),
        httpx.Response(200, json={"text": "x" * 4001}),
        httpx.Response(200, json={"text": ""}),
        httpx.Response(200, json={"text": "contains\u0000nul"}),
        httpx.Response(200, content=b"x" * 65537),
        httpx.Response(200, content=b"[" * 1500 + b"0" + b"]" * 1500),
        httpx.Response(200, content=b'{"text":"hi"}', headers={"content-length": "30"}),
    ],
)
def test_transcription_rejects_redirect_invalid_or_unbounded_response(response):
    calls = []

    async def scenario():
        def handler(req):
            calls.append(req)
            return response

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ProviderError):
                await adapter(client).transcribe(audio())

    asyncio.run(scenario())
    assert len(calls) == 1


def test_transcription_total_timeout():
    async def handler(req):
        await asyncio.sleep(1)
        return httpx.Response(200, json={"text": "late"})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ProviderError) as error:
                await adapter(client, timeout=0.001).transcribe(audio())
            assert error.value.category == ProviderErrorCategory.TIMEOUT
            assert not error.value.retryable

    asyncio.run(scenario())


def test_non_groq_transcription_is_rejected_without_io():
    def handler(req):
        raise AssertionError("provider I/O must not occur")

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ProviderError):
                await adapter(client, provider=ProviderId.OPENAI).transcribe(audio())

    asyncio.run(scenario())


def test_image_uses_inline_current_turn_only():
    image = EphemeralMedia(MediaKind.PHOTO, "image/jpeg", b"image-bytes", 1, 1)

    def handler(req):
        payload = json.loads(req.content)
        assert payload["messages"][0]["content"] == "system"
        assert payload["messages"][1]["content"] == [
            {"type": "text", "text": "user"},
            {
                "type": "image_url",
                "image_url": {"url": "data:image/jpeg;base64,aW1hZ2UtYnl0ZXM="},
            },
        ]
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await adapter(client).generate(replace(request(), current_image=image))

    asyncio.run(scenario())


@pytest.mark.parametrize("provider", ["gemini", "ollama"])
def test_unimplemented_image_adapter_rejects_before_io(provider):
    def handler(req):
        raise AssertionError("unsupported image must never reach I/O")

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            if provider == "gemini":
                model = GeminiProvider(
                    "model",
                    "https://provider.invalid",
                    "secret",
                    httpx.Timeout(1),
                    0,
                    client,
                )
            else:
                model = OllamaProvider(
                    "model", "https://provider.invalid", httpx.Timeout(1), 0, client
                )
            with pytest.raises(ProviderError) as error:
                await model.generate(
                    replace(
                        request(),
                        current_image=EphemeralMedia(
                            MediaKind.PHOTO, "image/jpeg", b"bounded", 1, 1
                        ),
                    )
                )
            assert error.value.category == ProviderErrorCategory.UNSUPPORTED_CAPABILITY

    asyncio.run(scenario())
