import asyncio
import json

import httpx
import pytest

from app.application.ports.text_to_speech import (
    TextToSpeechError,
    TextToSpeechRequest,
    TextToSpeechResult,
)
from app.domain.planning import ProviderErrorCategory, ProviderId
from app.domain.voice import (
    VOICE_ARTIFACT_MAX_BYTES,
    VOICE_SOURCE_MAX_CHARACTERS,
    VoiceFormat,
)
from app.infrastructure.text_to_speech import OpenAITextToSpeechAdapter


class _Chunks(httpx.AsyncByteStream):
    def __init__(self, *chunks: bytes) -> None:
        self._chunks = chunks

    async def __aiter__(self):  # type: ignore[no-untyped-def]
        for chunk in self._chunks:
            yield chunk


def _request(text: str = "speak this") -> TextToSpeechRequest:
    return TextToSpeechRequest(
        text=text,
        model="gpt-4o-mini-tts",
        voice="alloy",
    )


@pytest.mark.parametrize(
    ("length", "valid"),
    [
        (VOICE_SOURCE_MAX_CHARACTERS - 1, True),
        (VOICE_SOURCE_MAX_CHARACTERS, True),
        (VOICE_SOURCE_MAX_CHARACTERS + 1, False),
    ],
)
def test_tts_source_limit_is_exact_in_unicode_code_points(
    length: int, valid: bool
) -> None:
    text = "\U0001f642" * length
    if valid:
        assert len(_request(text).text) == length
    else:
        with pytest.raises(ValueError, match="1..4000"):
            _request(text)


@pytest.mark.parametrize(
    ("size", "valid"),
    [
        (VOICE_ARTIFACT_MAX_BYTES - 1, True),
        (VOICE_ARTIFACT_MAX_BYTES, True),
        (VOICE_ARTIFACT_MAX_BYTES + 1, False),
    ],
)
def test_tts_result_byte_limit_and_ogg_envelope_are_exact(
    size: int, valid: bool
) -> None:
    audio = b"OggS" + b"a" * (size - 4)
    values = {
        "provider": ProviderId.OPENAI,
        "model": "gpt-4o-mini-tts",
        "audio_bytes": audio,
        "format": VoiceFormat.OGG_OPUS,
        "mime_type": "audio/ogg",
    }
    if valid:
        assert len(TextToSpeechResult(**values).audio_bytes) == size
    else:
        with pytest.raises(ValueError, match="byte count"):
            TextToSpeechResult(**values)


def test_openai_tts_request_and_streamed_result_are_exact() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={
                "content-type": "audio/ogg; codecs=opus",
                "content-length": "8",
                "x-request-id": "req-safe",
            },
            stream=_Chunks(b"OggS", b"opus"),
        )

    async def scenario() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        adapter = OpenAITextToSpeechAdapter(
            base_url="https://api.test.invalid/v1",
            api_key="test-key",
            timeout_seconds=30,
            client=client,
        )
        result = await adapter.synthesize(_request())
        assert result.audio_bytes == b"OggSopus"
        assert result.provider_request_id == "req-safe"
        assert requests[0].method == "POST"
        assert requests[0].url == "https://api.test.invalid/v1/audio/speech"
        assert requests[0].headers["accept"] == "audio/ogg"
        assert requests[0].headers["accept-encoding"] == "identity"
        assert json.loads(requests[0].content) == {
            "model": "gpt-4o-mini-tts",
            "input": "speak this",
            "voice": "alloy",
            "response_format": "opus",
            "speed": 1.0,
        }
        await client.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("headers", "chunks", "diagnostic"),
    [
        (
            {"content-type": "audio/ogg", "content-length": "5242881"},
            (b"OggS",),
            "body length",
        ),
        (
            {"content-type": "audio/ogg"},
            (b"OggS", b"a" * (VOICE_ARTIFACT_MAX_BYTES - 3)),
            "exceeds",
        ),
        (
            {"content-type": "text/plain"},
            (b"OggS",),
            "content type",
        ),
        (
            {"content-type": "audio/ogg", "content-encoding": "gzip"},
            (b"OggS",),
            "encoded",
        ),
        (
            {"content-type": "audio/ogg", "content-length": "9"},
            (b"OggS",),
            "truncated",
        ),
        (
            {"content-type": "audio/ogg"},
            (b"not-ogg",),
            "audio envelope",
        ),
    ],
)
def test_openai_tts_rejects_untrusted_response_bytes(
    headers: dict[str, str], chunks: tuple[bytes, ...], diagnostic: str
) -> None:
    async def scenario() -> None:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, headers=headers, stream=_Chunks(*chunks))
            )
        )
        adapter = OpenAITextToSpeechAdapter(
            base_url="https://api.test.invalid/v1",
            api_key="test-key",
            timeout_seconds=30,
            client=client,
        )
        with pytest.raises(TextToSpeechError) as captured:
            await adapter.synthesize(_request())
        assert captured.value.category == ProviderErrorCategory.MALFORMED_RESPONSE
        assert captured.value.io_possible is False
        assert diagnostic in captured.value.diagnostic
        await client.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("status", "category"),
    [
        (400, ProviderErrorCategory.INVALID_REQUEST),
        (401, ProviderErrorCategory.AUTHENTICATION),
        (403, ProviderErrorCategory.PERMISSION),
        (413, ProviderErrorCategory.CONTEXT_TOO_LARGE),
        (429, ProviderErrorCategory.RATE_LIMITED),
        (500, ProviderErrorCategory.PROVIDER_UNAVAILABLE),
    ],
)
def test_openai_tts_status_failures_are_typed_without_body_disclosure(
    status: int, category: ProviderErrorCategory
) -> None:
    async def scenario() -> None:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(status, text="sensitive provider body")
            )
        )
        adapter = OpenAITextToSpeechAdapter(
            base_url="https://api.test.invalid/v1",
            api_key="test-key",
            timeout_seconds=30,
            client=client,
        )
        with pytest.raises(TextToSpeechError) as captured:
            await adapter.synthesize(_request())
        assert captured.value.category == category
        assert captured.value.io_possible is False
        assert "sensitive" not in captured.value.diagnostic
        assert "sensitive" not in str(captured.value)
        await client.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("error", "category"),
    [
        (httpx.ReadTimeout("late response"), ProviderErrorCategory.TIMEOUT),
        (httpx.ReadError("connection reset"), ProviderErrorCategory.TRANSPORT),
    ],
)
def test_openai_tts_timeout_or_reset_is_possible_io_without_retry(
    error: httpx.HTTPError, category: ProviderErrorCategory
) -> None:
    async def scenario() -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            raise error

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        adapter = OpenAITextToSpeechAdapter(
            base_url="https://api.test.invalid/v1",
            api_key="test-key",
            timeout_seconds=30,
            client=client,
        )
        with pytest.raises(TextToSpeechError) as captured:
            await adapter.synthesize(_request())
        assert captured.value.category == category
        assert captured.value.io_possible is True
        assert captured.value.retryable is False
        await client.aclose()

    asyncio.run(scenario())
