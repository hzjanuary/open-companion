"""Dedicated deterministic Telegram command worker.

It claims durable jobs, performs live authorization only for protected group
changes, and hands replies to the normal outbound delivery worker.
"""

import asyncio
import logging
import socket
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select

from app.application.commands import CommandOperation, command_response, parse_command
from app.application.memory import (
    MemoryValidationError,
    normalize_explicit_memory,
    normalize_personal_context,
)
from app.application.ports.concurrency import ConcurrencyLimiter
from app.application.ports.platform import PlatformAdapter, PlatformAdapterError
from app.application.ports.rate_limit import RateLimiter
from app.application.ports.telemetry import MetricsRecorder, NoOpMetricsRecorder
from app.application.ports.text_to_speech import (
    TextToSpeechError,
    TextToSpeechPort,
    TextToSpeechRequest,
)
from app.application.rate_limit_rules import text_to_speech_rules
from app.application.response_plan import ResponsePlanCandidate
from app.application.scheduling import (
    ScheduleValidationError,
    build_definition,
    format_local_time,
    parse_local_date,
    parse_local_time,
    validate_timezone,
    weekday_mask,
)
from app.application.semantic_memory import embedding_version
from app.core.config import Settings, get_settings
from app.domain.feedback import FeedbackOutcome, FeedbackValue
from app.domain.governance import (
    GROUP_EXPORT_CATEGORIES,
    SUBJECT_EXPORT_CATEGORIES,
    GovernanceScope,
)
from app.domain.persistence import (
    AssistantStatus,
    CommandAuthorizationOutcome,
    ConversationType,
    MemoryDeletionReason,
    MemoryKind,
    MemoryScope,
    PersonalityProfileStatus,
    PlatformConnectionStatus,
    ResponseMode,
    TenantStatus,
)
from app.domain.planning import PlanReasonCode, ProviderErrorCategory, ProviderId
from app.domain.provider_governance import (
    GovernanceMode,
    ProviderAttemptOutcome,
    ProviderOperation,
    RouteRole,
    WorkloadClass,
)
from app.domain.rate_limit import RateLimitDecision, RateLimitOperation
from app.domain.scheduling import (
    ALL_WEEKDAYS,
    RecurrenceKind,
    ScheduleCommandOutcome,
    ScheduleDefinition,
    ScheduleKind,
)
from app.domain.voice import VoiceFailureReason, VoiceFormat
from app.infrastructure.concurrency import (
    ConcurrencyUnavailable,
    RedisConcurrencyLimiter,
)
from app.infrastructure.database.commands import SqlAlchemyCommandRepository
from app.infrastructure.database.database import Database
from app.infrastructure.database.feedback import SqlAlchemyFeedbackRepository
from app.infrastructure.database.governance import (
    GovernanceErasureRecord,
    SqlAlchemyGovernanceRepository,
)
from app.infrastructure.database.group_configuration import ConfigurationChange
from app.infrastructure.database.memory import SqlAlchemyMemoryRepository
from app.infrastructure.database.models import (
    AssistantModel,
    ControlTenantModel,
    ConversationConfigurationRevisionModel,
    ConversationModel,
    MessageModel,
    ParticipantModel,
    PersonalityProfileModel,
    PersonalityProfileVersionModel,
    PlatformConnectionModel,
)
from app.infrastructure.database.privacy import SqlAlchemyPrivacyRepository
from app.infrastructure.database.provider_governance import (
    ProviderGovernanceUnavailable,
    SqlAlchemyProviderGovernanceRepository,
)
from app.infrastructure.database.regeneration import (
    RegenerationAdmission,
    SqlAlchemyRegenerationRepository,
)
from app.infrastructure.database.scheduling import SqlAlchemySchedulingRepository
from app.infrastructure.database.voice import (
    SqlAlchemyVoiceRepository,
    VoicePreparationOutcome,
)
from app.infrastructure.rate_limit import RateLimitUnavailable, RedisRateLimiter
from app.infrastructure.telegram.adapter import TelegramAdapter
from app.infrastructure.telemetry import InMemoryMetricsRecorder
from app.infrastructure.text_to_speech import OpenAITextToSpeechAdapter
from app.runtime.lifecycle import RuntimeLifecycle

logger = logging.getLogger(__name__)


def worker_name(settings: Settings) -> str:
    return f"{settings.command_owner_name}-{socket.gethostname()}"


