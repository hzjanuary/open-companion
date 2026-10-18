"""Typed provider-neutral generation contract."""

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Protocol, runtime_checkable
from uuid import UUID

from app.application.context import ConversationContext
from app.domain.media import EphemeralMedia
from app.domain.planning import ProviderErrorCategory, ProviderId
from app.domain.provider_governance import RouteRole


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    json_schema: bool
    json_object: bool
    max_output_tokens_parameter: str | None
    reports_usage: bool
    request_identifier: bool
    keyless_local: bool = False
    image_input: bool = False


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    planning_job_id: UUID
    context: ConversationContext
    prompt_version: str
    response_schema_version: str
    locale_hint: str
    maximum_output_tokens: int
    system_instructions: str
    user_content: str
    response_schema: dict[str, object]
    correction_attempt: int = 0
    correction_errors: tuple[str, ...] = ()
    current_image: EphemeralMedia | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class TranscriptionRequest:
    media: EphemeralMedia = field(repr=False)
    maximum_characters: int = 4000
    duration_seconds: int = 0


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    provider: ProviderId
    model: str
    text: str = field(repr=False)
    provider_request_id: str | None
    usage: "ProviderUsage"
    latency: timedelta
    refused: bool = False
    safety_blocked: bool = False


@dataclass(frozen=True, slots=True)
class ProviderUsage:
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None


@dataclass(frozen=True, slots=True)
class ProviderResult:
    provider: ProviderId
    model: str
    structured_text: str
    provider_request_id: str | None
    usage: ProviderUsage
    latency: timedelta
    finish_reason: str | None
    refused: bool = False
    safety_blocked: bool = False


@dataclass(frozen=True, slots=True)
class ProviderError(Exception):
    category: ProviderErrorCategory
    provider: ProviderId
    model: str
    retryable: bool
    operation: str
    summary: str
    retry_after: timedelta | None = None
    provider_request_id: str | None = None

    def __str__(self) -> str:
        return f"{self.provider.value} {self.operation}: {self.category.value}"


class ProviderIdentity(Protocol):
    provider_id: ProviderId
    model: str
    capabilities: ProviderCapabilities

    async def aclose(self) -> None: ...


class ModelProvider(ProviderIdentity, Protocol):
    async def generate(self, request: GenerationRequest) -> ProviderResult: ...


class TranscriptionProvider(ProviderIdentity, Protocol):
    async def transcribe(
        self, request: TranscriptionRequest
    ) -> TranscriptionResult: ...


@runtime_checkable
class AttemptGovernedModelProvider(ModelProvider, Protocol):
    """Provider whose every call crosses durable SPEC-026 admission."""

    async def generate_attempt(
        self, request: GenerationRequest, role: RouteRole, ordinal: int
    ) -> ProviderResult: ...

    async def record_application_outcome(self, outcome: str) -> None: ...

    def fallback_allowed(self, category: ProviderErrorCategory) -> bool: ...
