"""Direct typed HTTP adapters for configured model-provider families."""

import asyncio
import base64
import json
from datetime import timedelta
from time import monotonic

import httpx

from app.application.model_provider import (
    GenerationRequest,
    ModelProvider,
    ProviderCapabilities,
    ProviderError,
    ProviderResult,
    ProviderUsage,
    TranscriptionRequest,
    TranscriptionResult,
)
from app.core.config import Settings
from app.domain.media import MediaKind
from app.domain.planning import ProviderErrorCategory, ProviderId

OPENAI_CAPABILITIES = ProviderCapabilities(
    True, True, "max_tokens", True, True, image_input=True
)
OLLAMA_CAPABILITIES = ProviderCapabilities(True, True, "num_predict", True, False, True)
GEMINI_CAPABILITIES = ProviderCapabilities(True, False, "maxOutputTokens", True, True)


class OpenAICompatibleProvider:
    """OpenAI chat-completions-compatible adapter for OpenAI, Groq, OpenRouter."""

    def __init__(
        self,
        provider_id: ProviderId,
        model: str,
        base_url: str,
        api_key: str | None,
        timeout: httpx.Timeout,
        temperature: float,
        client: httpx.AsyncClient | None = None,
        capabilities: ProviderCapabilities = OPENAI_CAPABILITIES,
    ) -> None:
        self.provider_id = provider_id
        self.model = model
        self.capabilities = capabilities
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._temperature = temperature
        self._owned_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        if self._owned_client:
            await self._client.aclose()

    async def generate(self, request: GenerationRequest) -> ProviderResult:
        user_content: object = request.user_content
        if request.current_image is not None:
            image = request.current_image
            if (
                not self.capabilities.image_input
                or image.kind != MediaKind.PHOTO
                or image.mime_type != "image/jpeg"
                or not image.data
                or len(image.data) > 10 * 1024 * 1024
            ):
                raise self._error(
                    ProviderErrorCategory.UNSUPPORTED_CAPABILITY,
                    False,
                    "unsupported image input",
                )
            user_content = [
                {"type": "text", "text": request.user_content},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:image/jpeg;base64,"
                        + base64.b64encode(image.data).decode("ascii"),
                    },
                },
            ]
        if not self.capabilities.json_schema and not self.capabilities.json_object:
            raise self._error(
                ProviderErrorCategory.UNSUPPORTED_CAPABILITY,
                False,
                "structured output unsupported",
            )
        response_format: dict[str, object]
        if self.capabilities.json_schema:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": "response_plan",
                    "strict": True,
                    "schema": request.response_schema,
                },
            }
        else:
            response_format = {"type": "json_object"}
        payload: dict[str, object] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system_instructions},
                {"role": "user", "content": user_content},
            ],
            "response_format": response_format,
            "temperature": self._temperature,
            "stream": False,
        }
        if self.capabilities.max_output_tokens_parameter is not None:
            payload[self.capabilities.max_output_tokens_parameter] = (
                request.maximum_output_tokens
            )
        headers = {"Content-Type": "application/json"}
        if self._api_key is not None:
            headers["Authorization"] = f"Bearer {self._api_key}"
        started = monotonic()
        try:
            response = await self._client.post(
                f"{self._base_url}/chat/completions", json=payload, headers=headers
            )
        except httpx.TimeoutException as error:
            raise self._error(
                ProviderErrorCategory.TIMEOUT, True, "request timed out"
            ) from error
        except httpx.HTTPError as error:
            raise self._error(
                ProviderErrorCategory.TRANSPORT, True, "transport failure"
            ) from error
        latency = timedelta(seconds=monotonic() - started)
        if response.status_code >= 400:
            raise self._response_error(response)
        try:
            value = response.json()
            choice = value["choices"][0]
            content = choice["message"]["content"]
            if not isinstance(content, str):
                raise TypeError
        except (KeyError, TypeError, IndexError, ValueError) as error:
            raise self._error(
                ProviderErrorCategory.MALFORMED_RESPONSE,
                False,
                "malformed success response",
            ) from error
        usage = value.get("usage") if isinstance(value, dict) else None
        return ProviderResult(
            provider=self.provider_id,
            model=self.model,
            structured_text=content,
            provider_request_id=response.headers.get("x-request-id")
            or response.headers.get("x-groq-id"),
            usage=_openai_usage(usage),
            latency=latency,
            finish_reason=choice.get("finish_reason")
            if isinstance(choice, dict)
            else None,
            refused=bool(choice.get("message", {}).get("refusal"))
            if isinstance(choice, dict)
            else False,
        )

    async def transcribe(self, request: TranscriptionRequest) -> TranscriptionResult:
        """Bounded multipart speech-to-text through the existing Groq family."""
        media = request.media
        if (
            self.provider_id != ProviderId.GROQ
            or media.kind not in {MediaKind.VOICE, MediaKind.AUDIO}
            or media.mime_type not in {"audio/ogg", "audio/mpeg"}
            or not 1 <= len(media.data) <= 10 * 1024 * 1024
            or not 1 <= request.maximum_characters <= 8000
        ):
            raise self._error(
                ProviderErrorCategory.UNSUPPORTED_CAPABILITY,
                False,
                "unsupported transcription input",
            )
        filename = "audio.ogg" if media.mime_type == "audio/ogg" else "audio.mp3"
        headers = {"Accept-Encoding": "identity"}
        if self._api_key is not None:
            headers["Authorization"] = f"Bearer {self._api_key}"
        started = monotonic()
        try:
            async with asyncio.timeout(self._timeout.read or 20):
                async with self._client.stream(
                    "POST",
                    f"{self._base_url}/audio/transcriptions",
                    data={"model": self.model, "response_format": "json"},
                    files={"file": (filename, media.data, media.mime_type)},
                    headers=headers,
                    timeout=self._timeout,
                    follow_redirects=False,
                ) as response:
                    if response.status_code != 200:
                        raise self._response_error(response)
                    if (
                        response.headers.get("content-encoding", "identity")
                        != "identity"
                    ):
                        raise ValueError
                    content_length = response.headers.get("content-length")
                    if content_length is not None and (
                        not content_length.isascii()
                        or not content_length.isdecimal()
                        or len(content_length) > 6
                        or int(content_length) > 65536
                    ):
                        raise ValueError
                    body = bytearray()
                    try:
                        async for chunk in response.aiter_bytes(chunk_size=8192):
                            if len(body) + len(chunk) > 65536:
                                raise ValueError
                            body.extend(chunk)
                        if content_length is not None and len(body) != int(
                            content_length
                        ):
                            raise ValueError
                        value = json.loads(body)
                    finally:
                        body.clear()
                    text = value.get("text") if isinstance(value, dict) else None
                    if (
                        not isinstance(text, str)
                        or not text.strip()
                        or len(text.strip()) > request.maximum_characters
                        or "\x00" in text
                    ):
                        raise ValueError
                    return TranscriptionResult(
                        self.provider_id,
                        self.model,
                        text.strip(),
                        response.headers.get("x-request-id")
                        or response.headers.get("x-groq-id"),
                        _openai_usage(value.get("usage")),
                        timedelta(seconds=monotonic() - started),
                    )
        except (TimeoutError, httpx.TimeoutException):
            raise self._error(
                ProviderErrorCategory.TIMEOUT, False, "transcription timed out"
            ) from None
        except httpx.HTTPError:
            raise self._error(
                ProviderErrorCategory.TRANSPORT, False, "transcription transport failed"
            ) from None
        except (ValueError, TypeError, RecursionError):
            raise self._error(
                ProviderErrorCategory.MALFORMED_RESPONSE,
                False,
                "invalid transcription response",
            ) from None

    def _response_error(self, response: httpx.Response) -> ProviderError:
        status = response.status_code
        category = {
            400: ProviderErrorCategory.INVALID_REQUEST,
            401: ProviderErrorCategory.AUTHENTICATION,
            403: ProviderErrorCategory.PERMISSION,
            404: ProviderErrorCategory.INVALID_REQUEST,
            409: ProviderErrorCategory.PROVIDER_UNAVAILABLE,
            413: ProviderErrorCategory.CONTEXT_TOO_LARGE,
            429: ProviderErrorCategory.RATE_LIMITED,
        }.get(status, ProviderErrorCategory.PROVIDER_UNAVAILABLE)
        return ProviderError(
            category,
            self.provider_id,
            self.model,
            status in {409, 429} or status >= 500,
            "generate",
            "provider request failed",
            _retry_after(response),
            response.headers.get("x-request-id"),
        )

    def _error(
        self, category: ProviderErrorCategory, retryable: bool, summary: str
    ) -> ProviderError:
        return ProviderError(
            category, self.provider_id, self.model, retryable, "generate", summary
        )


