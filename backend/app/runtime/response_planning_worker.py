"""Dedicated durable response-planning worker; it never sends platform actions."""

import asyncio
import logging
import socket
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from functools import partial
from time import perf_counter
from uuid import UUID

from sqlalchemy import select

from app.application.ambient import apply_ambient_post_policy
from app.application.knowledge import ContextKnowledge
from app.application.model_provider import (
    ModelProvider,
    ProviderError,
    TranscriptionProvider,
)
from app.application.personality import merge_effective
from app.application.planning_service import generate_validated_plan
from app.application.ports.concurrency import ConcurrencyLimiter
from app.application.ports.media import MediaDownloader
from app.application.ports.platform import (
    PlatformAdapterError,
    PresenceAdapter,
    ReactionAdapter,
    SendChatActionRequest,
)
from app.application.ports.rate_limit import RateLimiter
from app.application.ports.telemetry import MetricsRecorder, NoOpMetricsRecorder
from app.application.presence import (
    PresenceControllerFactory,
    TypingPresenceController,
    telegram_typing_candidate,
)
from app.application.prompting import build_generation_request
from app.application.rate_limit_rules import generation_rules, provider_rule
from app.application.response_plan import ResponsePlanCandidate, ResponsePlanPolicy
from app.application.safety import SafetyModerationService
from app.core.config import Settings
from app.domain.ambient import (
    AMBIENT_POLICY_VERSION,
    AMBIENT_PROFILES,
    AmbientReason,
    ParticipationTrigger,
    is_sampled,
)
from app.domain.media import MediaFailureReason
from app.domain.planning import (
    GenerationAttemptKind,
    GenerationAttemptStatus,
    PlanReasonCode,
    ProviderErrorCategory,
    ProviderId,
    StickerIntent,
)
from app.domain.provider_governance import (
    GovernanceMode,
    ProviderOperation,
    WorkloadClass,
)
from app.domain.rate_limit import RateLimitDecision, RateLimitOperation
from app.domain.recovery import RecoveryDisposition, RecoveryKind, RecoveryReason
from app.domain.safety import (
    ProtectionAction,
    SafetyDecision,
    SafetyOutcome,
    SafetyPolicyVersion,
    SafetyReasonCode,
    SafetyStage,
    protection_notice,
)
from app.infrastructure.concurrency import RedisConcurrencyLimiter
from app.infrastructure.concurrency_provider import ConcurrencyLimitedProvider
from app.infrastructure.database.context import SqlAlchemyConversationContextReader
from app.infrastructure.database.database import Database
from app.infrastructure.database.media import SqlAlchemyMediaRepository
from app.infrastructure.database.models import (
    ConversationConfigurationRevisionModel,
    ConversationModel,
    MessageMediaModel,
    MessageModel,
    PersonalityProfileModel,
    PersonalityProfileVersionModel,
    ResponsePlanningJobModel,
    TelegramCommandJobModel,
)
from app.infrastructure.database.personality import revision_overrides, version_values
from app.infrastructure.database.planning import SqlAlchemyPlanningRepository
from app.infrastructure.database.provider_governance import (
    ProviderGovernanceUnavailable,
    SqlAlchemyProviderGovernanceRepository,
)
from app.infrastructure.database.reactions import (
    ReactionScope,
    SqlAlchemyReactionAuthority,
)
from app.infrastructure.database.recovery import SqlAlchemyRecoveryRepository
from app.infrastructure.database.safety import SqlAlchemySafetyRepository
from app.infrastructure.database.safety_protection import (
    SqlAlchemySafetyModerationRepository,
)
from app.infrastructure.database.tenancy import conversation_authority
from app.infrastructure.governed_provider import GovernedModelProvider
from app.infrastructure.model_providers import create_model_provider
from app.infrastructure.rate_limit import RateLimitUnavailable, RedisRateLimiter
from app.infrastructure.telegram.adapter import TelegramAdapter
from app.infrastructure.telemetry import InMemoryMetricsRecorder, MetricsHttpExporter
from app.runtime.lifecycle import RuntimeLifecycle
from app.runtime.telegram_media import (
    generation_requirements,
    prepare_media,
    record_media_operation,
)

logger = logging.getLogger(__name__)


def worker_name(settings: Settings) -> str:
    return f"{settings.planning_owner_name}-{socket.gethostname()}"