async def consume_once(
    settings: Settings,
    database: Database,
    adapter: PlatformAdapter | None = None,
    owner: str | None = None,
    telemetry: MetricsRecorder | None = None,
    tts_provider: TextToSpeechPort | None = None,
    rate_limiter: RateLimiter | None = None,
    concurrency_limiter: ConcurrencyLimiter | None = None,
) -> int:
    if not settings.command_worker_enabled:
        return 0
    recorder = telemetry or NoOpMetricsRecorder()
    lease_owner = owner or worker_name(settings)
    repository = SqlAlchemyCommandRepository(database.session_factory)
    index_version = (
        embedding_version(
            settings.embedding_provider,
            settings.embedding_model,
            settings.embedding_dimension,
        )
        if settings.semantic_memory_enabled
        and settings.embedding_provider is not None
        and settings.embedding_model is not None
        else None
    )
    memory_repository = SqlAlchemyMemoryRepository(
        database.session_factory,
        index_version,
        settings.memory_control_batch_size,
    )
    stale_erasure_scopes = await SqlAlchemyGovernanceRepository(
        database.session_factory
    ).fail_stale_erasure_requests(limit=settings.command_batch_size)
    for scope in stale_erasure_scopes:
        recorder.increment(
            "january_governance_erasure_requests_total",
            scope=scope,
            outcome="failed",
        )
    jobs = await repository.claim(
        lease_owner, settings.command_batch_size, settings.command_lease_seconds
    )
    owns_adapter = adapter is None
    client: PlatformAdapter | None = None
    try:
        for job in jobs:
            request = parse_command(job.command_name, job.arguments)
            (
                language,
                conversation,
                participant,
                assistant,
                expected_revision,
            ) = await _load_state(database, job.id)
            if conversation is None or participant is None or assistant is None:
                await _finish(repository, job, lease_owner, "safe_failure", language)
                continue
            if request.operation == CommandOperation.USAGE:
                await _finish(repository, job, lease_owner, "usage", language)
                continue
            if request.operation == CommandOperation.UNKNOWN:
                await _finish(repository, job, lease_owner, "unknown", language)
                continue
            if request.operation == CommandOperation.REGENERATION:
                recorder.increment(
                    "january_regeneration_requests_total", outcome="requested"
                )
                regeneration_outcome = await SqlAlchemyRegenerationRepository(
                    database.session_factory
                ).accept(job.id, lease_owner)
                if regeneration_outcome == RegenerationAdmission.ACCEPTED:
                    recorder.increment(
                        "january_regeneration_requests_total", outcome="accepted"
                    )
                else:
                    recorder.increment(
                        "january_regeneration_requests_total",
                        outcome=(
                            "limit"
                            if regeneration_outcome
                            == RegenerationAdmission.LIMIT_REACHED
                            else "denied"
                        ),
                    )
                    await _finish(
                        repository,
                        job,
                        lease_owner,
                        "regeneration_limit_reached"
                        if regeneration_outcome == RegenerationAdmission.LIMIT_REACHED
                        else "regeneration_target_unavailable",
                        language,
                    )
                continue
            if request.operation == CommandOperation.VOICE:
                await _handle_voice_command(
                    settings,
                    database,
                    repository,
                    job,
                    lease_owner,
                    language,
                    recorder,
                    tts_provider,
                    rate_limiter,
                    concurrency_limiter,
                )
                continue
            if request.operation == CommandOperation.FEEDBACK:
                if not isinstance(request.value, FeedbackValue):
                    await _finish(repository, job, lease_owner, "usage", language)
                    continue
                feedback_outcome = await SqlAlchemyFeedbackRepository(
                    database.session_factory
                ).apply(
                    job.id,
                    lease_owner,
                    request.value,
                    saved_candidate=_candidate(
                        job.message_id, "feedback_saved", language
                    ),
                    no_change_candidate=_candidate(
                        job.message_id, "feedback_no_change", language
                    ),
                    limit_candidate=_candidate(
                        job.message_id, "feedback_limit_reached", language
                    ),
                    unavailable_candidate=_candidate(
                        job.message_id, "feedback_target_unavailable", language
                    ),
                )
                metric_outcome = (
                    request.value.value
                    if feedback_outcome == FeedbackOutcome.SAVED
                    else feedback_outcome.value
                )
                recorder.increment(
                    "january_conversation_feedback_total", outcome=metric_outcome
                )
                continue
            if request.operation == CommandOperation.MEMORY:
                try:
                    await _handle_memory_command(
                        database,
                        repository,
                        memory_repository,
                        job,
                        lease_owner,
                        request,
                        language,
                        conversation,
                        participant,
                        assistant,
                        settings,
                        adapter,
                        recorder,
                    )
                except Exception:
                    _record_memory_control(
                        recorder,
                        operation=_memory_metric_operation(request.action),
                        outcome="failed",
                        record_kind="none",
                        conversation=conversation,
                    )
                    # Database exceptions may embed bound memory/command text.
                    # Preserve the lease for existing restart/reclaim recovery,
                    # but never let those parameters reach a worker traceback.
                    raise RuntimeError("memory command failed") from None
                continue
            if request.operation == CommandOperation.GOVERNANCE:
                await _handle_governance_command(
                    database,
                    repository,
                    job,
                    lease_owner,
                    request,
                    language,
                    conversation,
                    participant,
                    settings,
                    adapter,
                    recorder,
                )
                continue
            if request.operation == CommandOperation.SCHEDULING:
                await _handle_scheduling_command(
                    repository,
                    SqlAlchemySchedulingRepository(database.session_factory),
                    job,
                    lease_owner,
                    request,
                    language,
                    conversation,
                    participant,
                    settings,
                    recorder,
                )
                continue
            protected = request.operation == CommandOperation.CONFIGURATION
            if protected and conversation.conversation_type != ConversationType.PRIVATE:
                if client is None:
                    client = adapter or TelegramAdapter(settings)
                try:
                    member = await client.get_chat_member(
                        conversation.platform_conversation_id,
                        participant.platform_user_id,
                    )
                except PlatformAdapterError as error:
                    if (
                        error.retryable
                        and job.attempt_count
                        < settings.command_max_authorization_attempts
                    ):
                        await repository.retry(
                            job.id,
                            lease_owner,
                            _authorization_retry_delay(settings, job.attempt_count),
                        )
                        continue
                    code = "temporary_failure" if error.retryable else "denied"
                    outcome = (
                        CommandAuthorizationOutcome.RETRYABLE_FAILURE
                        if error.retryable
                        else CommandAuthorizationOutcome.PERMANENT_FAILURE
                    )
                    await _finish(repository, job, lease_owner, code, language, outcome)
                    continue
                if not (member.is_administrator or member.is_owner):
                    await _finish(
                        repository,
                        job,
                        lease_owner,
                        "denied",
                        language,
                        CommandAuthorizationOutcome.DENIED,
                    )
                    continue
                authorization = CommandAuthorizationOutcome.ALLOWED
            else:
                authorization = None
            if request.operation == CommandOperation.PREFERENCE:
                value = request.value
                if not isinstance(value, bool):
                    await _finish(repository, job, lease_owner, "usage", language)
                    continue
                preference = (
                    (value, None) if request.name == "mentions" else (None, value)
                )
                await _finish(
                    repository,
                    job,
                    lease_owner,
                    "success",
                    language,
                    preference=preference,
                )
                continue
            if request.operation == CommandOperation.CONFIGURATION:
                if request.name in {"protect", "unprotect"}:
                    from app.infrastructure.database.safety_protection import (
                        SqlAlchemySafetyModerationRepository,
                    )

                    target_participant_id = await _protection_target(
                        database, conversation, job
                    )
                    if target_participant_id is None:
                        await _finish(
                            repository,
                            job,
                            lease_owner,
                            "member_missing",
                            language,
                            authorization,
                        )
                        continue
                    safety_repository = SqlAlchemySafetyModerationRepository(
                        database.session_factory
                    )
                    if request.name == "protect":
                        await safety_repository.protect(
                            conversation_id=conversation.id,
                            participant_id=target_participant_id,
                            actor_participant_id=participant.id,
                            source="telegram_command",
                        )
                        await _finish(
                            repository,
                            job,
                            lease_owner,
                            "protect_done",
                            language,
                            authorization,
                        )
                    else:
                        await safety_repository.restore_targeting(
                            conversation_id=conversation.id,
                            participant_id=target_participant_id,
                            actor_participant_id=participant.id,
                            source="telegram_command",
                        )
                        await _finish(
                            repository,
                            job,
                            lease_owner,
                            "unprotect_done",
                            language,
                            authorization,
                        )
                    continue
                if request.name == "personality":
                    profile_version_id, profile_code = await _resolve_profile_version(
                        database,
                        assistant.id,
                        request.value,
                    )
                    if profile_version_id is None:
                        await _finish(
                            repository,
                            job,
                            lease_owner,
                            profile_code,
                            language,
                            authorization,
                        )
                        continue
                    change = ConfigurationChange(
                        profile_version_id=profile_version_id,
                        source="telegram_command",
                        actor_participant_id=participant.id,
                    )
                    await repository.complete_configuration(
                        job.id,
                        lease_owner,
                        assistant.id,
                        change,
                        _candidate(job.message_id, "success", language),
                        authorization,
                        expected_revision=expected_revision,
                        unchanged_candidate=_candidate(
                            job.message_id, "unchanged", language
                        ),
                        conflict_candidate=_candidate(
                            job.message_id, "conflict", language
                        ),
                    )
                    continue
                code, configuration_change, resume = _configuration_change(
                    settings, participant, request
                )
                if configuration_change is None:
                    await _finish(
                        repository, job, lease_owner, code, language, authorization
                    )
                    continue
                await repository.complete_configuration(
                    job.id,
                    lease_owner,
                    assistant.id,
                    configuration_change,
                    _candidate(job.message_id, code, language),
                    authorization,
                    expected_revision=expected_revision,
                    unchanged_candidate=_candidate(
                        job.message_id, "unchanged", language
                    ),
                    conflict_candidate=_candidate(job.message_id, "conflict", language),
                    resume=resume,
                )
                continue
            code = (
                "help"
                if request.name == "help"
                else "start"
                if request.name == "start"
                else "success"
            )
            if request.name in {
                "status",
                "mode",
                "personality",
                "stickers",
                "mentions",
                "teasing",
                "safety",
            }:
                code = "status"
            detail = await _read_detail(
                database,
                conversation,
                participant,
                assistant,
                request,
                settings.command_max_profiles_shown,
            )
            await _finish(repository, job, lease_owner, code, language, detail=detail)
    finally:
        if owns_adapter and isinstance(client, TelegramAdapter):
            await client.aclose()
    return len(jobs)