class GeminiProvider:
    provider_id = ProviderId.GEMINI
    capabilities = GEMINI_CAPABILITIES

    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str,
        timeout: httpx.Timeout,
        temperature: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._temperature = temperature
        self._owned_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        if self._owned_client:
            await self._client.aclose()

    async def generate(self, request: GenerationRequest) -> ProviderResult:
        payload = {
            "systemInstruction": {"parts": [{"text": request.system_instructions}]},
            "contents": [{"role": "user", "parts": [{"text": request.user_content}]}],
            "generationConfig": {
                "temperature": self._temperature,
                "maxOutputTokens": request.maximum_output_tokens,
                "responseMimeType": "application/json",
                "responseJsonSchema": request.response_schema,
            },
        }
        if request.current_image is not None:
            raise ProviderError(
                ProviderErrorCategory.UNSUPPORTED_CAPABILITY,
                self.provider_id,
                self.model,
                False,
                "generate",
                "image input is unsupported",
            )
        started = monotonic()
        try:
            response = await self._client.post(
                f"{self._base_url}/models/{self.model}:generateContent",
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": self._api_key,
                },
            )
        except httpx.TimeoutException as error:
            raise ProviderError(
                ProviderErrorCategory.TIMEOUT,
                self.provider_id,
                self.model,
                True,
                "generate",
                "request timed out",
            ) from error
        except httpx.HTTPError as error:
            raise ProviderError(
                ProviderErrorCategory.TRANSPORT,
                self.provider_id,
                self.model,
                True,
                "generate",
                "transport failure",
            ) from error
        if response.status_code >= 400:
            category = (
                ProviderErrorCategory.RATE_LIMITED
                if response.status_code == 429
                else ProviderErrorCategory.AUTHENTICATION
                if response.status_code == 401
                else ProviderErrorCategory.PROVIDER_UNAVAILABLE
                if response.status_code >= 500
                else ProviderErrorCategory.INVALID_REQUEST
            )
            raise ProviderError(
                category,
                self.provider_id,
                self.model,
                category
                in {
                    ProviderErrorCategory.RATE_LIMITED,
                    ProviderErrorCategory.PROVIDER_UNAVAILABLE,
                },
                "generate",
                "provider request failed",
                _retry_after(response),
                response.headers.get("x-request-id"),
            )
        try:
            value = response.json()
            candidate = value["candidates"][0]
            content = candidate["content"]["parts"][0]["text"]
            if not isinstance(content, str):
                raise TypeError
        except (KeyError, TypeError, IndexError, ValueError) as error:
            raise ProviderError(
                ProviderErrorCategory.MALFORMED_RESPONSE,
                self.provider_id,
                self.model,
                False,
                "generate",
                "malformed success response",
            ) from error
        metadata = value.get("usageMetadata", {})
        return ProviderResult(
            self.provider_id,
            self.model,
            content,
            response.headers.get("x-request-id"),
            ProviderUsage(
                _integer(metadata.get("promptTokenCount")),
                _integer(metadata.get("candidatesTokenCount")),
                _integer(metadata.get("totalTokenCount")),
            ),
            timedelta(seconds=monotonic() - started),
            candidate.get("finishReason") if isinstance(candidate, dict) else None,
            bool(candidate.get("finishReason") == "SAFETY")
            if isinstance(candidate, dict)
            else False,
            bool(candidate.get("finishReason") == "SAFETY")
            if isinstance(candidate, dict)
            else False,
        )