async def consume_once(
    settings: Settings,
    database: Database,
    owner: str | None = None,
    primary_provider: ModelProvider | None = None,
    fallback_provider: ModelProvider | None = None,
    rate_limiter: RateLimiter | None = None,
    concurrency_limiter: ConcurrencyLimiter | None = None,
    telemetry: MetricsRecorder | None = None,
    media_downloader: MediaDownloader | None = None,
    transcription_provider: TranscriptionProvider | None = None,
    presence_adapter: PresenceAdapter | None = None,
    presence_controller_factory: PresenceControllerFactory | None = None,
    reaction_adapter: ReactionAdapter | None = None,
) -> int:
    if not settings.llm_enabled:
        return 0
    repository = SqlAlchemyPlanningRepository(database.session_factory)
    recorder = telemetry or NoOpMetricsRecorder()
    context_reader = SqlAlchemyConversationContextReader(
        database.session_factory, settings, recorder
    )
    claimed = await repository.claim(
        owner or worker_name(settings),
        settings.planning_job_batch_size,
        settings.planning_job_lease_seconds,
    )
    lease_owner = owner or worker_name(settings)
    owns_providers = primary_provider is None
    owns_limiter = rate_limiter is None and settings.rate_limit_enabled
    owns_concurrency = (
        concurrency_limiter is None and settings.provider_concurrency_enabled
    )
    limiter = (
        rate_limiter
        if rate_limiter is not None
        else RedisRateLimiter(settings)
        if settings.rate_limit_enabled
        else None
    )
    concurrency = (
        concurrency_limiter
        if concurrency_limiter is not None
        else RedisConcurrencyLimiter(settings)
        if settings.provider_concurrency_enabled
        else None
    )
    safety_repository = SqlAlchemySafetyRepository(database.session_factory)
    moderation = SafetyModerationService(
        settings,
        SqlAlchemySafetyModerationRepository(database.session_factory),
    )
    reaction_authority = SqlAlchemyReactionAuthority(database.session_factory)
    for _ in claimed:
        recorder.increment("january_planning_jobs_total", outcome="claimed")
    governance_mode = GovernanceMode(settings.provider_governance_mode)
    primary = primary_provider or (
        create_model_provider(settings, ProviderId(settings.llm_primary_provider))
        if governance_mode == GovernanceMode.LEGACY
        else None
    )
    fallback = fallback_provider or (
        create_model_provider(settings, ProviderId(settings.llm_fallback_provider))
        if governance_mode == GovernanceMode.LEGACY and settings.llm_fallback_provider
        else None
    )
    if concurrency is not None and governance_mode == GovernanceMode.LEGACY:
        assert primary is not None
        primary = ConcurrencyLimitedProvider(primary, concurrency, recorder)
        if fallback is not None:
            fallback = ConcurrencyLimitedProvider(fallback, concurrency, recorder)
    try:
        for job in claimed:
            complete = partial(repository.complete, expected_attempt=job.attempt_count)
            complete.keywords["media_retention_days"] = (
                settings.raw_content_retention_days
            )
            context_exclusions = await _regeneration_context_exclusions(database, job)

            async def lifecycle_active(
                conversation_id: UUID = job.conversation_id,
            ) -> bool:
                async with database.session_factory() as session:
                    authority = await conversation_authority(session, conversation_id)
                return authority is not None and authority[1].permits_external_io

            if not await lifecycle_active():
                await complete(
                    job.id,
                    lease_owner,
                    None,
                    None,
                    None,
                    None,
                    job.prompt_version,
                    job.response_schema_version,
                )
                continue
            async with database.session_factory() as session:
                initial_authority = await conversation_authority(
                    session, job.conversation_id
                )
            if initial_authority is None:
                await complete(
                    job.id,
                    lease_owner,
                    None,
                    None,
                    None,
                    None,
                    job.prompt_version,
                    job.response_schema_version,
                )
                continue
            conversation_platform = initial_authority[1].connection.platform
            reaction_scope = ReactionScope(
                tenant_id=initial_authority[1].tenant.id,
                assistant_id=initial_authority[1].assistant.id,
                connection_id=initial_authority[1].connection.id,
                conversation_id=initial_authority[0].id,
            )
            async with database.session_factory() as session:
                media_source = await session.get(MessageModel, job.message_id)
                has_media_attachment = (
                    await session.scalar(
                        select(MessageMediaModel.id).where(
                            MessageMediaModel.message_id == job.message_id
                        )
                    )
                    is not None
                )
            is_media = has_media_attachment or (
                media_source is not None
                and (
                    media_source.message_type.value in {"photo", "voice", "audio"}
                    or "media_failure" in media_source.metadata_
                )
            )
            prepared_image = None
            prepared = None
            media_metric_kind = (
                media_source.message_type.value
                if media_source is not None
                and media_source.message_type.value in {"photo", "voice", "audio"}
                else "unsupported"
            )
            media_before_io = None
            context = await context_reader.build_for_message(
                job.message_id,
                planning_job_id=job.id,
                include_semantic=not is_media,
                excluded_message_ids=context_exclusions,
            )
            if context is None:
                await complete(
                    job.id,
                    lease_owner,
                    None,
                    None,
                    None,
                    None,
                    job.prompt_version,
                    job.response_schema_version,
                )
                continue
            if context.historical_summary is not None:
                recorder.increment(
                    "january_summary_context_usage_total",
                    outcome="used",
                    schema=context.historical_summary.schema_version,
                )
            else:
                recorder.increment(
                    "january_summary_context_usage_total",
                    outcome="raw_fallback",
                    schema="none",
                )
            async with database.session_factory() as session:
                conversation = await session.get(ConversationModel, job.conversation_id)
                current_revision = (
                    await session.get(
                        ConversationConfigurationRevisionModel,
                        conversation.current_configuration_revision_id,
                    )
                    if conversation is not None
                    and conversation.current_configuration_revision_id is not None
                    else None
                )
                revision = (
                    await session.get(
                        ConversationConfigurationRevisionModel,
                        job.configuration_revision_id,
                    )
                    if job.configuration_revision_id
                    else None
                )
                version = (
                    await session.get(
                        PersonalityProfileVersionModel,
                        job.personality_profile_version_id,
                    )
                    if job.personality_profile_version_id
                    else None
                )
                profile = (
                    await session.get(PersonalityProfileModel, version.profile_id)
                    if version is not None
                    else None
                )
            if (
                conversation is None
                or current_revision is None
                or revision is None
                or version is None
                or profile is None
            ):
                await complete(
                    job.id,
                    lease_owner,
                    None,
                    None,
                    None,
                    None,
                    job.prompt_version,
                    job.response_schema_version,
                )
                continue
            memory_privacy_revision = conversation.memory_privacy_revision
            if (
                conversation.status.value == "paused"
                or current_revision.response_mode.value == "paused"
            ):
                await complete(
                    job.id,
                    lease_owner,
                    None,
                    None,
                    None,
                    None,
                    job.prompt_version,
                    job.response_schema_version,
                )
                continue
            ambient = job.trigger == ParticipationTrigger.AMBIENT
            ambient_profile = current_revision.ambient_frequency.value

            async def complete_ambient_silence(
                reason: AmbientReason,
                job_id: UUID = job.id,
                prompt_version: str = job.prompt_version,
                schema_version: str = job.response_schema_version,
                profile: str = ambient_profile,
                finish: Callable[..., Awaitable[UUID | None]] = complete,
            ) -> None:
                await finish(
                    job_id,
                    lease_owner,
                    ResponsePlanCandidate(
                        should_respond=False,
                        reason_code=PlanReasonCode.SILENCE,
                        confidence=1.0,
                    ),
                    None,
                    None,
                    None,
                    prompt_version,
                    schema_version,
                    reason.value,
                )
                recorder.increment(
                    "january_ambient_decisions_total",
                    outcome=reason.value,
                    profile=profile,
                    policy=AMBIENT_POLICY_VERSION,
                )

            if ambient and (
                not settings.ambient_selective_enabled
                or current_revision.response_mode.value != "ambient_selective"
            ):
                await complete_ambient_silence(AmbientReason.FEATURE_DISABLED)
                continue
            effective = merge_effective(
                version_values(version),
                revision_overrides(revision),
                profile_id=profile.id,
                profile_version_id=version.id,
                profile_version_number=version.version_number,
                configuration_revision_id=revision.id,
                configuration_revision_number=revision.revision_number,
            )
            request = build_generation_request(
                planning_job_id=job.id,
                context=context,
                prompt_version=job.prompt_version,
                response_schema_version=job.response_schema_version,
                maximum_output_tokens=settings.llm_max_output_tokens,
                conversation_type=conversation.conversation_type.value,
                response_mode=conversation.response_mode.value,
                trigger=job.trigger.value,
                effective_personality=effective,
                stickers_enabled=revision.stickers_enabled,
            )
            teasing_level = effective["teasing_level"]
            policy = ResponsePlanPolicy(
                settings.response_plan_text_limit,
                frozenset(StickerIntent) if revision.stickers_enabled else frozenset(),
                teasing_permitted=isinstance(teasing_level, int | float)
                and teasing_level > 0,
                reply_to_current=not ambient,
            )
            # Do not send context assembled before a durable privacy/memory change.
            async with database.session_factory() as session:
                fresh_conversation = await session.get(
                    ConversationModel, job.conversation_id
                )
            if (
                fresh_conversation is None
                or fresh_conversation.memory_privacy_revision != memory_privacy_revision
            ):
                await repository.release_for_context_change(job.id, lease_owner)
                continue

            if ambient:
                if job.configuration_revision_id is None or not is_sampled(
                    context.current.id,
                    job.configuration_revision_id,
                    current_revision.ambient_frequency,
                    job.ambient_policy_version or AMBIENT_POLICY_VERSION,
                ):
                    await complete_ambient_silence(AmbientReason.NOT_SAMPLED)
                    continue
                last_ambient = await repository.latest_confirmed_ambient_response(
                    conversation.id
                )
                profile_policy = AMBIENT_PROFILES[current_revision.ambient_frequency]
                if (
                    last_ambient is not None
                    and (datetime.now(UTC) - last_ambient).total_seconds()
                    < profile_policy.cooldown_seconds
                ):
                    await complete_ambient_silence(AmbientReason.COOLDOWN)
                    continue

            participant_id = context.current.participant_id
            if participant_id is not None:
                protective_action = await moderation.evaluate_and_enforce(
                    conversation_id=job.conversation_id,
                    participant_id=participant_id,
                    safety_level=revision.safety_level,
                )
                if protective_action is not None:
                    recorder.increment(
                        "january_safety_protective_actions_total",
                        action=protective_action.value,
                    )
                state = await moderation.protection_state(participant_id)
                interaction_mode = state.interaction_mode if state is not None else None
                if (
                    protective_action == ProtectionAction.PAUSE_INTERACTION
                    or interaction_mode == ProtectionAction.PAUSE_INTERACTION.value
                ):
                    await safety_repository.record_decision(
                        planning_job_id=job.id,
                        response_plan_id=None,
                        conversation_id=job.conversation_id,
                        decision=SafetyDecision(
                            SafetyPolicyVersion.V1,
                            SafetyStage.PRE_GENERATION,
                            SafetyOutcome.SILENT,
                        ),
                    )
                    recorder.increment(
                        "january_safety_decisions_total",
                        stage=SafetyStage.PRE_GENERATION.value,
                        outcome=SafetyOutcome.SILENT.value,
                        reason="none",
                    )
                    await complete(
                        job.id,
                        lease_owner,
                        None,
                        None,
                        None,
                        None,
                        job.prompt_version,
                        job.response_schema_version,
                    )
                    continue
                if interaction_mode == ProtectionAction.REDUCE_INTERACTION.value:
                    await safety_repository.record_decision(
                        planning_job_id=job.id,
                        response_plan_id=None,
                        conversation_id=job.conversation_id,
                        decision=SafetyDecision(
                            SafetyPolicyVersion.V1,
                            SafetyStage.PRE_GENERATION,
                            SafetyOutcome.SILENT,
                        ),
                    )
                    recorder.increment(
                        "january_safety_decisions_total",
                        stage=SafetyStage.PRE_GENERATION.value,
                        outcome=SafetyOutcome.SILENT.value,
                        reason="none",
                    )
                    await complete(
                        job.id,
                        lease_owner,
                        ResponsePlanCandidate(
                            should_respond=True,
                            reason_code=PlanReasonCode.ACKNOWLEDGEMENT,
                            text=protection_notice(
                                "en" if version.primary_language == "en" else "vi"
                            ),
                            reply_to_message_id=job.message_id,
                            confidence=1.0,
                            language="en" if version.primary_language == "en" else "vi",
                        ),
                        None,
                        None,
                        None,
                        job.prompt_version,
                        job.response_schema_version,
                    )
                    continue
            await safety_repository.record_decision(
                planning_job_id=job.id,
                response_plan_id=None,
                conversation_id=job.conversation_id,
                decision=SafetyDecision(
                    SafetyPolicyVersion.V1,
                    SafetyStage.PRE_GENERATION,
                    SafetyOutcome.ALLOW,
                ),
            )
            recorder.increment(
                "january_safety_decisions_total",
                stage=SafetyStage.PRE_GENERATION.value,
                outcome=SafetyOutcome.ALLOW.value,
                reason="none",
            )
            if limiter is not None:
                try:
                    decision = await limiter.check(
                        RateLimitOperation.GENERATION,
                        generation_rules(
                            settings,
                            connection_id=conversation.platform_connection_id,
                            conversation_id=conversation.id,
                            participant_id=participant_id,
                        ),
                    )
                except RateLimitUnavailable:
                    decision = RateLimitDecision(
                        False,
                        retry_after_seconds=settings.rate_limit_redis_failure_retry_seconds,
                    )
                await safety_repository.record_rate_limit(
                    planning_job_id=job.id,
                    outbound_action_id=None,
                    operation=RateLimitOperation.GENERATION,
                    decision=decision,
                    provider_id=(
                        primary.provider_id.value
                        if primary is not None
                        else ProviderId(settings.llm_primary_provider).value
                    ),
                    configuration_version=SafetyPolicyVersion.V1.value,
                )
                if not decision.allowed:
                    recorder.increment(
                        "january_rate_limit_events_total",
                        operation="generation",
                        scope=decision.limiting_scope.value
                        if decision.limiting_scope
                        else "unavailable",
                        result="denied",
                    )
                    logger.info(
                        "rate_limit_denied operation=generation planning_job_id=%s "
                        "scope=%s retry_after_seconds=%s",
                        job.id,
                        decision.limiting_scope,
                        decision.retry_after_seconds,
                    )
                    await safety_repository.record_decision(
                        planning_job_id=job.id,
                        response_plan_id=None,
                        conversation_id=job.conversation_id,
                        decision=SafetyDecision(
                            SafetyPolicyVersion.V1,
                            SafetyStage.PRE_GENERATION,
                            SafetyOutcome.SILENT,
                            SafetyReasonCode.RATE_LIMITED,
                        ),
                    )
                    recorder.increment(
                        "january_safety_decisions_total",
                        stage=SafetyStage.PRE_GENERATION.value,
                        outcome=SafetyOutcome.SILENT.value,
                        reason=SafetyReasonCode.RATE_LIMITED.value,
                    )
                    await repository.release_for_rate_limit(
                        job.id,
                        lease_owner,
                        decision.retry_after_seconds
                        or settings.rate_limit_redis_failure_retry_seconds,
                    )
                    continue

            if is_media:
                media_repository = SqlAlchemyMediaRepository(
                    database.session_factory,
                    connection_id=conversation.platform_connection_id,
                    retention_days=settings.raw_content_retention_days,
                    lease_seconds=settings.planning_job_lease_seconds,
                    transcript_limit=settings.telegram_media_transcript_max_characters,
                )

                async def media_safety_preflight(
                    conversation_id: UUID = job.conversation_id,
                    subject_id: UUID | None = participant_id,
                ) -> bool:
                    async with database.session_factory() as session:
                        fresh = await session.get(ConversationModel, conversation_id)
                        config = (
                            await session.get(
                                ConversationConfigurationRevisionModel,
                                fresh.current_configuration_revision_id,
                            )
                            if fresh is not None
                            and fresh.current_configuration_revision_id
                            else None
                        )
                    if (
                        fresh is None
                        or config is None
                        or fresh.status.value != "active"
                        or config.response_mode.value == "paused"
                    ):
                        return False
                    protection = (
                        await moderation.protection_state(subject_id)
                        if subject_id is not None
                        else None
                    )
                    return await lifecycle_active() and (
                        protection is None
                        or protection.interaction_mode
                        not in {
                            ProtectionAction.PAUSE_INTERACTION.value,
                            ProtectionAction.REDUCE_INTERACTION.value,
                        }
                    )

                media_governance = SqlAlchemyProviderGovernanceRepository(
                    database.session_factory,
                    mode=governance_mode,
                    reservation_lease_seconds=settings.provider_reservation_lease_seconds,
                )
                failure: MediaFailureReason | None = MediaFailureReason.UNSUPPORTED
                media_token: UUID | None = None
                if has_media_attachment:
                    prepared = await prepare_media(
                        settings=settings,
                        repository=media_repository,
                        governance=media_governance,
                        job_id=job.id,
                        owner=lease_owner,
                        attempt=job.attempt_count,
                        connection_id=conversation.platform_connection_id,
                        rate_limiter=limiter,
                        concurrency_limiter=concurrency,
                        telemetry=recorder,
                        safety_preflight=media_safety_preflight,
                        downloader=media_downloader,
                        transcription_provider=transcription_provider,
                    )
                    failure = prepared.failure
                    prepared_image = prepared.image
                    if prepared.work is not None:
                        media_token = prepared.work.lease_token
                    complete.keywords["expected_media_token"] = media_token
                if failure is not None:
                    if failure in {
                        MediaFailureReason.STALE_LEASE,
                        MediaFailureReason.PRIVACY_CHANGED,
                    }:
                        await complete(
                            job.id,
                            lease_owner,
                            None,
                            None,
                            None,
                            None,
                            job.prompt_version,
                            job.response_schema_version,
                        )
                    else:
                        language = "en" if version.primary_language == "en" else "vi"
                        await complete(
                            job.id,
                            lease_owner,
                            ResponsePlanCandidate(
                                should_respond=True,
                                reason_code=PlanReasonCode.ACKNOWLEDGEMENT,
                                text=(
                                    "I couldn't process this media. "
                                    "Please send a text message."
                                    if language == "en"
                                    else "Mình chưa xử lý được nội dung này. "
                                    "Bạn gửi tin nhắn văn bản nhé."
                                ),
                                reply_to_message_id=job.message_id,
                                confidence=1.0,
                                language=language,
                            ),
                            None,
                            None,
                            None,
                            job.prompt_version,
                            job.response_schema_version,
                        )
                    continue
                async with database.session_factory() as session:
                    fresh = await session.get(ConversationModel, job.conversation_id)
                if fresh is None:
                    continue
                memory_privacy_revision = fresh.memory_privacy_revision
                complete.keywords["expected_privacy_revision"] = memory_privacy_revision

                async def media_generation_preflight(
                    media_store: SqlAlchemyMediaRepository = media_repository,
                    job_id: UUID = job.id,
                    attempt: int = job.attempt_count,
                    privacy_revision: int = memory_privacy_revision,
                    token: UUID | None = media_token,
                    safety_check: Callable[
                        [], Awaitable[bool]
                    ] = media_safety_preflight,
                ) -> bool:
                    return (
                        await safety_check()
                        and await media_store.generation_preflight(
                            job_id,
                            lease_owner,
                            attempt,
                            privacy_revision,
                            media_token=token,
                        )
                    )

                media_before_io = media_generation_preflight
                context = await context_reader.build_for_message(
                    job.message_id,
                    planning_job_id=job.id,
                    before_external_io=media_before_io,
                    excluded_message_ids=context_exclusions,
                )
                if context is None:
                    continue
                request = replace(
                    build_generation_request(
                        planning_job_id=job.id,
                        context=context,
                        prompt_version=job.prompt_version,
                        response_schema_version=job.response_schema_version,
                        maximum_output_tokens=settings.llm_max_output_tokens,
                        conversation_type=conversation.conversation_type.value,
                        response_mode=conversation.response_mode.value,
                        trigger=job.trigger.value,
                        effective_personality=effective,
                        stickers_enabled=revision.stickers_enabled,
                    ),
                    current_image=prepared_image,
                )

            selected_knowledge = context.knowledge
            if selected_knowledge and not await repository.knowledge_provenance_valid(
                job.id, [item.provenance() for item in selected_knowledge]
            ):
                context = replace(context, knowledge=())
                selected_knowledge = ()
                request = replace(
                    build_generation_request(
                        planning_job_id=job.id,
                        context=context,
                        prompt_version=job.prompt_version,
                        response_schema_version=job.response_schema_version,
                        maximum_output_tokens=settings.llm_max_output_tokens,
                        conversation_type=conversation.conversation_type.value,
                        response_mode=conversation.response_mode.value,
                        trigger=job.trigger.value,
                        effective_personality=effective,
                        stickers_enabled=revision.stickers_enabled,
                    ),
                    current_image=prepared_image,
                )
            if not await repository.store_knowledge_provenance(
                job.id,
                lease_owner,
                [item.provenance() for item in selected_knowledge],
            ):
                continue

            presence: TypingPresenceController | None = None
            if telegram_typing_candidate(
                conversation_platform, job.trigger, settings.telegram_enabled
            ):
                if presence_adapter is not None:
                    presence_request = SendChatActionRequest(
                        conversation.platform_conversation_id,
                        context.current.platform_thread_id,
                    )
                    factory = presence_controller_factory or TypingPresenceController
                    presence = factory(
                        partial(presence_adapter.send_chat_action, presence_request),
                        partial(
                            repository.presence_authorized,
                            job.id,
                            lease_owner,
                            job.attempt_count,
                        ),
                        recorder,
                    )

            async def start_presence(
                controller: TypingPresenceController | None = presence,
            ) -> None:
                if controller is not None:
                    await controller.start()

            async def before_provider(
                provider: ModelProvider,
                planning_job_id: UUID = job.id,
                selected_knowledge: tuple[ContextKnowledge, ...] = selected_knowledge,
            ) -> ProviderError | None:
                if not await repository.knowledge_provenance_valid(
                    planning_job_id,
                    [item.provenance() for item in selected_knowledge],
                ):
                    return ProviderError(
                        ProviderErrorCategory.NO_ELIGIBLE_ROUTE,
                        provider.provider_id,
                        provider.model,
                        False,
                        "generate",
                        "knowledge authority changed before provider I/O",
                    )
                if not await lifecycle_active():
                    return ProviderError(
                        ProviderErrorCategory.NO_ELIGIBLE_ROUTE,
                        provider.provider_id,
                        provider.model,
                        False,
                        "generate",
                        "tenant, assistant, or connection is not active",
                    )
                if governance_mode != GovernanceMode.LEGACY:
                    return None
                if limiter is not None:
                    try:
                        decision = await limiter.check(
                            RateLimitOperation.GENERATION,
                            (provider_rule(settings, provider.provider_id.value),),
                        )
                    except RateLimitUnavailable:
                        decision = RateLimitDecision(
                            False,
                            retry_after_seconds=(
                                settings.rate_limit_redis_failure_retry_seconds
                            ),
                        )
                    await safety_repository.record_rate_limit(
                        planning_job_id=planning_job_id,
                        outbound_action_id=None,
                        operation=RateLimitOperation.GENERATION,
                        decision=decision,
                        provider_id=provider.provider_id.value,
                        configuration_version=SafetyPolicyVersion.V1.value,
                    )
                    if not decision.allowed:
                        recorder.increment(
                            "january_rate_limit_events_total",
                            operation="generation",
                            scope=decision.limiting_scope.value
                            if decision.limiting_scope
                            else "unavailable",
                            result="denied",
                        )
                        logger.info(
                            "rate_limit_denied operation=provider planning_job_id=%s "
                            "scope=%s retry_after_seconds=%s",
                            planning_job_id,
                            decision.limiting_scope,
                            decision.retry_after_seconds,
                        )
                        return ProviderError(
                            ProviderErrorCategory.RATE_LIMITED,
                            provider.provider_id,
                            provider.model,
                            True,
                            "generate",
                            "distributed rate limit denied provider I/O",
                        )
                await start_presence()
                return None

            async def record(
                provider: ModelProvider,
                succeeded: bool,
                error: object,
                correction: int,
                planning_job_id: UUID = job.id,
            ) -> None:
                if governance_mode != GovernanceMode.LEGACY:
                    return
                from app.application.model_provider import ProviderError

                provider_error = error if isinstance(error, ProviderError) else None
                await repository.record_attempt(
                    planning_job_id,
                    provider.provider_id,
                    provider.model,
                    GenerationAttemptKind.CORRECTION
                    if correction
                    else GenerationAttemptKind.PRIMARY,
                    GenerationAttemptStatus.SUCCEEDED
                    if succeeded
                    else GenerationAttemptStatus.FAILED,
                    provider_error.category if provider_error else None,
                )

            active_primary = primary
            active_fallback: ModelProvider | tuple[ModelProvider, ...] | None = fallback
            governed_owned: list[ModelProvider] = []
            if governance_mode != GovernanceMode.LEGACY:
                governance = SqlAlchemyProviderGovernanceRepository(
                    database.session_factory,
                    mode=governance_mode,
                    reservation_lease_seconds=settings.provider_reservation_lease_seconds,
                )
                try:
                    source = await governance.planning_source(job.id)
                    routes = await governance.resolve_routes(
                        source,
                        WorkloadClass.CHAT_GENERATION,
                        generation_requirements(
                            settings, image=prepared_image is not None
                        ),
                    )
                except ProviderGovernanceUnavailable:
                    recorder.increment(
                        "january_provider_routing_decisions_total",
                        workload="chat_generation",
                        operation="response_planning",
                        route_role="primary",
                        outcome="denied",
                        reason="invalid_policy",
                    )
                    await complete(
                        job.id,
                        lease_owner,
                        None,
                        None,
                        None,
                        ProviderErrorCategory.GOVERNANCE_UNAVAILABLE,
                        job.prompt_version,
                        job.response_schema_version,
                    )
                    continue
                if not routes:
                    recorder.increment(
                        "january_provider_routing_decisions_total",
                        workload="chat_generation",
                        operation="response_planning",
                        route_role="primary",
                        outcome="denied",
                        reason="no_route",
                    )
                    await complete(
                        job.id,
                        lease_owner,
                        None,
                        None,
                        None,
                        ProviderErrorCategory.NO_ELIGIBLE_ROUTE,
                        job.prompt_version,
                        job.response_schema_version,
                    )
                    continue
                governed_providers: list[ModelProvider] = []
                for index, route in enumerate(routes):
                    injected = (
                        primary_provider
                        if index == 0 and primary_provider is not None
                        else fallback_provider
                        if index == 1 and fallback_provider is not None
                        else None
                    )
                    raw = injected or create_model_provider(
                        settings, route.adapter_key, route.model
                    )
                    if injected is None:
                        governed_owned.append(raw)
                    governed_providers.append(
                        GovernedModelProvider(
                            raw,
                            route,
                            source,
                            ProviderOperation.RESPONSE_PLANNING,
                            governance,
                            settings,
                            limiter,
                            concurrency,
                            recorder,
                            before_io=media_before_io,
                            on_io_start=start_presence,
                        )
                    )
                active_primary = governed_providers[0]
                active_fallback = tuple(governed_providers[1:])
            if active_primary is None:
                raise RuntimeError("response planning provider is unavailable")
            generation_started = perf_counter()
            try:
                outcome = await generate_validated_plan(
                    request,
                    policy,
                    active_primary,
                    active_fallback,
                    settings.llm_max_transport_attempts,
                    settings.llm_max_correction_attempts,
                    on_attempt=record,
                    before_provider=before_provider,
                    telemetry=recorder,
                    pricing=settings.metrics_provider_pricing,
                )
                if is_media:
                    record_media_operation(
                        recorder,
                        media_metric_kind,
                        "generation",
                        "completed" if outcome.candidate is not None else "failed",
                        reason="none"
                        if outcome.candidate is not None
                        else "unavailable",
                        duration=perf_counter() - generation_started,
                    )
            except BaseException as error:
                if is_media:
                    record_media_operation(
                        recorder,
                        media_metric_kind,
                        "generation",
                        "cancelled"
                        if isinstance(error, asyncio.CancelledError)
                        else "failed",
                        reason="unavailable",
                        duration=perf_counter() - generation_started,
                    )
                raise
            finally:
                if presence is not None:
                    await presence.stop()
                request = replace(request, current_image=None)
                prepared_image = None
                prepared = None
                if is_media:
                    record_media_operation(
                        recorder, media_metric_kind, "cleanup", "completed"
                    )
                for owned_provider in governed_owned:
                    await owned_provider.aclose()
            provider = outcome.provider
            if (
                outcome.provider_error is not None
                and outcome.provider_error.category
                == ProviderErrorCategory.RATE_LIMITED
            ):
                await safety_repository.record_decision(
                    planning_job_id=job.id,
                    response_plan_id=None,
                    conversation_id=job.conversation_id,
                    decision=SafetyDecision(
                        SafetyPolicyVersion.V1,
                        SafetyStage.PRE_GENERATION,
                        SafetyOutcome.SILENT,
                        SafetyReasonCode.RATE_LIMITED,
                    ),
                )
                recorder.increment(
                    "january_safety_decisions_total",
                    stage=SafetyStage.PRE_GENERATION.value,
                    outcome=SafetyOutcome.SILENT.value,
                    reason=SafetyReasonCode.RATE_LIMITED.value,
                )
                await repository.release_for_rate_limit(
                    job.id,
                    lease_owner,
                    settings.rate_limit_redis_failure_retry_seconds,
                )
                continue
            if (
                outcome.provider_error is not None
                and outcome.provider_error.category
                == ProviderErrorCategory.CONCURRENCY_LIMITED
            ):
                await repository.release_for_rate_limit(
                    job.id,
                    lease_owner,
                    settings.rate_limit_redis_failure_retry_seconds,
                )
                continue
            candidate = outcome.candidate
            ambient_reason: str | None = None
            if ambient and candidate is not None:
                profile_policy = AMBIENT_PROFILES[current_revision.ambient_frequency]
                candidate, ambient_decision = apply_ambient_post_policy(
                    candidate, profile_policy.minimum_confidence
                )
                ambient_reason = ambient_decision.value
                recorder.increment(
                    "january_ambient_decisions_total",
                    outcome=ambient_reason,
                    profile=current_revision.ambient_frequency.value,
                    policy=AMBIENT_POLICY_VERSION,
                )
            response_plan_id = await complete(
                job.id,
                lease_owner,
                candidate,
                provider.provider_id if provider else None,
                provider.model if provider else None,
                outcome.provider_error.category if outcome.provider_error else None,
                job.prompt_version,
                job.response_schema_version,
                ambient_reason,
            )
            if (
                outcome.candidate is None
                and outcome.provider_error is not None
                and outcome.provider_error.category
                not in {
                    ProviderErrorCategory.BUDGET_EXHAUSTED,
                    ProviderErrorCategory.GOVERNANCE_UNAVAILABLE,
                    ProviderErrorCategory.NO_ELIGIBLE_ROUTE,
                }
            ):
                await SqlAlchemyRecoveryRepository(database.session_factory).classify(
                    RecoveryKind.PLANNING,
                    job.id,
                    RecoveryDisposition.DEAD_LETTER,
                    RecoveryReason.PROVIDER_RETRY_EXHAUSTED
                    if outcome.provider_error.retryable
                    else RecoveryReason.INVALID_TERMINAL_PLAN,
                )
                recorder.increment(
                    "january_dead_letter_events_total",
                    work_kind="planning",
                    reason=(
                        "provider_retry_exhausted"
                        if outcome.provider_error.retryable
                        else "invalid_terminal_plan"
                    ),
                )
                recorder.increment(
                    "january_recovery_events_total",
                    work_kind="planning",
                    operation="classify",
                    outcome="dead_letter",
                    reason=(
                        "provider_retry_exhausted"
                        if outcome.provider_error.retryable
                        else "invalid_terminal_plan"
                    ),
                )
            await safety_repository.record_decision(
                planning_job_id=job.id,
                response_plan_id=response_plan_id,
                conversation_id=job.conversation_id,
                decision=SafetyDecision(
                    SafetyPolicyVersion.V1,
                    SafetyStage.POST_GENERATION,
                    SafetyOutcome.ALLOW
                    if outcome.candidate is not None
                    else SafetyOutcome.REFUSE,
                    SafetyReasonCode.MODEL_REFUSAL
                    if outcome.provider_error
                    and outcome.provider_error.category.value == "safety_refusal"
                    else None,
                    transformed=outcome.candidate is not None
                    and outcome.candidate.text is not None
                    and outcome.candidate.text.startswith("I will keep"),
                ),
            )
            recorder.increment(
                "january_safety_decisions_total",
                stage=SafetyStage.POST_GENERATION.value,
                outcome=(
                    SafetyOutcome.ALLOW.value
                    if outcome.candidate is not None
                    else SafetyOutcome.REFUSE.value
                ),
                reason=(
                    SafetyReasonCode.MODEL_REFUSAL.value
                    if outcome.provider_error
                    and outcome.provider_error.category.value == "safety_refusal"
                    else "none"
                ),
            )
            if reaction_adapter is not None:
                await _attempt_reaction(
                    reaction_authority,
                    reaction_adapter,
                    recorder,
                    job.id,
                    job.attempt_count,
                    scope=reaction_scope,
                    safety_allowed=(
                        outcome.provider_error is None
                        or outcome.provider_error.category
                        != ProviderErrorCategory.SAFETY_REFUSAL
                    ),
                )
        return len(claimed)
    finally:
        if owns_providers and governance_mode == GovernanceMode.LEGACY:
            assert primary is not None
            await primary.aclose()
            if fallback is not None:
                await fallback.aclose()
        if owns_limiter and limiter is not None:
            await limiter.aclose()
        if owns_concurrency and concurrency is not None:
            await concurrency.aclose()