async def _handle_voice_command(
    settings: Settings,
    database: Database,
    command_repository: SqlAlchemyCommandRepository,
    job: object,
    owner: str,
    language: str,
    recorder: MetricsRecorder,
    tts_provider: TextToSpeechPort | None,
    rate_limiter: RateLimiter | None,
    concurrency_limiter: ConcurrencyLimiter | None,
) -> None:
    from app.infrastructure.database.models import TelegramCommandJobModel

    assert isinstance(job, TelegramCommandJobModel)
    voice = SqlAlchemyVoiceRepository(database.session_factory)
    if (
        not settings.telegram_voice_tts_enabled
        or tts_provider is None
        or rate_limiter is None
        or concurrency_limiter is None
    ):
        recorder.increment("january_tts_admission_total", outcome="unsupported")
        await _finish(command_repository, job, owner, "voice_tts_unsupported", language)
        return
    preparation = await voice.prepare(job.id, owner, settings.command_lease_seconds)
    if preparation.outcome == VoicePreparationOutcome.TARGET_UNAVAILABLE:
        recorder.increment("january_tts_admission_total", outcome="target_unavailable")
        await _finish(
            command_repository, job, owner, "voice_target_unavailable", language
        )
        return
    if preparation.outcome == VoicePreparationOutcome.TOO_LONG:
        recorder.increment("january_tts_admission_total", outcome="too_long")
        await _finish(command_repository, job, owner, "voice_too_long", language)
        return
    if preparation.outcome == VoicePreparationOutcome.GENERATION_UNCERTAIN:
        recorder.increment("january_tts_admission_total", outcome="uncertain")
        await _finish(
            command_repository,
            job,
            owner,
            "voice_tts_generation_uncertain",
            language,
        )
        return
    if preparation.outcome == VoicePreparationOutcome.TERMINAL:
        return
    assert preparation.job_id is not None
    assert preparation.source_text is not None
    assert preparation.participant_id is not None
    governance = SqlAlchemyProviderGovernanceRepository(
        database.session_factory,
        mode=GovernanceMode.ENFORCE,
        reservation_lease_seconds=settings.provider_reservation_lease_seconds,
    )
    source = await governance.voice_source(preparation.job_id)
    assert source.connection_id is not None
    requirements: dict[str, object] = {
        "text_to_speech": True,
        "voice_format": "ogg_opus",
        "maximum_input_characters": settings.telegram_voice_tts_source_max_characters,
        "maximum_output_bytes": settings.telegram_voice_tts_output_max_bytes,
        "allowed_data_classes": ["approved_external"],
        "require_current_health": True,
    }
    try:
        routes = await governance.resolve_routes(
            source, WorkloadClass.TEXT_TO_SPEECH, requirements
        )
    except ProviderGovernanceUnavailable:
        routes = ()
    if not routes or routes[0].adapter_key != ProviderId.OPENAI:
        await voice.finish_failure(
            preparation.job_id,
            owner,
            reason=VoiceFailureReason.UNSUPPORTED,
        )
        recorder.increment("january_tts_admission_total", outcome="unsupported")
        await _finish(command_repository, job, owner, "voice_tts_unsupported", language)
        return
    route = routes[0]
    admission = await governance.reserve_attempt(
        source,
        route,
        WorkloadClass.TEXT_TO_SPEECH,
        ProviderOperation.VOICE_SYNTHESIS,
        RouteRole.PRIMARY,
        1,
        None,
        None,
    )
    if not admission.allowed:
        await voice.finish_failure(
            preparation.job_id,
            owner,
            reason=VoiceFailureReason.ADMISSION_DENIED,
        )
        recorder.increment(
            "january_tts_admission_total", outcome=admission.outcome.value
        )
        await _finish(
            command_repository,
            job,
            owner,
            "voice_tts_admission_denied",
            language,
        )
        return
    if not await voice.bind_provider_attempt(
        preparation.job_id, owner, admission.attempt_id
    ):
        await governance.finish_no_io(
            admission.attempt_id, ProviderAttemptOutcome.GOVERNANCE_UNAVAILABLE
        )
        await _finish(
            command_repository,
            job,
            owner,
            "voice_tts_admission_denied",
            language,
        )
        return
    try:
        rate_decision = await rate_limiter.check(
            RateLimitOperation.TEXT_TO_SPEECH,
            text_to_speech_rules(
                settings,
                connection_id=source.connection_id,
                conversation_id=job.conversation_id,
                participant_id=preparation.participant_id,
                provider_id=route.provider_id.value,
            ),
        )
    except RateLimitUnavailable:
        rate_decision = RateLimitDecision(
            False,
            retry_after_seconds=settings.rate_limit_redis_failure_retry_seconds,
        )
    await governance.record_rate_decision(
        source, RateLimitOperation.TEXT_TO_SPEECH, route.provider_id, rate_decision
    )
    if not rate_decision.allowed:
        await governance.finish_no_io(
            admission.attempt_id, ProviderAttemptOutcome.RATE_LIMITED
        )
        await voice.finish_failure(
            preparation.job_id,
            owner,
            reason=VoiceFailureReason.ADMISSION_DENIED,
        )
        recorder.increment("january_tts_admission_total", outcome="rate_limited")
        await _finish(
            command_repository,
            job,
            owner,
            "voice_tts_admission_denied",
            language,
        )
        return
    try:
        concurrency_lease = await concurrency_limiter.acquire(route.provider_id)
    except ConcurrencyUnavailable:
        concurrency_lease = None
    if concurrency_lease is None:
        await governance.finish_no_io(
            admission.attempt_id, ProviderAttemptOutcome.CONCURRENCY_LIMITED
        )
        await voice.finish_failure(
            preparation.job_id,
            owner,
            reason=VoiceFailureReason.ADMISSION_DENIED,
        )
        recorder.increment("january_tts_admission_total", outcome="concurrency_limited")
        await _finish(
            command_repository,
            job,
            owner,
            "voice_tts_admission_denied",
            language,
        )
        return
    try:
        if not await governance.mark_io_started(admission.attempt_id, owner):
            await voice.finish_failure(
                preparation.job_id,
                owner,
                reason=VoiceFailureReason.ADMISSION_DENIED,
            )
            await _finish(
                command_repository,
                job,
                owner,
                "voice_tts_admission_denied",
                language,
            )
            return
        if not await voice.mark_io_started(preparation.job_id, owner):
            await voice.finish_failure(
                preparation.job_id,
                owner,
                reason=VoiceFailureReason.PROVIDER_UNCERTAIN,
                uncertain=True,
            )
            await _finish(
                command_repository,
                job,
                owner,
                "voice_tts_generation_uncertain",
                language,
            )
            return
        recorder.increment("january_tts_admission_total", outcome="allowed")
        try:
            result = await tts_provider.synthesize(
                TextToSpeechRequest(
                    text=preparation.source_text,
                    model=route.model,
                    voice=settings.telegram_voice_tts_voice,
                    format=VoiceFormat.OGG_OPUS,
                    maximum_bytes=settings.telegram_voice_tts_output_max_bytes,
                )
            )
        except TextToSpeechError as error:
            if not error.io_possible:
                await governance.finish_io(
                    admission.attempt_id,
                    outcome=(
                        ProviderAttemptOutcome.INVALID_OUTPUT
                        if error.category == ProviderErrorCategory.MALFORMED_RESPONSE
                        else ProviderAttemptOutcome.PROVIDER_ERROR
                    ),
                    input_tokens=None,
                    output_tokens=None,
                    total_tokens=None,
                    provider_request_id=None,
                    retryable=False,
                    error_category=error.category.value,
                )
            await voice.finish_failure(
                preparation.job_id,
                owner,
                reason=(
                    VoiceFailureReason.PROVIDER_UNCERTAIN
                    if error.io_possible
                    else VoiceFailureReason.PROVIDER_FAILED
                ),
                uncertain=error.io_possible,
            )
            recorder.increment(
                "january_tts_results_total",
                outcome="uncertain" if error.io_possible else "failed",
                provider=route.provider_id.value,
            )
            await _finish(
                command_repository,
                job,
                owner,
                "voice_tts_generation_uncertain"
                if error.io_possible
                else "voice_tts_generation_failed",
                language,
            )
            return
        if result.provider != route.provider_id or result.model != route.model:
            await governance.finish_io(
                admission.attempt_id,
                outcome=ProviderAttemptOutcome.INVALID_OUTPUT,
                input_tokens=None,
                output_tokens=None,
                total_tokens=None,
                provider_request_id=result.provider_request_id,
                retryable=False,
                error_category=ProviderErrorCategory.MALFORMED_RESPONSE.value,
            )
            await voice.finish_failure(
                preparation.job_id,
                owner,
                reason=VoiceFailureReason.PROVIDER_FAILED,
            )
            recorder.increment(
                "january_tts_results_total",
                outcome="failed",
                provider=route.provider_id.value,
            )
            await _finish(
                command_repository,
                job,
                owner,
                "voice_tts_generation_failed",
                language,
            )
            return
        completion = await governance.finish_io(
            admission.attempt_id,
            outcome=ProviderAttemptOutcome.SUCCESS,
            input_tokens=None,
            output_tokens=None,
            total_tokens=None,
            provider_request_id=result.provider_request_id,
            retryable=False,
            error_category=None,
        )
        activated = completion is not None and await voice.activate(
            preparation.job_id, owner, result, language=language
        )
        await governance.set_application_outcome(
            admission.attempt_id, "accepted" if activated else "invalid_output"
        )
        recorder.increment(
            "january_tts_results_total",
            outcome="success" if activated else "stale",
            provider=route.provider_id.value,
        )
        if not activated:
            await _finish(
                command_repository,
                job,
                owner,
                "voice_target_unavailable",
                language,
            )
    finally:
        try:
            await concurrency_limiter.release(concurrency_lease)
        except ConcurrencyUnavailable:
            recorder.increment(
                "january_provider_concurrency_events_total",
                provider=route.provider_id.value,
                outcome="unavailable",
            )


