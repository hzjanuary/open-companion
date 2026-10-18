"""One bounded media preparation phase inside the existing planning worker."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from time import perf_counter
from uuid import UUID

import httpx

from app.application.model_provider import (
    ProviderError,
    TranscriptionProvider,
    TranscriptionRequest,
)
from app.application.ports.concurrency import ConcurrencyLimiter
from app.application.ports.media import MediaDownloader, MediaError
from app.application.ports.rate_limit import RateLimiter
from app.application.ports.telemetry import MetricsRecorder
from app.core.config import Settings
from app.domain.media import EphemeralMedia, MediaFailureReason, MediaKind, MediaStatus
from app.domain.planning import ProviderErrorCategory, ProviderId
from app.domain.provider_governance import WorkloadClass
from app.infrastructure.database.media import MediaWork, SqlAlchemyMediaRepository
from app.infrastructure.database.provider_governance import (
    ProviderGovernanceUnavailable,
    SqlAlchemyProviderGovernanceRepository,
)
from app.infrastructure.governed_provider import GovernedTranscriptionProvider
from app.infrastructure.model_providers import OpenAICompatibleProvider
from app.infrastructure.telegram.adapter import TelegramAdapter


@dataclass(frozen=True, slots=True)
class PreparedMedia:
    work: MediaWork | None = field(default=None, repr=False)
    image: EphemeralMedia | None = field(default=None, repr=False)
    failure: MediaFailureReason | None = None
    transcript_changed: bool = False


def record_media_operation(
    telemetry: MetricsRecorder,
    kind: str,
    stage: str,
    outcome: str,
    *,
    reason: str = "none",
    duration: float = 0,
) -> None:
    labels = {"kind": kind, "stage": stage, "outcome": outcome, "reason": reason}
    telemetry.increment("january_telegram_media_operations_total", **labels)
    telemetry.observe(
        "january_telegram_media_operation_duration_seconds", duration, **labels
    )


def generation_requirements(
    settings: Settings, *, image: bool = False
) -> dict[str, object]:
    requirements: dict[str, object] = {
        "json_schema": True,
        "maximum_output_tokens": settings.llm_max_output_tokens,
        "allowed_data_classes": ["local", "approved_external"],
        "require_current_health": True,
    }
    if image:
        requirements["image_input"] = True
    return requirements


async def prepare_media(
    *,
    settings: Settings,
    repository: SqlAlchemyMediaRepository,
    governance: SqlAlchemyProviderGovernanceRepository,
    job_id: UUID,
    owner: str,
    attempt: int,
    connection_id: UUID,
    rate_limiter: RateLimiter | None,
    concurrency_limiter: ConcurrencyLimiter | None,
    telemetry: MetricsRecorder,
    safety_preflight: Callable[[], Awaitable[bool]],
    downloader: MediaDownloader | None = None,
    transcription_provider: TranscriptionProvider | None = None,
) -> PreparedMedia:
    started = perf_counter()
    work = await repository.claim(job_id, owner, attempt)
    if work is None:
        return PreparedMedia(failure=MediaFailureReason.STALE_LEASE)
    if work.status == MediaStatus.COMPLETE:
        record_media_operation(
            telemetry, work.attachment.kind.value, "prepare", "reused"
        )
        return PreparedMedia(work=work)
    if work.status in {MediaStatus.FAILED, MediaStatus.AMBIGUOUS}:
        return PreparedMedia(work=work, failure=work.failure_reason)
    assert work.lease_token is not None
    token = work.lease_token

    async def fail(reason: MediaFailureReason) -> PreparedMedia:
        record_media_operation(
            telemetry,
            work.attachment.kind.value,
            "prepare",
            "ambiguous" if reason == MediaFailureReason.AMBIGUOUS else "failed",
            reason=reason.value,
            duration=perf_counter() - started,
        )
        persisted = await repository.fail(job_id, owner, attempt, token, reason)
        return PreparedMedia(
            work=work, failure=reason if persisted else MediaFailureReason.STALE_LEASE
        )

    async def before_io() -> bool:
        return await safety_preflight() and await repository.preflight(
            job_id, owner, attempt, token
        )

    if not settings.telegram_media_enabled:
        return await fail(MediaFailureReason.DISABLED)
    if (
        settings.provider_governance_mode != "enforce"
        or not settings.telegram_enabled
        or rate_limiter is None
        or concurrency_limiter is None
        or settings.telegram_platform_connection_id != connection_id
        or settings.telegram_bot_token is None
    ):
        return await fail(MediaFailureReason.UNAVAILABLE)
    kind = work.attachment.kind
    try:
        source = await governance.planning_source(job_id)
        requirements = (
            generation_requirements(settings, image=True)
            if kind == MediaKind.PHOTO
            else {
                "speech_to_text": True,
                "allowed_data_classes": ["approved_external"],
                "require_current_health": True,
                "audio_format": work.attachment.mime_type,
                "maximum_audio_bytes": settings.telegram_media_audio_max_bytes,
                "maximum_audio_duration_seconds": (
                    settings.telegram_media_audio_max_duration_seconds
                ),
            }
        )
        routes = await governance.resolve_routes(
            source,
            WorkloadClass.CHAT_GENERATION
            if kind == MediaKind.PHOTO
            else WorkloadClass.TRANSCRIPTION,
            requirements,
        )
    except ProviderGovernanceUnavailable:
        return await fail(MediaFailureReason.UNAVAILABLE)
    if not routes:
        return await fail(MediaFailureReason.UNAVAILABLE)
    if (
        kind != MediaKind.PHOTO
        and transcription_provider is None
        and settings.llm_groq_api_key is None
    ):
        return await fail(MediaFailureReason.UNAVAILABLE)
    owned_downloader = TelegramAdapter(settings) if downloader is None else None
    fetcher = downloader or owned_downloader
    assert fetcher is not None
    download_started = perf_counter()
    try:
        media = await fetcher.download_media(work.attachment, before_io=before_io)
    except MediaError as error:
        record_media_operation(
            telemetry,
            kind.value,
            "download",
            "failed",
            reason=error.reason.value,
            duration=perf_counter() - download_started,
        )
        return await fail(error.reason)
    finally:
        if owned_downloader is not None:
            await owned_downloader.aclose()
    record_media_operation(
        telemetry,
        kind.value,
        "download",
        "completed",
        duration=perf_counter() - download_started,
    )
    if kind == MediaKind.PHOTO:
        record_media_operation(
            telemetry,
            kind.value,
            "prepare",
            "completed",
            duration=perf_counter() - started,
        )
        return PreparedMedia(work=work, image=media)
    route = routes[0]
    owned_provider = None
    if transcription_provider is None:
        if settings.llm_groq_api_key is None:
            return await fail(MediaFailureReason.UNAVAILABLE)
        owned_provider = OpenAICompatibleProvider(
            ProviderId.GROQ,
            route.model,
            settings.llm_groq_base_url,
            settings.llm_groq_api_key.get_secret_value(),
            httpx.Timeout(
                settings.telegram_media_transcription_timeout_seconds,
                connect=settings.llm_connect_timeout_seconds,
            ),
            0,
        )
    raw = transcription_provider or owned_provider
    assert raw is not None
    provider = GovernedTranscriptionProvider(
        raw,
        route,
        source,
        governance,
        settings,
        rate_limiter,
        concurrency_limiter,
        before_io,
        telemetry,
    )
    transcription_started = perf_counter()
    try:
        result = await provider.transcribe(
            TranscriptionRequest(
                media,
                settings.telegram_media_transcript_max_characters,
                work.attachment.duration_seconds or 0,
            )
        )
        if not await safety_preflight():
            return await fail(MediaFailureReason.PRIVACY_CHANGED)
        completed = await repository.finish_transcript(
            job_id, owner, attempt, token, result.text
        )
        if not completed:
            return PreparedMedia(work=work, failure=MediaFailureReason.STALE_LEASE)
        record_media_operation(
            telemetry,
            kind.value,
            "transcription",
            "completed",
            duration=perf_counter() - transcription_started,
        )
        record_media_operation(
            telemetry,
            kind.value,
            "prepare",
            "completed",
            duration=perf_counter() - started,
        )
        return PreparedMedia(work=work, transcript_changed=True)
    except ProviderError as error:
        reason = {
            ProviderErrorCategory.BUDGET_EXHAUSTED: MediaFailureReason.BUDGET_DENIED,
            ProviderErrorCategory.RATE_LIMITED: MediaFailureReason.RATE_LIMITED,
            ProviderErrorCategory.CONCURRENCY_LIMITED: (
                MediaFailureReason.CONCURRENCY_LIMITED
            ),
            ProviderErrorCategory.GOVERNANCE_UNAVAILABLE: (
                MediaFailureReason.UNAVAILABLE
            ),
        }.get(error.category, MediaFailureReason.AMBIGUOUS)
        record_media_operation(
            telemetry,
            kind.value,
            "transcription",
            "ambiguous" if reason == MediaFailureReason.AMBIGUOUS else "failed",
            reason=reason.value,
            duration=perf_counter() - transcription_started,
        )
        return await fail(reason)
    except MediaError as error:
        return await fail(error.reason)
    finally:
        if owned_provider is not None:
            await owned_provider.aclose()