async def _regeneration_context_exclusions(
    database: Database, job: ResponsePlanningJobModel
) -> tuple[UUID, ...]:
    if job.source_command_job_id is None:
        return ()
    async with database.session_factory() as session:
        command = await session.get(TelegramCommandJobModel, job.source_command_job_id)
        return (command.message_id,) if command is not None else ()


async def _attempt_reaction(
    authority: SqlAlchemyReactionAuthority,
    adapter: ReactionAdapter,
    recorder: MetricsRecorder,
    planning_job_id: UUID,
    expected_attempt: int,
    *,
    scope: ReactionScope,
    safety_allowed: bool,
) -> None:
    target = await authority.resolve(
        planning_job_id,
        scope=scope,
        expected_attempt=expected_attempt,
        safety_allowed=safety_allowed,
    )
    if target is None:
        recorder.increment(
            "january_telegram_reaction_decisions_total",
            decision="none",
            kind="none",
        )
        return
    recorder.increment(
        "january_telegram_reaction_decisions_total",
        decision="selected",
        kind=target.request.kind.value,
    )
    try:
        await adapter.set_reaction(target.request)
    except PlatformAdapterError as error:
        recorder.increment(
            "january_telegram_reaction_delivery_total",
            outcome="failure",
            reason=error.category.value,
        )
        return
    recorder.increment(
        "january_telegram_reaction_delivery_total",
        outcome="success",
        reason="none",
    )