async def _handle_scheduling_command(
    commands: SqlAlchemyCommandRepository,
    schedules: SqlAlchemySchedulingRepository,
    job: object,
    owner: str,
    request: object,
    language: str,
    conversation: ConversationModel,
    participant: ParticipantModel,
    settings: Settings,
    telemetry: MetricsRecorder,
) -> None:
    """Execute exact-private scheduling commands without provider I/O."""

    from datetime import UTC, datetime

    from app.application.commands import CommandRequest
    from app.infrastructure.database.models import TelegramCommandJobModel

    assert isinstance(job, TelegramCommandJobModel)
    assert isinstance(request, CommandRequest)
    if not settings.proactive_scheduling_enabled:
        _record_schedule_command(telemetry, request.action, "denied")
        await _finish(commands, job, owner, "schedule_disabled", language)
        return
    if conversation.conversation_type != ConversationType.PRIVATE:
        _record_schedule_command(telemetry, request.action, "denied")
        await _finish(commands, job, owner, "schedule_private", language)
        return
    if participant.privacy_deleted_at is not None:
        _record_schedule_command(telemetry, request.action, "denied")
        await _finish(commands, job, owner, "denied", language)
        return
    now = datetime.now(UTC)
    preferences = await schedules.preferences(conversation.id, participant.id)
    if request.action == "timezone_status":
        detail = f" {preferences.timezone_name or 'not_set'}"
        _record_schedule_command(telemetry, request.action, "success")
        await _finish(commands, job, owner, "schedule_status", language, detail=detail)
        return
    if request.action == "quiet_status":
        state = "off"
        if preferences.quiet_hours_enabled:
            state = (
                f"{format_local_time(preferences.quiet_start_minute)}-"
                f"{format_local_time(preferences.quiet_end_minute)}"
            )
        _record_schedule_command(telemetry, request.action, "success")
        await _finish(
            commands, job, owner, "schedule_status", language, detail=f" {state}"
        )
        return
    if request.action in {"reminders_list", "checkins_status"}:
        values = await schedules.list_active(conversation.id, participant.id)
        if request.action == "reminders_list":
            values = [item for item in values if item.kind == ScheduleKind.REMINDER]
        else:
            values = [item for item in values if item.kind == ScheduleKind.CHECK_IN]
        detail = _schedule_list_detail(values)
        _record_schedule_command(telemetry, request.action, "success")
        await _finish(commands, job, owner, "schedule_status", language, detail=detail)
        return
    try:
        if request.action == "timezone_set":
            if not isinstance(request.value, str):
                raise ScheduleValidationError("timezone value is invalid")
            result = await schedules.set_timezone(
                command_job_id=job.id,
                conversation_id=conversation.id,
                participant_id=participant.id,
                timezone_name=validate_timezone(request.value),
                now=now,
            )
            code = (
                "unchanged"
                if result.outcome == ScheduleCommandOutcome.UNCHANGED
                else "success"
            )
        elif request.action in {"quiet_set", "quiet_off"}:
            if request.action == "quiet_off":
                enabled, start, end = False, 1320, 480
            elif (
                isinstance(request.value, tuple)
                and len(request.value) == 2
                and all(isinstance(value, str) for value in request.value)
            ):
                enabled, start, end = (
                    True,
                    parse_local_time(request.value[0]),
                    parse_local_time(request.value[1]),
                )
            else:
                raise ScheduleValidationError("quiet-hours value is invalid")
            result = await schedules.set_quiet_hours(
                command_job_id=job.id,
                conversation_id=conversation.id,
                participant_id=participant.id,
                enabled=enabled,
                start_minute=start,
                end_minute=end,
            )
            code = (
                "unchanged"
                if result.outcome == ScheduleCommandOutcome.UNCHANGED
                else "success"
            )
        elif request.action == "reminder_cancel":
            if not isinstance(request.value, str):
                raise ScheduleValidationError("reminder identifier is invalid")
            result = await schedules.cancel_reminder(
                command_job_id=job.id,
                conversation_id=conversation.id,
                participant_id=participant.id,
                public_id=request.value,
                now=now,
            )
            code = (
                "schedule_cancelled"
                if result.outcome == ScheduleCommandOutcome.CANCELLED
                else "schedule_too_late"
                if result.outcome == ScheduleCommandOutcome.TOO_LATE
                else "schedule_not_found"
            )
        elif request.action == "checkins_off":
            result = await schedules.disable_checkin(
                command_job_id=job.id,
                conversation_id=conversation.id,
                participant_id=participant.id,
                now=now,
            )
            code = "schedule_checkins_off"
        else:
            if preferences.timezone_name is None:
                _record_schedule_command(telemetry, request.action, "invalid")
                await _finish(
                    commands,
                    job,
                    owner,
                    "schedule_timezone_required",
                    language,
                )
                return
            definition = _schedule_definition(
                request, preferences.timezone_name, now, settings
            )
            if definition.kind == ScheduleKind.REMINDER:
                result = await schedules.create_reminder(
                    command_job_id=job.id,
                    conversation_id=conversation.id,
                    participant_id=participant.id,
                    definition=definition,
                    active_limit=settings.scheduler_active_reminder_limit,
                )
                code = (
                    "schedule_limit"
                    if result.outcome == ScheduleCommandOutcome.LIMIT_REACHED
                    else "schedule_created"
                )
            else:
                result = await schedules.enable_checkin(
                    command_job_id=job.id,
                    conversation_id=conversation.id,
                    participant_id=participant.id,
                    definition=definition,
                )
                code = "schedule_checkins_on"
        schedule_detail = f" {result.public_id}" if result.public_id else None
        _record_schedule_command(telemetry, request.action, result.outcome.value)
        await _finish(commands, job, owner, code, language, detail=schedule_detail)
    except ScheduleValidationError:
        code = (
            "schedule_timezone_invalid"
            if request.action == "timezone_set"
            else "schedule_too_late"
        )
        _record_schedule_command(telemetry, request.action, "invalid")
        await _finish(commands, job, owner, code, language)


def _schedule_definition(
    request: object, timezone_name: str, now: object, settings: Settings
) -> ScheduleDefinition:
    from datetime import datetime

    from app.application.commands import CommandRequest

    assert isinstance(request, CommandRequest)
    assert isinstance(now, datetime)
    local_date = None
    weekdays = 0
    reminder_text = None
    if request.action == "reminder_once" and isinstance(request.value, tuple):
        raw_date, raw_time, reminder_text = request.value
        recurrence = RecurrenceKind.ONCE
        local_date = parse_local_date(str(raw_date))
    elif request.action == "reminder_daily" and isinstance(request.value, tuple):
        raw_time, reminder_text = request.value
        recurrence = RecurrenceKind.DAILY
        weekdays = ALL_WEEKDAYS
    elif request.action == "reminder_weekly" and isinstance(request.value, tuple):
        raw_weekdays, raw_time, reminder_text = request.value
        recurrence = RecurrenceKind.WEEKLY
        weekdays = weekday_mask(str(raw_weekdays))
    elif request.action == "checkins_daily" and isinstance(request.value, str):
        raw_time = request.value
        recurrence = RecurrenceKind.DAILY
        weekdays = ALL_WEEKDAYS
    elif request.action == "checkins_weekly" and isinstance(request.value, tuple):
        raw_weekdays, raw_time = request.value
        recurrence = RecurrenceKind.WEEKLY
        weekdays = weekday_mask(str(raw_weekdays))
    else:
        raise ScheduleValidationError("schedule command value is invalid")
    kind = (
        ScheduleKind.CHECK_IN
        if request.action.startswith("checkins_")
        else ScheduleKind.REMINDER
    )
    return build_definition(
        kind=kind,
        recurrence=recurrence,
        timezone_name=timezone_name,
        local_date=local_date,
        local_time_minute=parse_local_time(str(raw_time)),
        weekday_mask_value=weekdays,
        reminder_text=str(reminder_text) if reminder_text is not None else None,
        now=now,
        minimum_lead_seconds=settings.scheduler_minimum_lead_seconds,
        horizon_days=settings.scheduler_horizon_days,
        text_limit=settings.scheduler_reminder_text_limit,
    )


def _schedule_list_detail(values: Sequence[object]) -> str:
    from app.domain.scheduling import ScheduleView

    if not values:
        return " none"
    parts: list[str] = []
    for value in values[:10]:
        assert isinstance(value, ScheduleView)
        parts.append(
            f" {value.public_id} {value.kind.value}/{value.recurrence.value} "
            f"{format_local_time(value.local_time_minute)} {value.timezone_name};"
        )
    if len(values) > 10:
        parts.append(" more=1")
    return "".join(parts)


def _record_schedule_command(
    telemetry: MetricsRecorder, operation: str, outcome: str
) -> None:
    telemetry.increment(
        "january_schedule_commands_total", operation=operation, outcome=outcome
    )