class OllamaProvider(OpenAICompatibleProvider):
    def __init__(
        self,
        model: str,
        base_url: str,
        timeout: httpx.Timeout,
        temperature: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            ProviderId.OLLAMA,
            model,
            base_url,
            None,
            timeout,
            temperature,
            client,
            OLLAMA_CAPABILITIES,
        )

    async def generate(self, request: GenerationRequest) -> ProviderResult:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system_instructions},
                {"role": "user", "content": request.user_content},
            ],
            "format": request.response_schema,
            "stream": False,
            "options": {
                "temperature": self._temperature,
                "num_predict": request.maximum_output_tokens,
            },
        }
        if request.current_image is not None:
            raise self._error(
                ProviderErrorCategory.UNSUPPORTED_CAPABILITY,
                False,
                "image input is unsupported",
            )
        started = monotonic()
        try:
            response = await self._client.post(
                f"{self._base_url}/api/chat", json=payload
            )
        except httpx.TimeoutException as error:
            raise self._error(
                ProviderErrorCategory.TIMEOUT, True, "request timed out"
            ) from error
        except httpx.HTTPError as error:
            raise self._error(
                ProviderErrorCategory.TRANSPORT, True, "transport failure"
            ) from error
        if response.status_code >= 400:
            raise self._response_error(response)
        try:
            value = response.json()
            content = value["message"]["content"]
            if not isinstance(content, str):
                raise TypeError
        except (KeyError, TypeError, ValueError) as error:
            raise self._error(
                ProviderErrorCategory.MALFORMED_RESPONSE,
                False,
                "malformed success response",
            ) from error
        return ProviderResult(
            self.provider_id,
            self.model,
            content,
            None,
            ProviderUsage(
                _integer(value.get("prompt_eval_count")),
                _integer(value.get("eval_count")),
                None,
            ),
            timedelta(seconds=monotonic() - started),
            "stop",
        )