async def run() -> None:
    settings = Settings()
    database = Database(settings)
    telemetry = (
        InMemoryMetricsRecorder() if settings.metrics_enabled else NoOpMetricsRecorder()
    )
    exporter = (
        MetricsHttpExporter(
            telemetry, settings.metrics_bind_host, settings.planning_metrics_port
        )
        if settings.metrics_export_enabled
        else None
    )
    await database.start()
    if GovernanceMode(settings.provider_governance_mode) == GovernanceMode.ENFORCE:
        governance = SqlAlchemyProviderGovernanceRepository(
            database.session_factory,
            mode=GovernanceMode.ENFORCE,
            reservation_lease_seconds=settings.provider_reservation_lease_seconds,
        )
        await governance.validate_prerequisites(WorkloadClass.CHAT_GENERATION)
        if settings.semantic_memory_enabled:
            await governance.validate_prerequisites(WorkloadClass.EMBEDDING)
    if exporter is not None:
        await exporter.start()
    lifecycle = RuntimeLifecycle("response_planning_worker")
    telegram_adapter = TelegramAdapter(settings) if settings.telegram_enabled else None
    lifecycle.install()
    try:
        while not lifecycle.stopping:
            processed = await consume_once(
                settings,
                database,
                telemetry=telemetry,
                presence_adapter=telegram_adapter,
                reaction_adapter=telegram_adapter,
            )
            if processed == 0:
                await lifecycle.wait(settings.planning_job_poll_interval_seconds)
    except asyncio.CancelledError:
        raise
    finally:
        lifecycle.close()
        if exporter is not None:
            await exporter.close()
        if telegram_adapter is not None:
            await telegram_adapter.aclose()
        await database.stop()


if __name__ == "__main__":
    asyncio.run(run())