async def _handle_memory_command(
    database: Database,
    commands: SqlAlchemyCommandRepository,
    memories: SqlAlchemyMemoryRepository,
    job: object,
    owner: str,
    request: object,
    language: str,
    conversation: ConversationModel,
    participant: ParticipantModel,
    assistant: AssistantModel,
    settings: Settings,
    adapter: PlatformAdapter | None,
    telemetry: MetricsRecorder,
) -> None:
    """Execute only explicit-memory commands; none construct a provider request."""

    from app.application.commands import CommandRequest
    from app.infrastructure.database.models import TelegramCommandJobModel

    assert isinstance(job, TelegramCommandJobModel)
    assert isinstance(request, CommandRequest)
    scope = (
        MemoryScope.PRIVATE_CONVERSATION
        if conversation.conversation_type == ConversationType.PRIVATE
        else MemoryScope.GROUP_CONVERSATION
    )
    common = {
        "assistant_id": assistant.id,
        "platform_connection_id": conversation.platform_connection_id,
        "conversation_id": conversation.id,
    }
    if request.action in {"summary", "recall_status"}:
        summary = await memories.status_for_participant(
            **common, participant_id=participant.id
        )
        detail = (
            f" recall={'on' if summary.recall_enabled else 'off'}; "
            f"owned={summary.owned_explicit}; shared={summary.shared_explicit}; "
            f"personal={summary.personal_context}; commands: /memory list; "
            "/memory remember <fact>; /memory context add <key> <value>; "
            "/memory update <id> <revision> <content>; "
            "/memory delete <id> <revision>; /memory clear_mine confirm; "
            "/memory recall status|off|on; /forget <id>."
        )
        _record_memory_control(
            telemetry,
            operation="status",
            outcome="success",
            record_kind="none",
            conversation=conversation,
        )
        await _finish(commands, job, owner, "memory_summary", language, detail=detail)
        return
    if request.action == "list":
        items = await memories.active_for_conversation(
            **common, viewer_participant_id=participant.id, limit=11
        )
        detail = _memory_list_detail(items[:10], more=len(items) > 10)
        _record_memory_control(
            telemetry,
            operation="list",
            outcome="success",
            record_kind="none",
            conversation=conversation,
        )
        await _finish(commands, job, owner, "memory_summary", language, detail=detail)
        return
    if request.action == "remember":
        if not isinstance(request.value, str):
            await _finish(commands, job, owner, "usage", language)
            return
        try:
            draft = normalize_explicit_memory(request.value, scope)
        except MemoryValidationError:
            _record_memory_control(
                telemetry,
                operation="create",
                outcome="invalid",
                record_kind="explicit_fact",
                conversation=conversation,
            )
            await _finish(commands, job, owner, "usage", language)
            return
        item = await memories.create(
            **common,
            creator_participant_id=participant.id,
            source_message_id=job.message_id,
            source_command_job_id=job.id,
            draft=draft,
        )
        _record_memory_control(
            telemetry,
            operation="create",
            outcome="success",
            record_kind="explicit_fact",
            conversation=conversation,
        )
        await _finish(
            commands,
            job,
            owner,
            "memory_saved",
            language,
            # This command created revision 1. A replay after a later edit must
            # not acknowledge that later revision as this command's effect.
            detail=f" id={item.public_id}; revision=1",
        )
        return
    if request.action == "context_create":
        if (
            not isinstance(request.value, tuple)
            or len(request.value) != 2
            or not all(isinstance(value, str) for value in request.value)
        ):
            await _finish(commands, job, owner, "usage", language)
            return
        key, content = request.value
        try:
            personal_draft = normalize_personal_context(key, content)
            context_result = await memories.create_personal_context(
                **common,
                creator_participant_id=participant.id,
                source_message_id=job.message_id,
                source_command_job_id=job.id,
                draft=personal_draft,
            )
        except MemoryValidationError:
            _record_memory_control(
                telemetry,
                operation="create",
                outcome="invalid",
                record_kind="personal_context",
                conversation=conversation,
            )
            await _finish(commands, job, owner, "usage", language)
            return
        code = (
            "memory_context_private"
            if context_result.outcome == "scope_denied"
            else "memory_conflict"
            if context_result.outcome == "conflict"
            else "memory_context_saved"
        )
        _record_memory_control(
            telemetry,
            operation="create",
            outcome=(
                "scope_denied"
                if context_result.outcome == "scope_denied"
                else "conflict"
                if context_result.outcome == "conflict"
                else "success"
            ),
            record_kind="personal_context",
            conversation=conversation,
        )
        context_public_id = context_result.public_id
        context_detail = (
            f" id={context_public_id}; revision={context_result.revision}"
            if context_public_id is not None
            else None
        )
        await _finish(commands, job, owner, code, language, detail=context_detail)
        return
    if request.action == "update":
        if (
            not isinstance(request.value, tuple)
            or len(request.value) != 3
            or not isinstance(request.value[0], str)
            or not isinstance(request.value[1], int)
            or not isinstance(request.value[2], str)
        ):
            await _finish(commands, job, owner, "usage", language)
            return
        public_id, expected_revision, content = request.value
        try:
            update_result = await memories.update_owned(
                **common,
                actor_id=participant.id,
                command_job_id=job.id,
                public_id=public_id,
                expected_revision=expected_revision,
                content=content,
            )
        except MemoryValidationError:
            _record_memory_control(
                telemetry,
                operation="update",
                outcome="invalid",
                record_kind="none",
                conversation=conversation,
            )
            await _finish(commands, job, owner, "usage", language)
            return
        code = {
            "updated": "memory_updated",
            "conflict": "memory_conflict",
            "denied": "denied",
        }.get(update_result.outcome, "memory_missing")
        _record_memory_control(
            telemetry,
            operation="update",
            outcome=(
                "success"
                if update_result.outcome == "updated"
                else update_result.outcome
            ),
            record_kind="none",
            conversation=conversation,
        )
        await _finish(
            commands,
            job,
            owner,
            code,
            language,
            detail=(
                f" id={update_result.public_id}; revision={update_result.revision}"
                if update_result.public_id is not None
                else None
            ),
        )
        return
    if request.action == "delete":
        if (
            not isinstance(request.value, tuple)
            or len(request.value) != 2
            or not isinstance(request.value[0], str)
            or not isinstance(request.value[1], int)
        ):
            await _finish(commands, job, owner, "usage", language)
            return
        delete_result = await memories.delete_owned(
            **common,
            actor_id=participant.id,
            command_job_id=job.id,
            public_id=request.value[0],
            expected_revision=request.value[1],
        )
        code = {
            "deleted": "memory_deleted",
            "conflict": "memory_conflict",
            "denied": "denied",
        }.get(delete_result.outcome, "memory_missing")
        _record_memory_control(
            telemetry,
            operation="delete",
            outcome=(
                "success"
                if delete_result.outcome == "deleted"
                else delete_result.outcome
            ),
            record_kind="none",
            conversation=conversation,
        )
        await _finish(commands, job, owner, code, language)
        return
    if request.action == "clear_mine":
        clear_result = await memories.clear_owned(
            **common, actor_id=participant.id, command_job_id=job.id
        )
        _record_memory_control(
            telemetry,
            operation="clear",
            outcome="success",
            record_kind="none",
            conversation=conversation,
        )
        await _finish(
            commands,
            job,
            owner,
            "memory_cleared",
            language,
            detail=f" count={clear_result.affected_count}",
        )
        return
    if request.action in {"recall_status", "recall_on", "recall_off"}:
        recall_result = (
            await memories.recall_status(**common, participant_id=participant.id)
            if request.action == "recall_status"
            else await memories.set_recall(
                **common,
                participant_id=participant.id,
                command_job_id=job.id,
                enabled=request.action == "recall_on",
            )
        )
        enabled = recall_result.recall_enabled is not False
        operation = (
            "status"
            if request.action == "recall_status"
            else "recall_enable"
            if enabled
            else "recall_disable"
        )
        _record_memory_control(
            telemetry,
            operation=operation,
            outcome=(
                "success"
                if request.action == "recall_status"
                else "unchanged"
                if recall_result.outcome == "unchanged"
                else "success"
            ),
            record_kind="recall_policy",
            conversation=conversation,
        )
        await _finish(
            commands,
            job,
            owner,
            "memory_recall_enabled" if enabled else "memory_recall_disabled",
            language,
            detail=f" revision={recall_result.revision}",
        )
        return
    if request.action == "forget":
        if not isinstance(request.value, str):
            await _finish(commands, job, owner, "usage", language)
            return
        target = await memories.resolve_active(**common, public_id=request.value)
        if target is None:
            await _finish(commands, job, owner, "memory_missing", language)
            return
        is_creator = target.creator_participant_id == participant.id
        if (
            not is_creator
            and conversation.conversation_type == ConversationType.PRIVATE
        ):
            await _finish(commands, job, owner, "denied", language)
            return
        if not is_creator:
            authorized = await _fresh_group_admin(
                commands,
                job,
                owner,
                language,
                conversation,
                participant,
                settings,
                adapter,
            )
            if not authorized:
                return
        deleted = await memories.delete(
            **common,
            public_id=request.value,
            actor_id=participant.id,
            command_job_id=job.id,
            reason=(
                MemoryDeletionReason.CREATOR_REQUEST
                if is_creator
                else MemoryDeletionReason.USER_REQUEST
            ),
        )
        await _finish(
            commands,
            job,
            owner,
            "memory_deleted" if deleted else "memory_missing",
            language,
        )
        return
    if request.action == "reset_group":
        if conversation.conversation_type == ConversationType.PRIVATE:
            await _finish(commands, job, owner, "memory_private_reset", language)
            return
        authorized = await _fresh_group_admin(
            commands,
            job,
            owner,
            language,
            conversation,
            participant,
            settings,
            adapter,
        )
        if not authorized:
            return
        try:
            erasure = await _begin_erasure(
                database,
                telemetry,
                scope=GovernanceScope.GROUP,
                conversation_id=conversation.id,
                participant_id=participant.id,
                command_job_id=job.id,
                lease_owner=owner,
                lease_seconds=settings.command_lease_seconds,
            )
        except Exception:  # noqa: BLE001 - fail closed with bounded telemetry
            telemetry.increment(
                "january_governance_erasure_requests_total",
                scope=GovernanceScope.GROUP.value,
                outcome="failed",
            )
            await _finish(commands, job, owner, "safe_failure", language)
            return
        if erasure.status == "complete":
            await _finish(
                commands, job, owner, "memory_reset", language, detail=" count=0"
            )
            return
        try:
            count = await memories.reset_group(
                **common,
                actor_id=participant.id,
                command_job_id=job.id,
            )
        except Exception:  # noqa: BLE001 - record a durable failure
            logger.warning(
                "group_reset_failed conversation=%s",
                conversation.id,
            )
            await _fail_erasure(
                database,
                telemetry,
                erasure_id=erasure.id,
                lease_owner=owner,
                scope=GovernanceScope.GROUP,
                conversation_id=conversation.id,
                participant_id=participant.id,
            )
            await _finish(commands, job, owner, "safe_failure", language)
            return
        await _complete_erasure(
            database,
            telemetry,
            erasure_id=erasure.id,
            lease_owner=owner,
            scope=GovernanceScope.GROUP,
            conversation_id=conversation.id,
            participant_id=participant.id,
        )
        await _finish(
            commands, job, owner, "memory_reset", language, detail=f" count={count}"
        )
        return
    if request.action == "warning":
        await _finish(commands, job, owner, "forget_me_warning", language)
        return
    if request.action == "confirm":
        index_version = (
            embedding_version(
                settings.embedding_provider,
                settings.embedding_model,
                settings.embedding_dimension,
            )
            if settings.semantic_memory_enabled
            and settings.embedding_provider is not None
            and settings.embedding_model is not None
            else None
        )
        try:
            erasure = await _begin_erasure(
                database,
                telemetry,
                scope=GovernanceScope.SUBJECT,
                conversation_id=conversation.id,
                participant_id=participant.id,
                command_job_id=job.id,
                lease_owner=owner,
                lease_seconds=settings.command_lease_seconds,
            )
        except Exception:  # noqa: BLE001 - fail closed with bounded telemetry
            telemetry.increment(
                "january_governance_erasure_requests_total",
                scope=GovernanceScope.SUBJECT.value,
                outcome="failed",
            )
            await _finish(commands, job, owner, "safe_failure", language)
            return
        if erasure.status == "complete":
            await _finish(commands, job, owner, "forget_me_unchanged", language)
            return
        try:
            privacy_result = await SqlAlchemyPrivacyRepository(
                database.session_factory, index_version
            ).erase_subject(
                assistant_id=assistant.id,
                platform_connection_id=conversation.platform_connection_id,
                platform_user_id=participant.platform_user_id,
                command_job_id=job.id,
            )
        except Exception:  # noqa: BLE001 - record a durable failure
            logger.warning(
                "subject_erasure_failed conversation=%s",
                conversation.id,
            )
            await _fail_erasure(
                database,
                telemetry,
                erasure_id=erasure.id,
                lease_owner=owner,
                scope=GovernanceScope.SUBJECT,
                conversation_id=conversation.id,
                participant_id=participant.id,
            )
            await _finish(commands, job, owner, "safe_failure", language)
            return
        await _complete_erasure(
            database,
            telemetry,
            erasure_id=erasure.id,
            lease_owner=owner,
            scope=GovernanceScope.SUBJECT,
            conversation_id=conversation.id,
            participant_id=participant.id,
        )
        await _finish(
            commands,
            job,
            owner,
            "forget_me_unchanged"
            if privacy_result.already_deleted
            else "forget_me_done",
            language,
        )
        return
    await _finish(commands, job, owner, "safe_failure", language)


