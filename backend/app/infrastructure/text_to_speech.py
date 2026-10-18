"""Bounded OpenAI speech adapter for explicit Telegram voice playback."""

from __future__ import annotations

import asyncio

import httpx

from app.application.ports.text_to_speech import (
    TextToSpeechError,
    TextToSpeechRequest,
    TextToSpeechResult,
)
from app.domain.planning import ProviderErrorCategory, ProviderId
from app.domain.voice import VoiceFormat

_ALLOWED_CONTENT_TYPES = frozenset(
    {"audio/ogg", "audio/opus", "application/ogg", "application/octet-stream"}
)


class OpenAITextToSpeechAdapter:
    """Call OpenAI's speech endpoint without chat completion or transcoding."""

    provider_id = ProviderId.OPENAI

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = httpx.Timeout(
            timeout_seconds, connect=min(5.0, timeout_seconds)
        )
        self._owned_client = client is None
        self._client = client or httpx.AsyncClient(timeout=self._timeout)

    async def aclose(self) -> None:
        if self._owned_client:
            await self._client.aclose()

    async def synthesize(self, request: TextToSpeechRequest) -> TextToSpeechResult:
        if self._api_key is None:
            raise TextToSpeechError(
                ProviderErrorCategory.INVALID_CONFIGURATION,
                retryable=False,
                io_possible=False,
                diagnostic="OpenAI TTS credential is unavailable",
            )
        if request.format != VoiceFormat.OGG_OPUS:
            raise TextToSpeechError(
                ProviderErrorCategory.UNSUPPORTED_CAPABILITY,
                retryable=False,
                io_possible=False,
                diagnostic="unsupported TTS format",
            )
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "audio/ogg",
            "Accept-Encoding": "identity",
            "Content-Type": "application/json",
        }
        payload = {
            "model": request.model,
            "input": request.text,
            "voice": request.voice,
            "response_format": "opus",
            "speed": 1.0,
        }
        try:
            async with asyncio.timeout(self._timeout.read or 30):
                async with self._client.stream(
                    "POST",
                    f"{self._base_url}/audio/speech",
                    json=payload,
                    headers=headers,
                    timeout=self._timeout,
                    follow_redirects=False,
                ) as response:
                    if response.status_code != 200:
                        raise _response_error(response)
                    content_type = response.headers.get("content-type", "")
                    media_type = content_type.partition(";")[0].strip().casefold()
                    if media_type not in _ALLOWED_CONTENT_TYPES:
                        raise TextToSpeechError(
                            ProviderErrorCategory.MALFORMED_RESPONSE,
                            retryable=False,
                            io_possible=False,
                            diagnostic="unexpected TTS content type",
                        )
                    if (
                        response.headers.get("content-encoding", "identity")
                        != "identity"
                    ):
                        raise TextToSpeechError(
                            ProviderErrorCategory.MALFORMED_RESPONSE,
                            retryable=False,
                            io_possible=False,
                            diagnostic="encoded TTS body is unsupported",
                        )
                    declared = response.headers.get("content-length")
                    if declared is not None and (
                        not declared.isascii()
                        or not declared.isdecimal()
                        or len(declared) > 8
                        or not 1 <= int(declared) <= request.maximum_bytes
                    ):
                        raise TextToSpeechError(
                            ProviderErrorCategory.MALFORMED_RESPONSE,
                            retryable=False,
                            io_possible=False,
                            diagnostic="TTS body length is invalid",
                        )
                    body = bytearray()
                    try:
                        async for chunk in response.aiter_bytes(chunk_size=65_536):
                            if len(body) + len(chunk) > request.maximum_bytes:
                                raise TextToSpeechError(
                                    ProviderErrorCategory.MALFORMED_RESPONSE,
                                    retryable=False,
                                    io_possible=False,
                                    diagnostic="TTS body exceeds the product limit",
                                )
                            body.extend(chunk)
                        if declared is not None and len(body) != int(declared):
                            raise TextToSpeechError(
                                ProviderErrorCategory.MALFORMED_RESPONSE,
                                retryable=False,
                                io_possible=False,
                                diagnostic="TTS body is truncated",
                            )
                        result = TextToSpeechResult(
                            provider=ProviderId.OPENAI,
                            model=request.model,
                            audio_bytes=bytes(body),
                            format=VoiceFormat.OGG_OPUS,
                            mime_type="audio/ogg",
                            provider_request_id=response.headers.get("x-request-id"),
                        )
                    except ValueError as error:
                        raise TextToSpeechError(
                            ProviderErrorCategory.MALFORMED_RESPONSE,
                            retryable=False,
                            io_possible=False,
                            diagnostic="invalid TTS audio envelope",
                        ) from error
                    finally:
                        body.clear()
                    return result
        except TextToSpeechError:
            raise
        except (TimeoutError, httpx.TimeoutException):
            raise TextToSpeechError(
                ProviderErrorCategory.TIMEOUT,
                retryable=False,
                io_possible=True,
                diagnostic="TTS request outcome is uncertain",
            ) from None
        except httpx.HTTPError:
            raise TextToSpeechError(
                ProviderErrorCategory.TRANSPORT,
                retryable=False,
                io_possible=True,
                diagnostic="TTS transport outcome is uncertain",
            ) from None


def _response_error(response: httpx.Response) -> TextToSpeechError:
    category = {
        400: ProviderErrorCategory.INVALID_REQUEST,
        401: ProviderErrorCategory.AUTHENTICATION,
        403: ProviderErrorCategory.PERMISSION,
        404: ProviderErrorCategory.INVALID_REQUEST,
        409: ProviderErrorCategory.PROVIDER_UNAVAILABLE,
        413: ProviderErrorCategory.CONTEXT_TOO_LARGE,
        429: ProviderErrorCategory.RATE_LIMITED,
    }.get(
        response.status_code,
        ProviderErrorCategory.PROVIDER_UNAVAILABLE
        if response.status_code >= 500
        else ProviderErrorCategory.INVALID_REQUEST,
    )
    return TextToSpeechError(
        category,
        retryable=False,
        io_possible=False,
        diagnostic="TTS provider rejected the request",
    )