def create_model_provider(
    settings: Settings, provider: ProviderId, model_override: str | None = None
) -> ModelProvider:
    timeout = httpx.Timeout(
        settings.llm_timeout_seconds, connect=settings.llm_connect_timeout_seconds
    )
    model = model_override or getattr(settings, f"llm_{provider.value}_model")
    if not model:
        raise ValueError("configured provider has no model")
    if provider == ProviderId.GEMINI:
        key = settings.llm_gemini_api_key
        if key is None:
            raise ValueError("configured provider has no credential")
        return GeminiProvider(
            model,
            settings.llm_gemini_base_url,
            key.get_secret_value(),
            timeout,
            settings.llm_temperature,
        )
    if provider == ProviderId.OLLAMA:
        return OllamaProvider(
            model, settings.llm_ollama_base_url, timeout, settings.llm_temperature
        )
    key = getattr(settings, f"llm_{provider.value}_api_key")
    if key is None:
        raise ValueError("configured provider has no credential")
    return OpenAICompatibleProvider(
        provider,
        model,
        getattr(settings, f"llm_{provider.value}_base_url"),
        key.get_secret_value(),
        timeout,
        settings.llm_temperature,
    )


def _openai_usage(value: object) -> ProviderUsage:
    if value is None:
        return ProviderUsage(None, None, None)
    if not isinstance(value, dict):
        return ProviderUsage(-1, None, None)
    return ProviderUsage(
        _integer(value.get("prompt_tokens")),
        _integer(value.get("completion_tokens")),
        _integer(value.get("total_tokens")),
    )


def _integer(value: object) -> int | None:
    if value is None:
        return None
    # Preserve invalidity for the durable classifier without retaining raw data.
    return value if type(value) is int else -1


def _retry_after(response: httpx.Response) -> timedelta | None:
    raw = response.headers.get("retry-after")
    try:
        return timedelta(seconds=max(0, min(float(raw or ""), 120)))
    except ValueError:
        return None