async def _begin_erasure(
    database: Database,
    telemetry: MetricsRecorder,
    *,
    scope: GovernanceScope,
    conversation_id: UUID,
    participant_id: UUID,
    command_job_id: UUID,
    lease_owner: str,
    lease_seconds: int,
) -> GovernanceErasureRecord:
    """Create a durable content-free erasure record and its audit trail (FR-06)."""

    governance = SqlAlchemyGovernanceRepository(database.session_factory)
    record = await governance.create_erasure_request(
        scope=scope,
        conversation_id=conversation_id,
        participant_id=participant_id,
        requested_via="telegram_command",
        source_command_job_id=command_job_id,
    )
    if record.created:
        telemetry.increment(
            "january_governance_erasure_requests_total",
            scope=scope.value,
            outcome="requested",
        )
    if record.status != "complete":
        claimed = await governance.mark_erasure_in_progress(
            record.id,
            lease_owner=lease_owner,
            lease_seconds=lease_seconds,
        )
        if not claimed:
            raise RuntimeError("erasure request has an active lease")
        telemetry.increment(
            "january_governance_erasure_requests_total",
            scope=scope.value,
            outcome="in_progress",
        )
    return record


async def _complete_erasure(
    database: Database,
    telemetry: MetricsRecorder,
    *,
    erasure_id: UUID,
    lease_owner: str,
    scope: GovernanceScope,
    conversation_id: UUID,
    participant_id: UUID,
) -> None:
    governance = SqlAlchemyGovernanceRepository(database.session_factory)
    completed = await governance.complete_erasure_request(
        erasure_id, lease_owner=lease_owner
    )
    if not completed:
        return
    telemetry.increment(
        "january_governance_erasure_requests_total",
        scope=scope.value,
        outcome="complete",
    )


async def _fail_erasure(
    database: Database,
    telemetry: MetricsRecorder,
    *,
    erasure_id: UUID,
    lease_owner: str,
    scope: GovernanceScope,
    conversation_id: UUID,
    participant_id: UUID,
) -> None:
    governance = SqlAlchemyGovernanceRepository(database.session_factory)
    completed = await governance.complete_erasure_request(
        erasure_id,
        partial=True,
        partial_reason="repository_error",
        retryable=True,
        lease_owner=lease_owner,
    )
    if not completed:
        return
    telemetry.increment(
        "january_governance_erasure_requests_total",
        scope=scope.value,
        outcome="partial",
    )


async def _handle_governance_command(
    database: Database,
    commands: SqlAlchemyCommandRepository,
    job: object,
    owner: str,
    request: object,
    language: str,
    conversation: ConversationModel,
    participant: ParticipantModel,
    settings: Settings,
    adapter: PlatformAdapter | None,
    telemetry: MetricsRecorder,
) -> None:
    """Execute SPEC-025 data governance commands (FR-02, FR-03, FR-13)."""

    from app.application.commands import CommandRequest
    from app.infrastructure.database.models import TelegramCommandJobModel

    assert isinstance(job, TelegramCommandJobModel)
    assert isinstance(request, CommandRequest)
    if not settings.data_governance_enabled:
        await _finish(commands, job, owner, "governance_disabled", language)
        return
    if request.action == "summary":
        summary = await SqlAlchemyGovernanceRepository(
            database.session_factory
        ).subject_summary(
            conversation_id=conversation.id,
            participant_id=participant.id,
        )
        assistant_id = await _assistant_id_for_conversation(database, conversation.id)
        if assistant_id is None:
            await _finish(commands, job, owner, "safe_failure", language)
            return
        memory_summary = await SqlAlchemyMemoryRepository(
            database.session_factory
        ).status_for_participant(
            assistant_id=assistant_id,
            platform_connection_id=conversation.platform_connection_id,
            conversation_id=conversation.id,
            participant_id=participant.id,
        )
        detail = _data_summary_detail(settings, summary, memory_summary)
        await _finish(commands, job, owner, "data_summary", language, detail=detail)
        return
    if request.action not in {"export_subject", "export_group"}:
        await _finish(commands, job, owner, "usage", language)
        return
    if request.action == "export_group":
        if conversation.conversation_type == ConversationType.PRIVATE:
            await _finish(commands, job, owner, "export_group_private", language)
            return
        authorized = await _fresh_group_admin(
            commands,
            job,
            owner,
            language,
            conversation,
            participant,
            settings,
            adapter,
        )
        if not authorized:
            return
    scope = (
        GovernanceScope.SUBJECT
        if request.action == "export_subject"
        else GovernanceScope.GROUP
    )
    categories = (
        SUBJECT_EXPORT_CATEGORIES
        if scope is GovernanceScope.SUBJECT
        else GROUP_EXPORT_CATEGORIES
    )
    try:
        export = await SqlAlchemyGovernanceRepository(
            database.session_factory
        ).create_export_request(
            scope=scope,
            conversation_id=conversation.id,
            participant_id=participant.id,
            tenant_id=None,
            token_hash=None,
            categories=categories,
            ttl_days=settings.governance_export_ttl_days,
            source_command_job_id=job.id,
        )
    except Exception:  # noqa: BLE001 - fail closed and expose only closed telemetry
        telemetry.increment(
            "january_governance_export_requests_total",
            scope=scope.value,
            outcome="failed",
        )
        await _finish(commands, job, owner, "export_failed", language)
        return
    if export.created:
        telemetry.increment(
            "january_governance_export_requests_total",
            scope=scope.value,
            outcome="requested",
        )
    await _finish(
        commands,
        job,
        owner,
        "export_requested",
        language,
        detail=str(export.id),
        governance_export_request_id=export.id,
    )


