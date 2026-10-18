"""Provider-independent bounded text-to-speech contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.domain.planning import ProviderErrorCategory, ProviderId
from app.domain.voice import (
    VOICE_ARTIFACT_MAX_BYTES,
    VOICE_SOURCE_MAX_CHARACTERS,
    VoiceFormat,
)


@dataclass(frozen=True, slots=True)
class TextToSpeechRequest:
    text: str
    model: str
    voice: str
    format: VoiceFormat = VoiceFormat.OGG_OPUS
    maximum_bytes: int = VOICE_ARTIFACT_MAX_BYTES

    def __post_init__(self) -> None:
        if not self.text or not 1 <= len(self.text) <= VOICE_SOURCE_MAX_CHARACTERS:
            raise ValueError("TTS text must contain 1..4000 Unicode code points")
        if "\x00" in self.text:
            raise ValueError("TTS text must not contain NUL")
        if not self.model or len(self.model) > 255:
            raise ValueError("TTS model must be a bounded nonempty value")
        if self.voice != "alloy":
            raise ValueError("TTS voice must be the product-owned default")
        if self.format != VoiceFormat.OGG_OPUS:
            raise ValueError("TTS format must be OGG/Opus")
        if not 1 <= self.maximum_bytes <= VOICE_ARTIFACT_MAX_BYTES:
            raise ValueError("TTS byte limit exceeds the product maximum")


@dataclass(frozen=True, slots=True)
class TextToSpeechResult:
    provider: ProviderId
    model: str
    audio_bytes: bytes
    format: VoiceFormat
    mime_type: str
    provider_request_id: str | None = None

    def __post_init__(self) -> None:
        if self.provider != ProviderId.OPENAI:
            raise ValueError("unsupported TTS provider")
        if self.format != VoiceFormat.OGG_OPUS or self.mime_type != "audio/ogg":
            raise ValueError("TTS output must be OGG/Opus")
        if not 1 <= len(self.audio_bytes) <= VOICE_ARTIFACT_MAX_BYTES:
            raise ValueError("TTS output byte count is invalid")
        if not self.audio_bytes.startswith(b"OggS"):
            raise ValueError("TTS output is not an Ogg envelope")


class TextToSpeechError(Exception):
    def __init__(
        self,
        category: ProviderErrorCategory,
        *,
        retryable: bool,
        io_possible: bool,
        diagnostic: str,
    ) -> None:
        self.category = category
        self.retryable = retryable
        self.io_possible = io_possible
        self.diagnostic = diagnostic
        super().__init__(f"text_to_speech: {category.value}")


class TextToSpeechPort(Protocol):
    async def synthesize(self, request: TextToSpeechRequest) -> TextToSpeechResult: ...