def _data_summary_detail(
    settings: Settings, summary: object, memory_summary: object
) -> str:
    from app.infrastructure.database.governance import SubjectGovernanceSummary
    from app.infrastructure.database.memory import MemoryStatusSummary

    assert isinstance(summary, SubjectGovernanceSummary)
    assert isinstance(memory_summary, MemoryStatusSummary)
    return (
        " profile, preferences, private schedules, your messages (including "
        "captions and derived "
        "voice/audio transcripts), and memories in this conversation; "
        f"recall={'enabled' if memory_summary.recall_enabled else 'disabled'}; "
        f"owned_explicit={memory_summary.owned_explicit}; "
        f"shared_explicit={memory_summary.shared_explicit}; "
        f"personal_context={memory_summary.personal_context}; "
        f"export={summary.export_state}; erasure={summary.erasure_state}; "
        f"raw content is retained at most {settings.raw_content_retention_days} days; "
        "use /export_my_data or /forget_me; infrastructure encryption is owned "
        "by the operating owner and application-level field encryption is not provided."
    )


async def _assistant_id_for_conversation(
    database: Database, conversation_id: UUID
) -> UUID | None:
    async with database.session_factory() as session:
        value = await session.scalar(
            select(PlatformConnectionModel.assistant_id)
            .join(
                ConversationModel,
                ConversationModel.platform_connection_id == PlatformConnectionModel.id,
            )
            .where(ConversationModel.id == conversation_id)
        )
        return value if isinstance(value, UUID) else None


def _memory_list_detail(items: Sequence[object], *, more: bool) -> str:
    from app.infrastructure.database.memory import MemoryListEntry

    lines: list[str] = []
    for entry in items:
        assert isinstance(entry, MemoryListEntry)
        item = entry.item
        preview = (item.content or "")[:80]
        suffix = "..." if item.content and len(item.content) > len(preview) else ""
        created = item.created_at.date().isoformat()
        kind = (
            f"personal_context:{item.context_key.value}"
            if item.kind == MemoryKind.PERSONAL_CONTEXT and item.context_key is not None
            else "explicit_fact"
        )
        creator = (
            f"; {entry.creator_label}" if item.kind == MemoryKind.EXPLICIT_FACT else ""
        )
        lines.append(
            f" {item.public_id} [{kind}; rev={item.revision}; {created}{creator}]: "
            f"{preview}{suffix}"
        )
    detail = "".join(lines) if lines else " none"
    return f"{detail} more=1" if more else detail


def _record_memory_control(
    telemetry: MetricsRecorder,
    *,
    operation: str,
    outcome: str,
    record_kind: str,
    conversation: ConversationModel,
) -> None:
    telemetry.increment(
        "january_memory_control_operations_total",
        operation=operation,
        outcome=outcome,
        record_kind=record_kind,
        conversation_type=(
            "private"
            if conversation.conversation_type == ConversationType.PRIVATE
            else "group"
        ),
    )


def _memory_metric_operation(action: str) -> str:
    return {
        "summary": "status",
        "list": "list",
        "remember": "create",
        "context_create": "create",
        "update": "update",
        "delete": "delete",
        "forget": "delete",
        "clear_mine": "clear",
        "reset_group": "clear",
        "recall_status": "status",
        "recall_off": "recall_disable",
        "recall_on": "recall_enable",
        "warning": "delete",
        "confirm": "clear",
    }.get(action, "status")


async def _fresh_group_admin(
    commands: SqlAlchemyCommandRepository,
    job: object,
    owner: str,
    language: str,
    conversation: ConversationModel,
    participant: ParticipantModel,
    settings: Settings,
    adapter: PlatformAdapter | None,
) -> bool:
    from app.infrastructure.database.models import TelegramCommandJobModel

    assert isinstance(job, TelegramCommandJobModel)
    client = adapter or TelegramAdapter(settings)
    try:
        member = await client.get_chat_member(
            conversation.platform_conversation_id, participant.platform_user_id
        )
    except PlatformAdapterError as error:
        if adapter is None and isinstance(client, TelegramAdapter):
            await client.aclose()
        if (
            error.retryable
            and job.attempt_count < settings.command_max_authorization_attempts
        ):
            await commands.retry(
                job.id, owner, _authorization_retry_delay(settings, job.attempt_count)
            )
        else:
            await _finish(
                commands,
                job,
                owner,
                "temporary_failure" if error.retryable else "denied",
                language,
                (
                    CommandAuthorizationOutcome.RETRYABLE_FAILURE
                    if error.retryable
                    else CommandAuthorizationOutcome.PERMANENT_FAILURE
                ),
            )
        return False
    if adapter is None and isinstance(client, TelegramAdapter):
        await client.aclose()
    if not (member.is_administrator or member.is_owner):
        await _finish(
            commands,
            job,
            owner,
            "denied",
            language,
            CommandAuthorizationOutcome.DENIED,
        )
        return False
    return True


async def _load_state(
    database: Database, job_id: UUID
) -> tuple[
    str,
    ConversationModel | None,
    ParticipantModel | None,
    AssistantModel | None,
    int | None,
]:
    from app.infrastructure.database.models import TelegramCommandJobModel

    async with database.session_factory() as session:
        row = await session.execute(
            select(
                TelegramCommandJobModel,
                ConversationModel,
                ParticipantModel,
                AssistantModel,
                PlatformConnectionModel,
                ControlTenantModel,
                ConversationConfigurationRevisionModel,
            )
            .join(
                ConversationModel,
                TelegramCommandJobModel.conversation_id == ConversationModel.id,
            )
            .join(
                ParticipantModel,
                TelegramCommandJobModel.participant_id == ParticipantModel.id,
            )
            .join(
                PlatformConnectionModel,
                ConversationModel.platform_connection_id == PlatformConnectionModel.id,
            )
            .join(
                AssistantModel,
                (PlatformConnectionModel.assistant_id == AssistantModel.id)
                & (PlatformConnectionModel.tenant_id == AssistantModel.tenant_id),
            )
            .join(
                ControlTenantModel,
                ControlTenantModel.id == AssistantModel.tenant_id,
            )
            .outerjoin(
                ConversationConfigurationRevisionModel,
                ConversationModel.current_configuration_revision_id
                == ConversationConfigurationRevisionModel.id,
            )
            .where(TelegramCommandJobModel.id == job_id)
        )
        value = row.first()
        if value is None:
            return "vi", None, None, None, None
        _, conversation, participant, assistant, connection, tenant, revision = value
        if (
            tenant.status != TenantStatus.ACTIVE
            or assistant.status != AssistantStatus.ACTIVE
            or connection.status != PlatformConnectionStatus.ACTIVE
        ):
            return "vi", conversation, participant, None, None
        version = (
            await session.get(
                PersonalityProfileVersionModel,
                revision.personality_profile_version_id,
            )
            if revision is not None
            else None
        )
    language = (
        "en" if version is not None and version.primary_language == "en" else "vi"
    )
    return (
        language,
        conversation,
        participant,
        assistant,
        revision.revision_number if revision is not None else None,
    )


async def _resolve_profile_version(
    database: Database,
    assistant_id: UUID,
    value: object,
) -> tuple[UUID | None, str]:
    if not isinstance(value, str):
        return None, "profile_not_found"
    slug, separator, raw_version = value.partition("@")
    version_number = int(raw_version) if separator else None
    async with database.session_factory() as session:
        profile = await session.scalar(
            select(PersonalityProfileModel).where(
                PersonalityProfileModel.assistant_id == assistant_id,
                PersonalityProfileModel.slug == slug,
            )
        )
        if profile is None:
            exists_elsewhere = await session.scalar(
                select(PersonalityProfileModel.id).where(
                    PersonalityProfileModel.slug == slug
                )
            )
            return (
                None,
                "profile_not_owned"
                if exists_elsewhere is not None
                else "profile_not_found",
            )
        if profile.conversation_id is not None:
            return None, "profile_not_owned"
        if profile.status != PersonalityProfileStatus.ACTIVE:
            return None, "profile_not_found"
        query = select(PersonalityProfileVersionModel.id).where(
            PersonalityProfileVersionModel.profile_id == profile.id
        )
        if version_number is not None:
            query = query.where(
                PersonalityProfileVersionModel.version_number == version_number
            )
        else:
            query = query.order_by(
                PersonalityProfileVersionModel.version_number.desc()
            ).limit(1)
        result = await session.scalar(query)
        return (
            (result, "success")
            if isinstance(result, UUID)
            else (None, "profile_not_found")
        )


async def _protection_target(
    database: Database,
    conversation: ConversationModel,
    job: object,
) -> UUID | None:
    """Resolve the reply-to participant for /protect and /unprotect (FR-09)."""

    from app.infrastructure.database.models import TelegramCommandJobModel

    assert isinstance(job, TelegramCommandJobModel)
    async with database.session_factory() as session:
        message = await session.get(MessageModel, job.message_id)
        if message is None or message.reply_to_message_id is None:
            return None
        target = await session.get(MessageModel, message.reply_to_message_id)
        if (
            target is None
            or target.participant_id is None
            or target.conversation_id != conversation.id
        ):
            return None
        return target.participant_id


async def _read_detail(
    database: Database,
    conversation: ConversationModel,
    participant: ParticipantModel,
    assistant: AssistantModel,
    request: object,
    profile_limit: int,
) -> str | None:
    from app.application.commands import CommandRequest

    assert isinstance(request, CommandRequest)
    async with database.session_factory() as session:
        current = await session.get(ConversationModel, conversation.id)
        revision = (
            await session.get(
                ConversationConfigurationRevisionModel,
                current.current_configuration_revision_id,
            )
            if current is not None
            and current.current_configuration_revision_id is not None
            else None
        )
        latest_participant = await session.get(ParticipantModel, participant.id)
        version = (
            await session.get(
                PersonalityProfileVersionModel,
                revision.personality_profile_version_id,
            )
            if revision is not None
            else None
        )
        profile = (
            await session.get(PersonalityProfileModel, version.profile_id)
            if version is not None
            else None
        )
        if request.name == "status" and current and revision and latest_participant:
            state = (
                "paused" if revision.response_mode == ResponseMode.PAUSED else "active"
            )
            personality = (
                f"{profile.display_name} v{version.version_number}"
                if profile is not None and version is not None
                else "unavailable"
            )
            return (
                f"state={state}; "
                f"mode={revision.response_mode.value}; "
                f"frequency={revision.ambient_frequency.value}; "
                f"stickers={'on' if revision.stickers_enabled else 'off'}; "
                f"mentions={'on' if latest_participant.mention_allowed else 'off'}; "
                f"teasing={'on' if latest_participant.teasing_allowed else 'off'}; "
                f"safety={revision.safety_level.value}; "
                f"teasing_cap={revision.teasing_cap}; "
                f"personality={personality}"
            )
        if (
            request.name == "personality"
            and profile is not None
            and version is not None
        ):
            if request.action == "list":
                profiles = list(
                    await session.scalars(
                        select(PersonalityProfileModel)
                        .where(
                            PersonalityProfileModel.assistant_id == assistant.id,
                            PersonalityProfileModel.status
                            == PersonalityProfileStatus.ACTIVE,
                            PersonalityProfileModel.conversation_id.is_(None),
                        )
                        .order_by(PersonalityProfileModel.slug)
                        .limit(profile_limit)
                    )
                )
                return ", ".join(item.slug for item in profiles) or "none"
            return (
                f"{profile.display_name} ({profile.slug}) v{version.version_number}; "
                f"language={version.primary_language}; tone={version.formality}"
            )
        if request.name == "mode" and revision:
            return revision.response_mode.value
        if request.name == "frequency" and revision:
            return revision.ambient_frequency.value
        if request.name == "stickers" and revision:
            return "on" if revision.stickers_enabled else "off"
        if request.name == "mentions" and latest_participant:
            return "on" if latest_participant.mention_allowed else "off"
        if request.name == "teasing" and latest_participant:
            return "on" if latest_participant.teasing_allowed else "off"
        if request.name == "safety" and revision:
            return f"{revision.safety_level.value}; teasing_cap={revision.teasing_cap}"
    return None


def _configuration_change(
    settings: Settings,
    participant: ParticipantModel,
    request: object,
) -> tuple[str, ConfigurationChange | None, bool]:
    from app.application.commands import CommandRequest

    assert isinstance(request, CommandRequest)
    if (
        request.name == "mode"
        and request.value == "ambient_selective"
        and not settings.ambient_selective_enabled
    ):
        return "ambient_disabled", None, False
    if (
        request.name == "stickers"
        and request.value is True
        and not settings.telegram_sticker_mapping
    ):
        return "sticker_mapping_unavailable", None, False
    change = ConfigurationChange(
        source="telegram_command", actor_participant_id=participant.id
    )
    if request.name == "mode":
        change = ConfigurationChange(
            response_mode=ResponseMode(str(request.value)),
            source="telegram_command",
            actor_participant_id=participant.id,
        )
    elif request.name == "quiet":
        change = ConfigurationChange(
            response_mode=ResponseMode.PAUSED,
            source="telegram_command",
            actor_participant_id=participant.id,
        )
    elif request.name == "resume":
        change = ConfigurationChange(
            response_mode=ResponseMode.MENTION_ONLY,
            source="telegram_command",
            actor_participant_id=participant.id,
        )
    elif request.name == "stickers":
        change = ConfigurationChange(
            stickers_enabled=bool(request.value),
            source="telegram_command",
            actor_participant_id=participant.id,
        )
    elif request.name == "frequency":
        from app.domain.ambient import AmbientFrequency

        change = ConfigurationChange(
            ambient_frequency=AmbientFrequency(str(request.value)),
            source="telegram_command",
            actor_participant_id=participant.id,
        )
    elif request.name == "safety" and request.action == "set_safety_level":
        from app.domain.safety import SafetyLevel

        change = ConfigurationChange(
            safety_level=SafetyLevel(str(request.value)),
            source="telegram_command",
            actor_participant_id=participant.id,
        )
    elif request.name == "safety" and request.action == "set_teasing_cap":
        change = ConfigurationChange(
            teasing_cap=int(str(request.value)),
            source="telegram_command",
            actor_participant_id=participant.id,
        )
    else:
        return "usage", None, False
    return "success", change, request.name == "resume"


async def _finish(
    repository: SqlAlchemyCommandRepository,
    job: object,
    owner: str,
    code: str,
    language: str,
    authorization: CommandAuthorizationOutcome | None = None,
    preference: tuple[bool | None, bool | None] | None = None,
    detail: str | None = None,
    governance_export_request_id: UUID | None = None,
) -> None:
    from app.infrastructure.database.models import TelegramCommandJobModel

    assert isinstance(job, TelegramCommandJobModel)
    await repository.complete(
        job.id,
        owner,
        _candidate(job.message_id, code, language, detail),
        code,
        authorization,
        preference,
        unchanged_candidate=(
            _candidate(job.message_id, "unchanged", language)
            if preference is not None
            else None
        ),
        governance_export_request_id=governance_export_request_id,
    )


def _candidate(
    message_id: UUID, code: str, language: str, detail: str | None = None
) -> ResponsePlanCandidate:
    return ResponsePlanCandidate(
        should_respond=True,
        reason_code=PlanReasonCode.ACKNOWLEDGEMENT,
        text=command_response(code, language=language, detail=detail),
        reply_to_message_id=message_id,
        confidence=1,
        language=language,
    )


def _authorization_retry_delay(settings: Settings, attempt_count: int) -> float:
    """Apply bounded exponential backoff after the durable claim count."""

    return float(
        min(
            settings.command_retry_max_delay_seconds,
            settings.command_retry_min_delay_seconds * (2 ** max(0, attempt_count - 1)),
        )
    )


async def run() -> None:
    settings = get_settings()
    database = Database(settings)
    telemetry = (
        InMemoryMetricsRecorder() if settings.metrics_enabled else NoOpMetricsRecorder()
    )
    await database.start()
    tts_adapter: OpenAITextToSpeechAdapter | None = None
    tts_rate_limiter: RedisRateLimiter | None = None
    tts_concurrency_limiter: RedisConcurrencyLimiter | None = None
    if settings.telegram_voice_tts_enabled:
        governance = SqlAlchemyProviderGovernanceRepository(
            database.session_factory,
            mode=GovernanceMode.ENFORCE,
            reservation_lease_seconds=settings.provider_reservation_lease_seconds,
        )
        await governance.validate_prerequisites(WorkloadClass.TEXT_TO_SPEECH)
        tts_adapter = OpenAITextToSpeechAdapter(
            base_url=settings.llm_openai_base_url,
            api_key=(
                settings.llm_openai_api_key.get_secret_value()
                if settings.llm_openai_api_key is not None
                else None
            ),
            timeout_seconds=settings.telegram_voice_tts_timeout_seconds,
        )
        tts_rate_limiter = RedisRateLimiter(settings)
        tts_concurrency_limiter = RedisConcurrencyLimiter(settings)
    lifecycle = RuntimeLifecycle("telegram_command_worker")
    lifecycle.install()
    try:
        while not lifecycle.stopping:
            count = await consume_once(
                settings,
                database,
                telemetry=telemetry,
                tts_provider=tts_adapter,
                rate_limiter=tts_rate_limiter,
                concurrency_limiter=tts_concurrency_limiter,
            )
            if count:
                telemetry.increment(
                    "january_worker_operations_total",
                    count,
                    runtime="commands",
                    operation="command_job",
                    outcome="completed",
                )
            if count == 0:
                await lifecycle.wait(settings.command_poll_interval_seconds)
    finally:
        lifecycle.close()
        if tts_adapter is not None:
            await tts_adapter.aclose()
        if tts_rate_limiter is not None:
            await tts_rate_limiter.aclose()
        if tts_concurrency_limiter is not None:
            await tts_concurrency_limiter.aclose()
        await database.stop()


if __name__ == "__main__":
    asyncio.run(run())
