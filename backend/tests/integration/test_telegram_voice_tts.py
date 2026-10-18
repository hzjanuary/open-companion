"""Live PostgreSQL proofs for SPEC-038 explicit Telegram voice playback."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ingress import IngressQueueEvent
from app.application.ports.platform import (
    PlatformAdapterError,
    PlatformCapability,
    PlatformErrorCategory,
    SendVoiceRequest,
    SentMessage,
)
from app.application.ports.text_to_speech import (
    TextToSpeechError,
    TextToSpeechRequest,
    TextToSpeechResult,
)
from app.application.response_plan import ResponsePlanCandidate
from app.core.config import Settings
from app.domain.conversation import ProcessingOutcome
from app.domain.outbound import (
    DeliveryCertainty,
    OutboundActionKind,
    OutboundActionStatus,
)
from app.domain.persistence import (
    AssistantStatus,
    CommandJobStatus,
    ConversationStatus,
    ConversationType,
    IngressSource,
    MessageDirection,
    MessageProcessingStatus,
    MessageType,
    Platform,
    PlatformConnectionStatus,
    ResponseMode,
)
from app.domain.planning import (
    PlanningJobStatus,
    PlanReasonCode,
    ProviderErrorCategory,
    ProviderId,
)
from app.domain.provider_governance import (
    BudgetMeasurement,
    BudgetMode,
    BudgetScope,
    BudgetWindowKind,
    GovernanceMode,
    ProviderAttemptOutcome,
    ProviderAttemptState,
    ProviderDataClass,
    ProviderHealth,
    ProviderLifecycle,
    ProviderOperation,
    RouteRole,
    WorkloadClass,
)
from app.domain.rate_limit import RateLimitDecision
from app.domain.voice import (
    VoiceArtifactStatus,
    VoiceFailureReason,
    VoiceFormat,
    VoiceGenerationStatus,
)
from app.infrastructure.database.commands import SqlAlchemyCommandRepository
from app.infrastructure.database.conversation import SqlAlchemyConversationProcessor
from app.infrastructure.database.database import Database
from app.infrastructure.database.ingress import SqlAlchemyDurableIngressRepository
from app.infrastructure.database.models import (
    AssistantModel,
    ControlOperatorIdentityModel,
    ControlTenantModel,
    ConversationModel,
    ConversationProcessingRecordModel,
    GeneratedVoiceArtifactModel,
    IncomingPlatformUpdateModel,
    IngressOutboxEventModel,
    MessageModel,
    OutboundActionModel,
    OutboundDeliveryAttemptModel,
    ParticipantModel,
    PlatformConnectionModel,
    ProviderBudgetHeadModel,
    ProviderBudgetModel,
    ProviderBudgetRevisionModel,
    ProviderCapabilityModel,
    ProviderCapabilityStateModel,
    ProviderHealthPolicyRevisionModel,
    ProviderPriceRevisionModel,
    ProviderRoutingPolicyHeadModel,
    ProviderRoutingPolicyRevisionModel,
    ProviderRoutingPolicyRouteModel,
    ProviderUsageAttemptModel,
    ResponsePlanModel,
    ResponsePlanningJobModel,
    TelegramCommandJobModel,
    TelegramVoiceGenerationJobModel,
)
from app.infrastructure.database.personality import ensure_conversation_configuration
from app.infrastructure.database.planning import SqlAlchemyPlanningRepository
from app.infrastructure.database.privacy import SqlAlchemyPrivacyRepository
from app.infrastructure.database.provider_governance import (
    SqlAlchemyProviderGovernanceRepository,
)
from app.infrastructure.database.regeneration import (
    RegenerationAdmission,
    SqlAlchemyRegenerationRepository,
)
from app.infrastructure.database.retention import SqlAlchemyRetentionRepository
from app.infrastructure.database.voice import (
    SqlAlchemyVoiceRepository,
    VoicePreparationOutcome,
)
from app.infrastructure.telegram.normalizer import normalize_telegram_update
from app.infrastructure.telegram.updates import parse_telegram_update
from app.infrastructure.telemetry import InMemoryMetricsRecorder
from app.runtime.outbound_delivery_worker import consume_once as deliver_once
from app.runtime.telegram_command_worker import consume_once as consume_command_once

pytestmark = [pytest.mark.integration, pytest.mark.telegram_voice_tts_integration]

_AUDIO = b"OggS\x00\x02synthetic-opus"


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        provider_governance_mode="enforce",
        provider_governance_worker_enabled=True,
        control_plane_enabled=True,
        control_plane_jwt_secret=SecretStr("x" * 32),
        control_plane_jwt_issuer="spec038-test",
        control_plane_jwt_audience="spec038-test",
        rate_limit_enabled=True,
        provider_concurrency_enabled=True,
        command_worker_enabled=True,
        outbound_delivery_enabled=True,
        telegram_enabled=True,
        telegram_bot_token=SecretStr("123456:SPEC038_FAKE_TOKEN"),
        telegram_platform_connection_id=uuid4(),
        telegram_voice_tts_enabled=True,
        llm_openai_api_key=SecretStr("test-only-openai-key"),
    )


class _AllowedRateLimiter:
    async def check(self, *args: object) -> RateLimitDecision:
        del args
        return RateLimitDecision(True)


class _DeniedRateLimiter:
    async def check(self, *args: object) -> RateLimitDecision:
        del args
        return RateLimitDecision(False, retry_after_seconds=30)


class _Lease:
    provider = ProviderId.OPENAI
    token = "test-only-concurrency-lease"


class _AvailableConcurrency:
    async def acquire(self, provider: ProviderId) -> _Lease:
        assert provider == ProviderId.OPENAI
        return _Lease()

    async def release(self, lease: _Lease) -> None:
        assert lease.provider == ProviderId.OPENAI


class _DeniedConcurrency:
    async def acquire(self, provider: ProviderId) -> None:
        assert provider == ProviderId.OPENAI
        return None

    async def release(self, lease: object) -> None:
        raise AssertionError(f"denied concurrency must not release a lease: {lease!r}")


class _SessionCheckingTTS:
    provider_id = ProviderId.OPENAI

    def __init__(self, database: Database) -> None:
        self.database = database
        self.requests: list[TextToSpeechRequest] = []

    async def synthesize(self, request: TextToSpeechRequest) -> TextToSpeechResult:
        assert self.database.engine.pool.checkedout() == 0  # type: ignore[attr-defined]
        self.requests.append(request)
        return TextToSpeechResult(
            provider=ProviderId.OPENAI,
            model=request.model,
            audio_bytes=_AUDIO,
            format=VoiceFormat.OGG_OPUS,
            mime_type="audio/ogg",
            provider_request_id="opaque-spec038-request",
        )


class _BlockingTTS(_SessionCheckingTTS):
    def __init__(self, database: Database) -> None:
        super().__init__(database)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def synthesize(self, request: TextToSpeechRequest) -> TextToSpeechResult:
        assert self.database.engine.pool.checkedout() == 0  # type: ignore[attr-defined]
        self.requests.append(request)
        self.entered.set()
        await self.release.wait()
        return TextToSpeechResult(
            provider=ProviderId.OPENAI,
            model=request.model,
            audio_bytes=_AUDIO,
            format=VoiceFormat.OGG_OPUS,
            mime_type="audio/ogg",
            provider_request_id="opaque-spec038-blocked-request",
        )


class _UncertainTTS(_SessionCheckingTTS):
    async def synthesize(self, request: TextToSpeechRequest) -> TextToSpeechResult:
        assert self.database.engine.pool.checkedout() == 0  # type: ignore[attr-defined]
        self.requests.append(request)
        raise TextToSpeechError(
            ProviderErrorCategory.TIMEOUT,
            retryable=False,
            io_possible=True,
            diagnostic="test-only uncertain TTS outcome",
        )


class _WrongModelTTS(_SessionCheckingTTS):
    async def synthesize(self, request: TextToSpeechRequest) -> TextToSpeechResult:
        assert self.database.engine.pool.checkedout() == 0  # type: ignore[attr-defined]
        self.requests.append(request)
        return TextToSpeechResult(
            provider=ProviderId.OPENAI,
            model="wrong-route-model",
            audio_bytes=_AUDIO,
            format=VoiceFormat.OGG_OPUS,
            mime_type="audio/ogg",
        )


class _OversizedOutputTTS(_SessionCheckingTTS):
    async def synthesize(self, request: TextToSpeechRequest) -> TextToSpeechResult:
        assert self.database.engine.pool.checkedout() == 0  # type: ignore[attr-defined]
        self.requests.append(request)
        raise TextToSpeechError(
            ProviderErrorCategory.MALFORMED_RESPONSE,
            retryable=False,
            io_possible=False,
            diagnostic="provider output exceeded the configured byte limit",
        )


class _SessionCheckingTelegram:
    capabilities = frozenset({PlatformCapability.SEND_VOICE})

    def __init__(self, database: Database) -> None:
        self.database = database
        self.requests: list[SendVoiceRequest] = []

    async def send_voice(self, request: SendVoiceRequest) -> SentMessage:
        assert self.database.engine.pool.checkedout() == 0  # type: ignore[attr-defined]
        self.requests.append(request)
        return SentMessage(
            platform=Platform.TELEGRAM,
            platform_message_id="voice-delivered-1",
            conversation_id=request.conversation_id,
            sender_id="bot",
            message_thread_id=request.message_thread_id,
            created_at=datetime.now(UTC),
        )


class _SequencedTelegram(_SessionCheckingTelegram):
    def __init__(
        self, database: Database, first_error: PlatformAdapterError | None
    ) -> None:
        super().__init__(database)
        self.first_error = first_error

    async def send_voice(self, request: SendVoiceRequest) -> SentMessage:
        assert self.database.engine.pool.checkedout() == 0  # type: ignore[attr-defined]
        self.requests.append(request)
        if self.first_error is not None:
            error = self.first_error
            self.first_error = None
            raise error
        return SentMessage(
            platform=Platform.TELEGRAM,
            platform_message_id=f"voice-delivered-{len(self.requests)}",
            conversation_id=request.conversation_id,
            sender_id="bot",
            message_thread_id=request.message_thread_id,
            created_at=datetime.now(UTC),
        )


async def _processing_record(
    session: AsyncSession,
    conversation: ConversationModel,
    message: MessageModel,
) -> ConversationProcessingRecordModel:
    update = IncomingPlatformUpdateModel(
        platform_connection_id=conversation.platform_connection_id,
        platform=Platform.TELEGRAM,
        platform_update_id=f"voice-update-{uuid4()}",
        update_type="message",
        ingress_source=IngressSource.WEBHOOK,
        raw_payload={},
        received_at=datetime.now(UTC),
    )
    session.add(update)
    await session.flush()
    record = ConversationProcessingRecordModel(
        incoming_update_id=update.id,
        outcome=ProcessingOutcome.MESSAGE_CREATED,
        conversation_id=conversation.id,
        message_id=message.id,
    )
    session.add(record)
    await session.flush()
    return record


async def _incoming(
    session: AsyncSession,
    conversation: ConversationModel,
    participant: ParticipantModel,
    *,
    platform_id: str,
    text: str,
    reply_to: MessageModel | None = None,
) -> MessageModel:
    message = MessageModel(
        conversation_id=conversation.id,
        participant_id=participant.id,
        platform_message_id=platform_id,
        direction=MessageDirection.INCOMING,
        message_type=MessageType.TEXT,
        text=text,
        reply_to_message_id=reply_to.id if reply_to is not None else None,
        reply_to_platform_message_id=(
            reply_to.platform_message_id if reply_to is not None else None
        ),
        processing_status=MessageProcessingStatus.PROCESSED,
        platform_sent_at=datetime.now(UTC),
    )
    session.add(message)
    await session.flush()
    return message


async def _voice_command(
    session: AsyncSession,
    conversation: ConversationModel,
    participant: ParticipantModel,
    *,
    reply_to: MessageModel | None,
) -> TelegramCommandJobModel:
    command_message = await _incoming(
        session,
        conversation,
        participant,
        platform_id=f"voice-command-{uuid4()}",
        text="/voice",
        reply_to=reply_to,
    )
    command_record = await _processing_record(session, conversation, command_message)
    command = TelegramCommandJobModel(
        conversation_processing_record_id=command_record.id,
        conversation_id=conversation.id,
        message_id=command_message.id,
        participant_id=participant.id,
        command_name="voice",
        arguments="",
        status=CommandJobStatus.PENDING,
    )
    session.add(command)
    await session.flush()
    return command


async def _seed_authority(
    session: AsyncSession,
    *,
    plan_text: str = "first chunk + second chunk",
) -> tuple[
    ConversationModel,
    ParticipantModel,
    list[MessageModel],
    TelegramCommandJobModel,
]:
    suffix = uuid4().hex
    tenant = ControlTenantModel(slug=f"voice-{suffix}", name="Voice")
    session.add(tenant)
    await session.flush()
    assistant = AssistantModel(
        tenant_id=tenant.id,
        slug=f"voice-assistant-{suffix}",
        name="January",
        status=AssistantStatus.ACTIVE,
    )
    session.add(assistant)
    await session.flush()
    connection = PlatformConnectionModel(
        tenant_id=tenant.id,
        assistant_id=assistant.id,
        platform=Platform.TELEGRAM,
        external_bot_id=f"voice-bot-{suffix}",
        status=PlatformConnectionStatus.ACTIVE,
    )
    session.add(connection)
    await session.flush()
    conversation = ConversationModel(
        platform_connection_id=connection.id,
        platform_conversation_id=f"voice-chat-{suffix}",
        conversation_type=ConversationType.PRIVATE,
        status=ConversationStatus.ACTIVE,
        response_mode=ResponseMode.MENTION_ONLY,
    )
    session.add(conversation)
    await session.flush()
    await ensure_conversation_configuration(session, assistant, conversation)
    participant = ParticipantModel(
        conversation_id=conversation.id,
        platform_user_id=f"voice-user-{suffix}",
        display_name="User",
    )
    session.add(participant)
    await session.flush()
    source = await _incoming(
        session,
        conversation,
        participant,
        platform_id=f"source-{suffix}",
        text="Question",
    )
    record = await _processing_record(session, conversation, source)
    planning = ResponsePlanningJobModel(
        conversation_processing_record_id=record.id,
        conversation_id=conversation.id,
        message_id=source.id,
        prompt_version="spec-038-test",
        response_schema_version="response-plan-v1",
        status=PlanningJobStatus.COMPLETED,
        completed_at=datetime.now(UTC),
    )
    session.add(planning)
    await session.flush()
    plan = ResponsePlanModel(
        planning_job_id=planning.id,
        should_respond=True,
        reason_code=PlanReasonCode.ANSWER,
        text=plan_text,
        reply_to_message_id=source.id,
        mention_participant_ids=[],
        confidence=1,
        prompt_version="spec-038-test",
        schema_version="response-plan-v1",
    )
    session.add(plan)
    await session.flush()
    delivered: list[MessageModel] = []
    split_at = max(1, len(plan_text) // 2)
    for number, chunk_text in enumerate(
        (plan_text[:split_at], plan_text[split_at:]), start=1
    ):
        action = OutboundActionModel(
            response_plan_id=plan.id,
            conversation_id=conversation.id,
            sequence_number=number,
            sequence_count=2,
            idempotency_key=uuid4().hex,
            kind=OutboundActionKind.TEXT,
            status=OutboundActionStatus.DELIVERED,
            text=chunk_text,
            mention_participant_ids=[],
            completed_at=datetime.now(UTC),
        )
        session.add(action)
        await session.flush()
        message = MessageModel(
            conversation_id=conversation.id,
            outbound_action_id=action.id,
            platform_message_id=f"answer-{number}-{suffix}",
            direction=MessageDirection.OUTGOING,
            message_type=MessageType.TEXT,
            text=chunk_text,
            processing_status=MessageProcessingStatus.PROCESSED,
            platform_sent_at=datetime.now(UTC),
        )
        session.add(message)
        await session.flush()
        action.delivered_message_id = message.id
        delivered.append(message)
    command = await _voice_command(
        session,
        conversation,
        participant,
        reply_to=delivered[1],
    )
    await _seed_tts_governance(session)
    return conversation, participant, delivered, command


async def _other_scope_target(
    session: AsyncSession,
    *,
    tenant: ControlTenantModel,
    assistant: AssistantModel,
    suffix: str,
) -> MessageModel:
    connection = PlatformConnectionModel(
        tenant_id=tenant.id,
        assistant_id=assistant.id,
        platform=Platform.TELEGRAM,
        external_bot_id=f"other-bot-{suffix}",
        status=PlatformConnectionStatus.ACTIVE,
    )
    session.add(connection)
    await session.flush()
    conversation = ConversationModel(
        platform_connection_id=connection.id,
        platform_conversation_id=f"other-chat-{suffix}",
        conversation_type=ConversationType.PRIVATE,
        status=ConversationStatus.ACTIVE,
        response_mode=ResponseMode.MENTION_ONLY,
    )
    session.add(conversation)
    await session.flush()
    target = MessageModel(
        conversation_id=conversation.id,
        platform_message_id=f"other-answer-{suffix}",
        direction=MessageDirection.OUTGOING,
        message_type=MessageType.TEXT,
        text="Foreign content must never be synthesized",
        processing_status=MessageProcessingStatus.PROCESSED,
        platform_sent_at=datetime.now(UTC),
    )
    session.add(target)
    await session.flush()
    return target


async def _seed_tts_governance(session: AsyncSession) -> None:
    now = datetime.now(UTC)
    actor = ControlOperatorIdentityModel(
        issuer=f"spec038-{uuid4().hex}", subject="operator"
    )
    session.add(actor)
    await session.flush()
    capability = ProviderCapabilityModel(
        provider_id=ProviderId.OPENAI,
        adapter_key=ProviderId.OPENAI,
        workload_class=WorkloadClass.TEXT_TO_SPEECH,
        model="gpt-4o-mini-tts",
        capability_metadata={
            "text_to_speech": True,
            "voice_format": "ogg_opus",
            "maximum_input_characters": 4000,
            "maximum_output_bytes": 5_242_880,
        },
        data_class=ProviderDataClass.APPROVED_EXTERNAL,
        credential_slot="openai",
        credential_configured=True,
        reservation_strategy="request_count",
        created_by_identity_id=actor.id,
    )
    session.add(capability)
    await session.flush()
    health_policy = ProviderHealthPolicyRevisionModel(
        capability_id=capability.id,
        version=1,
        observation_window_seconds=300,
        degraded_threshold=2,
        unavailable_threshold=3,
        recovery_success_threshold=2,
        stale_after_seconds=300,
        effective_at=now,
        created_by_identity_id=actor.id,
    )
    session.add(health_policy)
    await session.flush()
    session.add(
        ProviderCapabilityStateModel(
            capability_id=capability.id,
            lifecycle=ProviderLifecycle.ENABLED,
            health=ProviderHealth.READY,
            health_policy_revision_id=health_policy.id,
            last_evaluated_at=now,
        )
    )
    policy = ProviderRoutingPolicyRevisionModel(
        scope_type=BudgetScope.DEPLOYMENT,
        scope_key="deployment",
        workload_class=WorkloadClass.TEXT_TO_SPEECH,
        schema_version="provider-routing-v1",
        version=1,
        requirements={
            "text_to_speech": True,
            "allowed_data_classes": ["approved_external"],
            "require_current_health": True,
        },
        effective_at=now,
        created_by_identity_id=actor.id,
    )
    session.add(policy)
    await session.flush()
    session.add_all(
        [
            ProviderRoutingPolicyRouteModel(
                policy_revision_id=policy.id,
                capability_id=capability.id,
                position=0,
            ),
            ProviderRoutingPolicyHeadModel(
                scope_key="deployment",
                workload_class=WorkloadClass.TEXT_TO_SPEECH,
                policy_revision_id=policy.id,
            ),
            ProviderPriceRevisionModel(
                capability_id=capability.id,
                currency="USD",
                unit_basis="tts_request",
                request_rate=1_000,
                effective_from=now,
                created_by_identity_id=actor.id,
            ),
        ]
    )
    budget = ProviderBudgetModel(
        scope_type=BudgetScope.DEPLOYMENT,
        scope_key="deployment",
        workload_class=WorkloadClass.TEXT_TO_SPEECH,
        measurement=BudgetMeasurement.ESTIMATED_COST_MICROUSD,
        window_kind=BudgetWindowKind.DAILY_UTC,
    )
    session.add(budget)
    await session.flush()
    budget_revision = ProviderBudgetRevisionModel(
        budget_id=budget.id,
        version=1,
        amount=10_000,
        mode=BudgetMode.HARD,
        alert_threshold_bps=8000,
        effective_at=now,
        created_by_identity_id=actor.id,
    )
    session.add(budget_revision)
    await session.flush()
    session.add(
        ProviderBudgetHeadModel(
            budget_id=budget.id,
            budget_revision_id=budget_revision.id,
        )
    )


async def _generate_voice(
    settings: Settings,
    database: Database,
    *,
    owner: str,
) -> tuple[_SessionCheckingTTS, UUID, UUID]:
    tts = _SessionCheckingTTS(database)
    assert (
        await consume_command_once(
            settings,
            database,
            owner=owner,
            tts_provider=tts,
            rate_limiter=_AllowedRateLimiter(),
            concurrency_limiter=_AvailableConcurrency(),
        )
        == 1
    )
    assert len(tts.requests) == 1
    async with database.session_factory() as session:
        action = await session.scalar(
            select(OutboundActionModel).where(
                OutboundActionModel.kind == OutboundActionKind.VOICE
            )
        )
        assert action is not None
        assert action.generated_voice_artifact_id is not None
        return tts, action.id, action.generated_voice_artifact_id


async def _forbidden_side_effect_counts(session: AsyncSession) -> tuple[int, ...]:
    row = (
        await session.execute(
            text(
                "SELECT "
                "(SELECT count(*) FROM memory_items), "
                "(SELECT count(*) FROM memory_events), "
                "(SELECT count(*) FROM explicit_memory_semantic_index_jobs), "
                "(SELECT count(*) FROM knowledge_documents), "
                "(SELECT count(*) FROM knowledge_document_revisions), "
                "(SELECT count(*) FROM knowledge_chunks), "
                "(SELECT count(*) FROM knowledge_index_jobs), "
                "(SELECT count(*) FROM conversation_summaries), "
                "(SELECT count(*) FROM message_media), "
                "(SELECT count(*) FROM provider_usage_attempts "
                " WHERE operation <> 'voice_synthesis')"
            )
        )
    ).one()
    return tuple(int(value) for value in row)


def test_voice_split_target_generation_artifact_and_delivery_are_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        settings = _settings()
        database = Database(settings)
        await database.start()
        try:
            async with database.session_factory() as session, session.begin():
                await session.execute(
                    text(
                        "TRUNCATE control_operator_identities, control_tenants CASCADE"
                    )
                )
                conversation, _, _, command = await _seed_authority(session)
                conversation_id = conversation.id
                command_id = command.id
                command_platform_id = (
                    await session.get(MessageModel, command.message_id)
                ).platform_message_id  # type: ignore[union-attr]
            async with database.session_factory() as session:
                forbidden_before = await _forbidden_side_effect_counts(session)
            tts = _SessionCheckingTTS(database)
            telemetry = InMemoryMetricsRecorder()
            original_bind = SqlAlchemyVoiceRepository.bind_provider_attempt

            async def asserted_bind(
                repository: SqlAlchemyVoiceRepository,
                job_id: UUID,
                owner: str,
                attempt_id: UUID,
            ) -> bool:
                async with database.session_factory() as session:
                    row = await session.get(TelegramVoiceGenerationJobModel, job_id)
                    assert row is not None
                    assert row.status == VoiceGenerationStatus.LEASED
                    assert row.lease_owner == owner
                    assert row.lease_expires_at is not None
                    assert row.lease_expires_at > datetime.now(UTC)
                    assert row.provider_attempt_id is None
                bound = await original_bind(repository, job_id, owner, attempt_id)
                assert bound
                async with database.session_factory() as session:
                    rebound = await session.get(TelegramVoiceGenerationJobModel, job_id)
                    assert rebound is not None
                    assert rebound.provider_attempt_id == attempt_id
                return bound

            monkeypatch.setattr(
                SqlAlchemyVoiceRepository,
                "bind_provider_attempt",
                asserted_bind,
            )
            assert (
                await consume_command_once(
                    settings,
                    database,
                    owner="spec038-command",
                    tts_provider=tts,
                    rate_limiter=_AllowedRateLimiter(),
                    concurrency_limiter=_AvailableConcurrency(),
                    telemetry=telemetry,
                )
                == 1
            )
            assert len(tts.requests) == 1
            assert (
                telemetry.counter_value(
                    "january_tts_admission_total", outcome="allowed"
                )
                == 1
            )
            assert (
                telemetry.counter_value(
                    "january_tts_results_total",
                    outcome="success",
                    provider="openai",
                )
                == 1
            )
            assert tts.requests[0].text == "first chunk + second chunk"
            assert tts.requests[0].model == "gpt-4o-mini-tts"
            async with database.session_factory() as session:
                job = await session.scalar(
                    select(TelegramVoiceGenerationJobModel).where(
                        TelegramVoiceGenerationJobModel.command_job_id == command_id
                    )
                )
                assert job is not None
                assert job.status == VoiceGenerationStatus.COMPLETED
                artifact = await session.scalar(
                    select(GeneratedVoiceArtifactModel).where(
                        GeneratedVoiceArtifactModel.generation_job_id == job.id
                    )
                )
                assert artifact is not None
                assert artifact.status == VoiceArtifactStatus.READY
                assert artifact.audio_bytes == _AUDIO
                assert artifact.byte_size == len(_AUDIO)
                action = await session.scalar(
                    select(OutboundActionModel).where(
                        OutboundActionModel.generated_voice_artifact_id == artifact.id
                    )
                )
                assert action is not None
                assert action.kind == OutboundActionKind.VOICE
                assert action.status == OutboundActionStatus.PENDING
                assert action.reply_to_message_id == command.message_id
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(ProviderUsageAttemptModel)
                        .where(
                            ProviderUsageAttemptModel.voice_generation_job_id == job.id
                        )
                    )
                    == 1
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(MessageModel)
                        .where(
                            MessageModel.conversation_id == conversation_id,
                            MessageModel.message_type == MessageType.VOICE,
                        )
                    )
                    == 0
                )
            telegram = _SessionCheckingTelegram(database)
            assert (
                await deliver_once(
                    settings,
                    database,
                    adapter=telegram,  # type: ignore[arg-type]
                    rate_limiter=_AllowedRateLimiter(),
                )
                == 1
            )
            assert len(telegram.requests) == 1
            assert telegram.requests[0].audio_bytes == _AUDIO
            assert telegram.requests[0].reply_to_message_id == command_platform_id
            async with database.session_factory() as session:
                delivered_action = await session.get(OutboundActionModel, action.id)
                assert delivered_action is not None
                assert delivered_action.status == OutboundActionStatus.DELIVERED
                delivered_artifact = await session.get(
                    GeneratedVoiceArtifactModel, artifact.id
                )
                assert delivered_artifact is not None
                assert delivered_artifact.action_terminal_at is not None
                assert delivered_artifact.audio_bytes == _AUDIO
                assert (
                    delivered_artifact.action_terminal_at
                    < delivered_artifact.expires_at
                    <= delivered_artifact.action_terminal_at + timedelta(hours=24)
                )
                voice_message = await session.scalar(
                    select(MessageModel).where(
                        MessageModel.outbound_action_id == delivered_action.id
                    )
                )
                assert voice_message is not None
                assert voice_message.message_type == MessageType.VOICE
                assert voice_message.text is None
                assert await _forbidden_side_effect_counts(session) == forbidden_before
        finally:
            await database.stop()

    asyncio.run(scenario())


def test_voice_invalid_and_foreign_targets_never_reach_tts() -> None:
    async def scenario() -> None:
        settings = _settings()
        database = Database(settings)
        await database.start()
        try:
            async with database.session_factory() as session, session.begin():
                await session.execute(
                    text(
                        "TRUNCATE control_operator_identities, control_tenants CASCADE"
                    )
                )
                conversation, participant, _, valid_command = await _seed_authority(
                    session
                )
                valid_command.status = CommandJobStatus.COMPLETED
                valid_command.result_code = "fixture_only"
                valid_command.completed_at = datetime.now(UTC)
                no_reply = await _voice_command(
                    session, conversation, participant, reply_to=None
                )
                user_target = await _incoming(
                    session,
                    conversation,
                    participant,
                    platform_id=f"user-target-{uuid4()}",
                    text="User-authored text must not be synthesized",
                )
                user_reply = await _voice_command(
                    session, conversation, participant, reply_to=user_target
                )
                connection = await session.get(
                    PlatformConnectionModel, conversation.platform_connection_id
                )
                assert connection is not None
                tenant = await session.get(ControlTenantModel, connection.tenant_id)
                assistant = await session.get(AssistantModel, connection.assistant_id)
                assert tenant is not None and assistant is not None
                same_assistant_other_connection = await _other_scope_target(
                    session,
                    tenant=tenant,
                    assistant=assistant,
                    suffix=f"connection-{uuid4().hex}",
                )
                foreign_assistant = AssistantModel(
                    tenant_id=tenant.id,
                    slug=f"foreign-assistant-{uuid4().hex}",
                    name="Foreign assistant",
                    status=AssistantStatus.ACTIVE,
                )
                session.add(foreign_assistant)
                await session.flush()
                foreign_assistant_target = await _other_scope_target(
                    session,
                    tenant=tenant,
                    assistant=foreign_assistant,
                    suffix=f"assistant-{uuid4().hex}",
                )
                foreign_tenant = ControlTenantModel(
                    slug=f"foreign-tenant-{uuid4().hex}", name="Foreign tenant"
                )
                session.add(foreign_tenant)
                await session.flush()
                foreign_tenant_assistant = AssistantModel(
                    tenant_id=foreign_tenant.id,
                    slug=f"foreign-tenant-assistant-{uuid4().hex}",
                    name="Foreign tenant assistant",
                    status=AssistantStatus.ACTIVE,
                )
                session.add(foreign_tenant_assistant)
                await session.flush()
                foreign_tenant_target = await _other_scope_target(
                    session,
                    tenant=foreign_tenant,
                    assistant=foreign_tenant_assistant,
                    suffix=f"tenant-{uuid4().hex}",
                )
                for foreign_target in (
                    same_assistant_other_connection,
                    foreign_assistant_target,
                    foreign_tenant_target,
                ):
                    with pytest.raises(IntegrityError):
                        async with session.begin_nested():
                            await _incoming(
                                session,
                                conversation,
                                participant,
                                platform_id=f"foreign-command-{uuid4()}",
                                text="/voice",
                                reply_to=foreign_target,
                            )
                invalid_ids = {no_reply.id, user_reply.id}
            tts = _SessionCheckingTTS(database)
            assert (
                await consume_command_once(
                    settings,
                    database,
                    owner="spec038-invalid-targets",
                    tts_provider=tts,
                    rate_limiter=_AllowedRateLimiter(),
                    concurrency_limiter=_AvailableConcurrency(),
                )
                == 2
            )
            assert tts.requests == []
            async with database.session_factory() as session:
                result_codes = set(
                    await session.scalars(
                        select(TelegramCommandJobModel.result_code).where(
                            TelegramCommandJobModel.id.in_(invalid_ids)
                        )
                    )
                )
                assert result_codes == {"voice_target_unavailable"}
                assert (
                    await session.scalar(
                        select(func.count()).select_from(
                            TelegramVoiceGenerationJobModel
                        )
                    )
                    == 0
                )
                assert (
                    await session.scalar(
                        select(func.count()).select_from(GeneratedVoiceArtifactModel)
                    )
                    == 0
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(OutboundActionModel)
                        .where(OutboundActionModel.kind == OutboundActionKind.VOICE)
                    )
                    == 0
                )
        finally:
            await database.stop()

    asyncio.run(scenario())


def test_voice_concurrent_claim_and_stale_authority_activate_nothing() -> None:
    async def scenario() -> None:
        settings = _settings()
        database = Database(settings)
        await database.start()
        try:
            async with database.session_factory() as session, session.begin():
                await session.execute(
                    text(
                        "TRUNCATE control_operator_identities, control_tenants CASCADE"
                    )
                )
                conversation, _, _, command = await _seed_authority(session)
                connection = await session.get(
                    PlatformConnectionModel, conversation.platform_connection_id
                )
                assert connection is not None
                assistant_id = connection.assistant_id
                command_id = command.id
            tts = _BlockingTTS(database)

            async def first_worker() -> int:
                return await consume_command_once(
                    settings,
                    database,
                    owner="spec038-stale-first",
                    tts_provider=tts,
                    rate_limiter=_AllowedRateLimiter(),
                    concurrency_limiter=_AvailableConcurrency(),
                )

            async def invalidate_while_io_is_open() -> int:
                await tts.entered.wait()
                duplicate = await consume_command_once(
                    settings,
                    database,
                    owner="spec038-stale-duplicate",
                    tts_provider=tts,
                    rate_limiter=_AllowedRateLimiter(),
                    concurrency_limiter=_AvailableConcurrency(),
                )
                async with database.session_factory() as session, session.begin():
                    assistant = await session.get(AssistantModel, assistant_id)
                    assert assistant is not None
                    assistant.status = AssistantStatus.DISABLED
                tts.release.set()
                return duplicate

            consumed, duplicate = await asyncio.gather(
                first_worker(), invalidate_while_io_is_open()
            )
            assert (consumed, duplicate) == (1, 0)
            assert len(tts.requests) == 1
            async with database.session_factory() as session:
                command_row = await session.get(TelegramCommandJobModel, command_id)
                assert command_row is not None
                assert command_row.result_code == "voice_target_unavailable"
                voice_job = await session.scalar(
                    select(TelegramVoiceGenerationJobModel).where(
                        TelegramVoiceGenerationJobModel.command_job_id == command_id
                    )
                )
                assert voice_job is not None
                assert voice_job.status == VoiceGenerationStatus.STALE
                assert (
                    await session.scalar(
                        select(func.count()).select_from(GeneratedVoiceArtifactModel)
                    )
                    == 0
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(OutboundActionModel)
                        .where(OutboundActionModel.kind == OutboundActionKind.VOICE)
                    )
                    == 0
                )
        finally:
            await database.stop()

    asyncio.run(scenario())


def test_voice_duplicate_ingress_and_concurrent_workers_synthesize_once() -> None:
    async def scenario() -> None:
        settings = _settings()
        database = Database(settings)
        await database.start()
        try:
            async with database.session_factory() as session, session.begin():
                await session.execute(
                    text(
                        "TRUNCATE control_operator_identities, control_tenants CASCADE"
                    )
                )
                (
                    conversation,
                    participant,
                    delivered,
                    fixture_command,
                ) = await _seed_authority(session)
                fixture_command.status = CommandJobStatus.COMPLETED
                fixture_command.result_code = "fixture_only"
                fixture_command.completed_at = datetime.now(UTC)
                connection = await session.get(
                    PlatformConnectionModel, conversation.platform_connection_id
                )
                assert connection is not None
                assistant = await session.get(AssistantModel, connection.assistant_id)
                assert assistant is not None
                inbox_before = await session.scalar(
                    select(func.count()).select_from(IncomingPlatformUpdateModel)
                )
                target_platform_id = delivered[0].platform_message_id
                command_platform_id = f"duplicate-voice-{uuid4().hex}"
                raw_payload: dict[str, object] = {
                    "update_id": 3_800_000_001,
                    "message": {
                        "message_id": command_platform_id,
                        "date": 1_800_000_000,
                        "chat": {
                            "id": conversation.platform_conversation_id,
                            "type": "private",
                        },
                        "from": {
                            "id": participant.platform_user_id,
                            "first_name": "User",
                            "is_bot": False,
                        },
                        "text": "/voice",
                        "entities": [{"type": "bot_command", "offset": 0, "length": 6}],
                        "reply_to_message": {
                            "message_id": target_platform_id,
                            "from": {
                                "id": connection.external_bot_id,
                                "first_name": assistant.name,
                                "is_bot": True,
                            },
                            "text": "forged Telegram quote is never TTS authority",
                        },
                    },
                }
                connection_id = connection.id
                assistant_platform_user_id = connection.external_bot_id
                assistant_name = assistant.name
                expected_text = (
                    await session.get(
                        ResponsePlanModel,
                        (
                            await session.get(
                                OutboundActionModel, delivered[0].outbound_action_id
                            )
                        ).response_plan_id,  # type: ignore[union-attr]
                    )
                ).text  # type: ignore[union-attr]

            parsed = parse_telegram_update(raw_payload)
            envelope = parsed.to_ingress(
                platform_connection_id=connection_id,
                ingress_source=IngressSource.WEBHOOK,
                received_at=datetime.now(UTC),
            )
            ingress = SqlAlchemyDurableIngressRepository(
                database.session_factory, settings.ingress_event_schema_version
            )
            first, second = await asyncio.gather(
                ingress.accept(envelope), ingress.accept(envelope)
            )
            assert {first.duplicate, second.duplicate} == {False, True}
            assert first.incoming_update_id == second.incoming_update_id
            event = IngressQueueEvent(
                schema_version=settings.ingress_event_schema_version,
                incoming_update_id=first.incoming_update_id,
                platform=Platform.TELEGRAM,
                platform_connection_id=connection_id,
                platform_update_id=parsed.update_id,
                update_type=parsed.update_type,
                received_at=envelope.received_at,
            )
            normalized = normalize_telegram_update(
                parsed,
                platform_connection_id=connection_id,
                assistant_platform_user_id=assistant_platform_user_id,
                assistant_display_name=assistant_name,
                assistant_username=None,
            )
            processor = SqlAlchemyConversationProcessor(database.session_factory)
            processed = await asyncio.gather(
                processor.process(event, normalized),
                processor.process(event, normalized),
            )
            assert {item.duplicate for item in processed} == {False, True}
            async with database.session_factory() as session:
                assert (
                    await session.scalar(
                        select(func.count()).select_from(IncomingPlatformUpdateModel)
                    )
                    == inbox_before + 1
                )
                assert (
                    await session.scalar(
                        select(func.count()).select_from(IngressOutboxEventModel)
                    )
                    == 1
                )
                command = await session.scalar(
                    select(TelegramCommandJobModel).where(
                        TelegramCommandJobModel.command_name == "voice",
                        TelegramCommandJobModel.status == CommandJobStatus.PENDING,
                    )
                )
                assert command is not None
                command_id = command.id
            tts = _SessionCheckingTTS(database)
            consumed = await asyncio.gather(
                consume_command_once(
                    settings,
                    database,
                    owner="spec038-duplicate-a",
                    tts_provider=tts,
                    rate_limiter=_AllowedRateLimiter(),
                    concurrency_limiter=_AvailableConcurrency(),
                ),
                consume_command_once(
                    settings,
                    database,
                    owner="spec038-duplicate-b",
                    tts_provider=tts,
                    rate_limiter=_AllowedRateLimiter(),
                    concurrency_limiter=_AvailableConcurrency(),
                ),
            )
            assert sorted(consumed) == [0, 1]
            assert len(tts.requests) == 1
            assert tts.requests[0].text == expected_text
            assert "forged Telegram quote" not in tts.requests[0].text
            async with database.session_factory() as session:
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(TelegramVoiceGenerationJobModel)
                        .where(
                            TelegramVoiceGenerationJobModel.command_job_id == command_id
                        )
                    )
                    == 1
                )
                assert (
                    await session.scalar(
                        select(func.count()).select_from(GeneratedVoiceArtifactModel)
                    )
                    == 1
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(OutboundActionModel)
                        .where(OutboundActionModel.kind == OutboundActionKind.VOICE)
                    )
                    == 1
                )
        finally:
            await database.stop()

    asyncio.run(scenario())


def test_voice_pre_io_crash_reclaims_one_reservation_and_calls_tts_once() -> None:
    async def scenario() -> None:
        settings = _settings()
        database = Database(settings)
        await database.start()
        try:
            async with database.session_factory() as session, session.begin():
                await session.execute(
                    text(
                        "TRUNCATE control_operator_identities, control_tenants CASCADE"
                    )
                )
                await _seed_authority(session)
            claimed = await SqlAlchemyCommandRepository(database.session_factory).claim(
                "spec038-crashed-owner", 1, settings.command_lease_seconds
            )
            assert len(claimed) == 1
            voice = SqlAlchemyVoiceRepository(database.session_factory)
            preparation = await voice.prepare(
                claimed[0].id,
                "spec038-crashed-owner",
                settings.command_lease_seconds,
            )
            assert preparation.outcome == VoicePreparationOutcome.ACCEPTED
            assert preparation.job_id is not None
            governance = SqlAlchemyProviderGovernanceRepository(
                database.session_factory,
                mode=GovernanceMode.ENFORCE,
                reservation_lease_seconds=settings.provider_reservation_lease_seconds,
            )
            source = await governance.voice_source(preparation.job_id)
            requirements: dict[str, object] = {
                "text_to_speech": True,
                "voice_format": "ogg_opus",
                "maximum_input_characters": 4000,
                "maximum_output_bytes": 5_242_880,
                "allowed_data_classes": ["approved_external"],
                "require_current_health": True,
            }
            routes = await governance.resolve_routes(
                source, WorkloadClass.TEXT_TO_SPEECH, requirements
            )
            assert len(routes) == 1
            admission = await governance.reserve_attempt(
                source,
                routes[0],
                WorkloadClass.TEXT_TO_SPEECH,
                ProviderOperation.VOICE_SYNTHESIS,
                RouteRole.PRIMARY,
                1,
                None,
                None,
            )
            assert admission.allowed
            assert await voice.bind_provider_attempt(
                preparation.job_id,
                "spec038-crashed-owner",
                admission.attempt_id,
            )
            expired = datetime.now(UTC) - timedelta(seconds=1)
            async with database.session_factory() as session, session.begin():
                command = await session.get(
                    TelegramCommandJobModel, claimed[0].id, with_for_update=True
                )
                voice_job = await session.get(
                    TelegramVoiceGenerationJobModel,
                    preparation.job_id,
                    with_for_update=True,
                )
                assert command is not None and voice_job is not None
                command.lease_expires_at = expired
                voice_job.lease_expires_at = expired
            tts = _SessionCheckingTTS(database)
            assert (
                await consume_command_once(
                    settings,
                    database,
                    owner="spec038-recovery-owner",
                    tts_provider=tts,
                    rate_limiter=_AllowedRateLimiter(),
                    concurrency_limiter=_AvailableConcurrency(),
                )
                == 1
            )
            assert len(tts.requests) == 1
            async with database.session_factory() as session:
                attempts = list(
                    await session.scalars(
                        select(ProviderUsageAttemptModel).where(
                            ProviderUsageAttemptModel.voice_generation_job_id
                            == preparation.job_id
                        )
                    )
                )
                assert len(attempts) == 1
                assert attempts[0].id == admission.attempt_id
                assert attempts[0].state == ProviderAttemptState.IO_COMPLETE
                assert attempts[0].provider_outcome == ProviderAttemptOutcome.SUCCESS
                assert attempts[0].request_count == 1
                assert attempts[0].reservation_owner == "spec038-recovery-owner"
                assert (
                    await session.scalar(
                        select(func.count()).select_from(GeneratedVoiceArtifactModel)
                    )
                    == 1
                )
        finally:
            await database.stop()

    asyncio.run(scenario())


def test_voice_regenerated_target_uses_only_the_exact_regeneration_plan() -> None:
    async def scenario() -> None:
        settings = _settings()
        database = Database(settings)
        await database.start()
        try:
            async with database.session_factory() as session, session.begin():
                await session.execute(
                    text(
                        "TRUNCATE control_operator_identities, control_tenants CASCADE"
                    )
                )
                (
                    conversation,
                    participant,
                    delivered,
                    original_voice,
                ) = await _seed_authority(session)
                original_voice.status = CommandJobStatus.COMPLETED
                original_voice.result_code = "fixture_only"
                original_voice.completed_at = datetime.now(UTC)
                root_action = await session.get(
                    OutboundActionModel, delivered[0].outbound_action_id
                )
                assert root_action is not None
                root_plan = await session.get(
                    ResponsePlanModel, root_action.response_plan_id
                )
                assert root_plan is not None
                regeneration_message = await _incoming(
                    session,
                    conversation,
                    participant,
                    platform_id=f"regenerate-command-{uuid4()}",
                    text="/regenerate",
                    reply_to=delivered[0],
                )
                regeneration_record = await _processing_record(
                    session, conversation, regeneration_message
                )
                regeneration_command = TelegramCommandJobModel(
                    conversation_processing_record_id=regeneration_record.id,
                    conversation_id=conversation.id,
                    message_id=regeneration_message.id,
                    participant_id=participant.id,
                    command_name="regenerate",
                    arguments="",
                    status=CommandJobStatus.LEASED,
                    lease_owner="spec038-regeneration-admission",
                    lease_expires_at=datetime.now(UTC) + timedelta(seconds=60),
                    attempt_count=1,
                )
                session.add(regeneration_command)
                await session.flush()
                regeneration_command_id = regeneration_command.id
                source_message_id = root_plan.reply_to_message_id
            assert (
                await SqlAlchemyRegenerationRepository(database.session_factory).accept(
                    regeneration_command_id,
                    "spec038-regeneration-admission",
                )
                == RegenerationAdmission.ACCEPTED
            )
            async with database.session_factory() as session, session.begin():
                regeneration_job = await session.scalar(
                    select(ResponsePlanningJobModel).where(
                        ResponsePlanningJobModel.source_command_job_id
                        == regeneration_command_id
                    )
                )
                assert regeneration_job is not None
                regeneration_job.status = PlanningJobStatus.LEASED
                regeneration_job.lease_owner = "spec038-regeneration-planner"
                regeneration_job.lease_expires_at = datetime.now(UTC) + timedelta(
                    seconds=60
                )
                regeneration_job.attempt_count = 1
                regeneration_job_id = regeneration_job.id
                prompt_version = regeneration_job.prompt_version
                schema_version = regeneration_job.response_schema_version
            regenerated_text = "Only this regenerated answer may become voice."
            regenerated_plan_id = await SqlAlchemyPlanningRepository(
                database.session_factory
            ).complete(
                regeneration_job_id,
                "spec038-regeneration-planner",
                ResponsePlanCandidate(
                    should_respond=True,
                    reason_code=PlanReasonCode.ANSWER,
                    text=regenerated_text,
                    reply_to_message_id=source_message_id,
                    confidence=1,
                ),
                ProviderId.OPENAI,
                "test-only-regeneration-model",
                None,
                prompt_version,
                schema_version,
                expected_attempt=1,
            )
            assert regenerated_plan_id is not None
            async with database.session_factory() as session, session.begin():
                regenerated_action = await session.scalar(
                    select(OutboundActionModel).where(
                        OutboundActionModel.response_plan_id == regenerated_plan_id,
                        OutboundActionModel.kind == OutboundActionKind.TEXT,
                    )
                )
                assert regenerated_action is not None
                regenerated_action.status = OutboundActionStatus.DELIVERED
                regenerated_action.completed_at = datetime.now(UTC)
                regenerated_message = MessageModel(
                    conversation_id=regenerated_action.conversation_id,
                    outbound_action_id=regenerated_action.id,
                    platform_message_id=f"regenerated-answer-{uuid4()}",
                    direction=MessageDirection.OUTGOING,
                    message_type=MessageType.TEXT,
                    text=regenerated_action.text,
                    processing_status=MessageProcessingStatus.PROCESSED,
                    platform_sent_at=datetime.now(UTC),
                )
                session.add(regenerated_message)
                await session.flush()
                regenerated_action.delivered_message_id = regenerated_message.id
                conversation = await session.get(
                    ConversationModel, regenerated_action.conversation_id
                )
                assert conversation is not None
                participant = await session.scalar(
                    select(ParticipantModel).where(
                        ParticipantModel.conversation_id == conversation.id
                    )
                )
                assert participant is not None
                voice = await _voice_command(
                    session,
                    conversation,
                    participant,
                    reply_to=regenerated_message,
                )
                voice_id = voice.id
            tts = _SessionCheckingTTS(database)
            assert (
                await consume_command_once(
                    settings,
                    database,
                    owner="spec038-regenerated-voice",
                    tts_provider=tts,
                    rate_limiter=_AllowedRateLimiter(),
                    concurrency_limiter=_AvailableConcurrency(),
                )
                == 1
            )
            assert len(tts.requests) == 1
            assert tts.requests[0].text == regenerated_text
            assert "first chunk" not in tts.requests[0].text
            async with database.session_factory() as session:
                voice_job = await session.scalar(
                    select(TelegramVoiceGenerationJobModel).where(
                        TelegramVoiceGenerationJobModel.command_job_id == voice_id
                    )
                )
                assert voice_job is not None
                assert voice_job.source_response_plan_id == regenerated_plan_id
        finally:
            await database.stop()

    asyncio.run(scenario())


def test_voice_rate_denial_and_over_limit_source_call_tts_zero() -> None:
    async def scenario() -> None:
        settings = _settings()
        database = Database(settings)
        await database.start()
        try:
            async with database.session_factory() as session, session.begin():
                await session.execute(
                    text(
                        "TRUNCATE control_operator_identities, control_tenants CASCADE"
                    )
                )
                _, _, _, too_long = await _seed_authority(session, plan_text="x" * 4001)
                too_long_id = too_long.id
            tts = _SessionCheckingTTS(database)
            assert (
                await consume_command_once(
                    settings,
                    database,
                    owner="spec038-too-long",
                    tts_provider=tts,
                    rate_limiter=_AllowedRateLimiter(),
                    concurrency_limiter=_AvailableConcurrency(),
                )
                == 1
            )
            assert tts.requests == []
            async with database.session_factory() as session:
                command = await session.get(TelegramCommandJobModel, too_long_id)
                assert command is not None
                assert command.result_code == "voice_too_long"
                assert (
                    await session.scalar(
                        select(func.count()).select_from(
                            TelegramVoiceGenerationJobModel
                        )
                    )
                    == 0
                )

            async with database.session_factory() as session, session.begin():
                await session.execute(
                    text(
                        "TRUNCATE control_operator_identities, control_tenants CASCADE"
                    )
                )
                _, _, _, denied = await _seed_authority(session)
                denied_id = denied.id
            assert (
                await consume_command_once(
                    settings,
                    database,
                    owner="spec038-rate-denied",
                    tts_provider=tts,
                    rate_limiter=_DeniedRateLimiter(),
                    concurrency_limiter=_AvailableConcurrency(),
                )
                == 1
            )
            assert tts.requests == []
            async with database.session_factory() as session:
                command = await session.get(TelegramCommandJobModel, denied_id)
                assert command is not None
                assert command.result_code == "voice_tts_admission_denied"
                voice_job = await session.scalar(
                    select(TelegramVoiceGenerationJobModel).where(
                        TelegramVoiceGenerationJobModel.command_job_id == denied_id
                    )
                )
                assert voice_job is not None
                assert voice_job.status == VoiceGenerationStatus.FAILED
                assert voice_job.failure_reason == VoiceFailureReason.ADMISSION_DENIED
                attempt = await session.scalar(
                    select(ProviderUsageAttemptModel).where(
                        ProviderUsageAttemptModel.voice_generation_job_id
                        == voice_job.id
                    )
                )
                assert attempt is not None
                assert attempt.state == ProviderAttemptState.NO_IO
                assert attempt.provider_outcome == ProviderAttemptOutcome.RATE_LIMITED
                assert (
                    await session.scalar(
                        select(func.count()).select_from(GeneratedVoiceArtifactModel)
                    )
                    == 0
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(OutboundActionModel)
                        .where(OutboundActionModel.kind == OutboundActionKind.VOICE)
                    )
                    == 0
                )
        finally:
            await database.stop()

    asyncio.run(scenario())


def test_voice_budget_concurrency_and_unavailable_route_call_tts_zero() -> None:
    async def scenario() -> None:
        settings = _settings()
        database = Database(settings)
        await database.start()
        try:

            async def assert_denial(
                command_id: UUID,
                *,
                owner: str,
                concurrency: object,
                result_code: str,
                attempt_outcome: ProviderAttemptOutcome | None,
            ) -> None:
                tts = _SessionCheckingTTS(database)
                assert (
                    await consume_command_once(
                        settings,
                        database,
                        owner=owner,
                        tts_provider=tts,
                        rate_limiter=_AllowedRateLimiter(),
                        concurrency_limiter=concurrency,  # type: ignore[arg-type]
                    )
                    == 1
                )
                assert tts.requests == []
                async with database.session_factory() as session:
                    command = await session.get(TelegramCommandJobModel, command_id)
                    assert command is not None
                    assert command.result_code == result_code
                    job = await session.scalar(
                        select(TelegramVoiceGenerationJobModel).where(
                            TelegramVoiceGenerationJobModel.command_job_id == command_id
                        )
                    )
                    assert job is not None
                    attempt = await session.scalar(
                        select(ProviderUsageAttemptModel).where(
                            ProviderUsageAttemptModel.voice_generation_job_id == job.id
                        )
                    )
                    if attempt_outcome is None:
                        assert attempt is None
                    else:
                        assert attempt is not None
                        assert attempt.state == ProviderAttemptState.NO_IO
                        assert attempt.provider_outcome == attempt_outcome
                    assert (
                        await session.scalar(
                            select(func.count()).select_from(
                                GeneratedVoiceArtifactModel
                            )
                        )
                        == 0
                    )
                    assert (
                        await session.scalar(
                            select(func.count())
                            .select_from(OutboundActionModel)
                            .where(OutboundActionModel.kind == OutboundActionKind.VOICE)
                        )
                        == 0
                    )

            async with database.session_factory() as session, session.begin():
                await session.execute(
                    text(
                        "TRUNCATE control_operator_identities, control_tenants CASCADE"
                    )
                )
                _, _, _, command = await _seed_authority(session)
                command_id = command.id
                head = await session.scalar(select(ProviderBudgetHeadModel))
                assert head is not None
                current = await session.get(
                    ProviderBudgetRevisionModel, head.budget_revision_id
                )
                assert current is not None
                denied = ProviderBudgetRevisionModel(
                    budget_id=current.budget_id,
                    version=2,
                    amount=1,
                    mode=BudgetMode.HARD,
                    alert_threshold_bps=8000,
                    effective_at=datetime.now(UTC),
                    created_by_identity_id=current.created_by_identity_id,
                )
                session.add(denied)
                await session.flush()
                head.budget_revision_id = denied.id
                head.lock_version += 1
            await assert_denial(
                command_id,
                owner="spec038-budget-denied",
                concurrency=_AvailableConcurrency(),
                result_code="voice_tts_admission_denied",
                attempt_outcome=ProviderAttemptOutcome.BUDGET_DENIED,
            )

            async with database.session_factory() as session, session.begin():
                await session.execute(
                    text(
                        "TRUNCATE control_operator_identities, control_tenants CASCADE"
                    )
                )
                _, _, _, command = await _seed_authority(session)
                command_id = command.id
            await assert_denial(
                command_id,
                owner="spec038-concurrency-denied",
                concurrency=_DeniedConcurrency(),
                result_code="voice_tts_admission_denied",
                attempt_outcome=ProviderAttemptOutcome.CONCURRENCY_LIMITED,
            )

            async with database.session_factory() as session, session.begin():
                await session.execute(
                    text(
                        "TRUNCATE control_operator_identities, control_tenants CASCADE"
                    )
                )
                _, _, _, command = await _seed_authority(session)
                command_id = command.id
                capability_state = await session.scalar(
                    select(ProviderCapabilityStateModel)
                )
                assert capability_state is not None
                capability_state.lifecycle = ProviderLifecycle.DISABLED
            await assert_denial(
                command_id,
                owner="spec038-route-unavailable",
                concurrency=_AvailableConcurrency(),
                result_code="voice_tts_unsupported",
                attempt_outcome=None,
            )
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    (
        "provider_type",
        "result_code",
        "job_status",
        "job_reason",
        "attempt_state",
        "attempt_outcome",
    ),
    [
        (
            _UncertainTTS,
            "voice_tts_generation_uncertain",
            VoiceGenerationStatus.IO_POSSIBLE,
            VoiceFailureReason.PROVIDER_UNCERTAIN,
            ProviderAttemptState.IO_STARTED,
            ProviderAttemptOutcome.PENDING,
        ),
        (
            _WrongModelTTS,
            "voice_tts_generation_failed",
            VoiceGenerationStatus.FAILED,
            VoiceFailureReason.PROVIDER_FAILED,
            ProviderAttemptState.IO_COMPLETE,
            ProviderAttemptOutcome.INVALID_OUTPUT,
        ),
        (
            _OversizedOutputTTS,
            "voice_tts_generation_failed",
            VoiceGenerationStatus.FAILED,
            VoiceFailureReason.PROVIDER_FAILED,
            ProviderAttemptState.IO_COMPLETE,
            ProviderAttemptOutcome.INVALID_OUTPUT,
        ),
    ],
)
def test_voice_uncertain_or_route_mismatched_provider_output_never_activates(
    provider_type: type[_SessionCheckingTTS],
    result_code: str,
    job_status: VoiceGenerationStatus,
    job_reason: VoiceFailureReason,
    attempt_state: ProviderAttemptState,
    attempt_outcome: ProviderAttemptOutcome,
) -> None:
    async def scenario() -> None:
        settings = _settings()
        database = Database(settings)
        await database.start()
        try:
            async with database.session_factory() as session, session.begin():
                await session.execute(
                    text(
                        "TRUNCATE control_operator_identities, control_tenants CASCADE"
                    )
                )
                _, _, _, command = await _seed_authority(session)
                command_id = command.id
            provider = provider_type(database)
            assert (
                await consume_command_once(
                    settings,
                    database,
                    owner=f"spec038-{job_status.value}",
                    tts_provider=provider,
                    rate_limiter=_AllowedRateLimiter(),
                    concurrency_limiter=_AvailableConcurrency(),
                )
                == 1
            )
            assert len(provider.requests) == 1
            assert (
                await consume_command_once(
                    settings,
                    database,
                    owner="spec038-no-blind-retry",
                    tts_provider=provider,
                    rate_limiter=_AllowedRateLimiter(),
                    concurrency_limiter=_AvailableConcurrency(),
                )
                == 0
            )
            assert len(provider.requests) == 1
            async with database.session_factory() as session:
                command = await session.get(TelegramCommandJobModel, command_id)
                assert command is not None
                assert command.result_code == result_code
                job = await session.scalar(
                    select(TelegramVoiceGenerationJobModel).where(
                        TelegramVoiceGenerationJobModel.command_job_id == command_id
                    )
                )
                assert job is not None
                assert job.status == job_status
                assert job.failure_reason == job_reason
                attempt = await session.scalar(
                    select(ProviderUsageAttemptModel).where(
                        ProviderUsageAttemptModel.voice_generation_job_id == job.id
                    )
                )
                assert attempt is not None
                assert attempt.state == attempt_state
                assert attempt.provider_outcome == attempt_outcome
                assert (
                    await session.scalar(
                        select(func.count()).select_from(GeneratedVoiceArtifactModel)
                    )
                    == 0
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(OutboundActionModel)
                        .where(OutboundActionModel.kind == OutboundActionKind.VOICE)
                    )
                    == 0
                )
        finally:
            await database.stop()

    asyncio.run(scenario())


def test_voice_retry_reuses_the_same_artifact_without_new_tts() -> None:
    async def scenario() -> None:
        settings = _settings()
        database = Database(settings)
        await database.start()
        try:
            async with database.session_factory() as session, session.begin():
                await session.execute(
                    text(
                        "TRUNCATE control_operator_identities, control_tenants CASCADE"
                    )
                )
                await _seed_authority(session)
            tts, action_id, artifact_id = await _generate_voice(
                settings, database, owner="spec038-retry-generate"
            )
            telegram = _SequencedTelegram(
                database,
                PlatformAdapterError(
                    PlatformErrorCategory.SERVER,
                    "sendVoice",
                    retryable=True,
                    delivery_certainty=DeliveryCertainty.NOT_SENT,
                ),
            )
            assert (
                await deliver_once(
                    settings,
                    database,
                    adapter=telegram,  # type: ignore[arg-type]
                    rate_limiter=_AllowedRateLimiter(),
                )
                == 1
            )
            assert len(telegram.requests) == 1
            async with database.session_factory() as session, session.begin():
                action = await session.get(OutboundActionModel, action_id)
                assert action is not None
                assert action.status == OutboundActionStatus.PENDING
                assert action.generated_voice_artifact_id == artifact_id
                action.available_at = datetime.now(UTC)
            assert (
                await deliver_once(
                    settings,
                    database,
                    adapter=telegram,  # type: ignore[arg-type]
                    rate_limiter=_AllowedRateLimiter(),
                )
                == 1
            )
            assert len(tts.requests) == 1
            assert len(telegram.requests) == 2
            assert telegram.requests[0].audio_bytes == _AUDIO
            assert telegram.requests[1].audio_bytes == _AUDIO
            async with database.session_factory() as session:
                action = await session.get(OutboundActionModel, action_id)
                assert action is not None
                assert action.status == OutboundActionStatus.DELIVERED
                assert action.generated_voice_artifact_id == artifact_id
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(OutboundDeliveryAttemptModel)
                        .where(
                            OutboundDeliveryAttemptModel.outbound_action_id == action_id
                        )
                    )
                    == 2
                )
                assert (
                    await session.scalar(
                        select(func.count()).select_from(GeneratedVoiceArtifactModel)
                    )
                    == 1
                )
        finally:
            await database.stop()

    asyncio.run(scenario())


def test_voice_ambiguous_telegram_delivery_is_not_immediately_retried() -> None:
    async def scenario() -> None:
        settings = _settings()
        database = Database(settings)
        await database.start()
        try:
            async with database.session_factory() as session, session.begin():
                await session.execute(
                    text(
                        "TRUNCATE control_operator_identities, control_tenants CASCADE"
                    )
                )
                await _seed_authority(session)
            tts, action_id, artifact_id = await _generate_voice(
                settings, database, owner="spec038-ambiguous-generate"
            )
            telegram = _SequencedTelegram(
                database,
                PlatformAdapterError(
                    PlatformErrorCategory.TIMEOUT,
                    "sendVoice",
                    delivery_certainty=DeliveryCertainty.UNKNOWN,
                ),
            )
            assert (
                await deliver_once(
                    settings,
                    database,
                    adapter=telegram,  # type: ignore[arg-type]
                    rate_limiter=_AllowedRateLimiter(),
                )
                == 1
            )
            assert len(tts.requests) == 1
            assert len(telegram.requests) == 1
            assert (
                await deliver_once(
                    settings,
                    database,
                    adapter=telegram,  # type: ignore[arg-type]
                    rate_limiter=_AllowedRateLimiter(),
                )
                == 0
            )
            assert len(tts.requests) == 1
            assert len(telegram.requests) == 1
            async with database.session_factory() as session:
                action = await session.get(OutboundActionModel, action_id)
                assert action is not None
                assert action.status == OutboundActionStatus.DELIVERY_UNKNOWN
                assert action.generated_voice_artifact_id == artifact_id
                artifact = await session.get(GeneratedVoiceArtifactModel, artifact_id)
                assert artifact is not None
                assert artifact.action_terminal_at is not None
                assert artifact.audio_bytes == _AUDIO
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(OutboundDeliveryAttemptModel)
                        .where(
                            OutboundDeliveryAttemptModel.outbound_action_id == action_id
                        )
                    )
                    == 1
                )
        finally:
            await database.stop()

    asyncio.run(scenario())


def test_voice_privacy_erasure_purges_bytes_and_blocks_replay_delivery() -> None:
    async def scenario() -> None:
        settings = _settings()
        database = Database(settings)
        await database.start()
        try:
            async with database.session_factory() as session, session.begin():
                await session.execute(
                    text(
                        "TRUNCATE control_operator_identities, control_tenants CASCADE"
                    )
                )
                conversation, participant, delivered, command = await _seed_authority(
                    session
                )
                connection = await session.get(
                    PlatformConnectionModel, conversation.platform_connection_id
                )
                assert connection is not None
                assistant_id = connection.assistant_id
                connection_id = connection.id
                platform_user_id = participant.platform_user_id
                command_id = command.id
                conversation_id = conversation.id
                participant_id = participant.id
                replay_target_id = delivered[0].id
            tts, action_id, artifact_id = await _generate_voice(
                settings, database, owner="spec038-privacy-generate"
            )
            async with database.session_factory() as session, session.begin():
                conversation = await session.get(ConversationModel, conversation_id)
                participant = await session.get(ParticipantModel, participant_id)
                replay_target = await session.get(MessageModel, replay_target_id)
                assert conversation is not None
                assert participant is not None
                assert replay_target is not None
                replay = await _voice_command(
                    session,
                    conversation,
                    participant,
                    reply_to=replay_target,
                )
                replay_id = replay.id
            result = await SqlAlchemyPrivacyRepository(
                database.session_factory
            ).erase_subject(
                assistant_id=assistant_id,
                platform_connection_id=connection_id,
                platform_user_id=platform_user_id,
                command_job_id=command_id,
            )
            assert result.already_deleted is False
            telegram = _SessionCheckingTelegram(database)
            assert (
                await deliver_once(
                    settings,
                    database,
                    adapter=telegram,  # type: ignore[arg-type]
                    rate_limiter=_AllowedRateLimiter(),
                )
                == 0
            )
            assert telegram.requests == []
            assert (
                await consume_command_once(
                    settings,
                    database,
                    owner="spec038-erased-replay",
                    tts_provider=tts,
                    rate_limiter=_AllowedRateLimiter(),
                    concurrency_limiter=_AvailableConcurrency(),
                )
                == 1
            )
            assert len(tts.requests) == 1
            async with database.session_factory() as session:
                artifact = await session.get(GeneratedVoiceArtifactModel, artifact_id)
                assert artifact is not None
                assert artifact.status == VoiceArtifactStatus.PURGED
                assert artifact.audio_bytes is None
                assert artifact.purged_at is not None
                action = await session.get(OutboundActionModel, action_id)
                assert action is not None
                assert action.status == OutboundActionStatus.PERMANENTLY_FAILED
                assert action.last_error_category == "privacy_erasure"
                replay = await session.get(TelegramCommandJobModel, replay_id)
                assert replay is not None
                assert replay.result_code == "voice_target_unavailable"
                assert (
                    await session.scalar(
                        select(func.count()).select_from(GeneratedVoiceArtifactModel)
                    )
                    == 1
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(OutboundActionModel)
                        .where(OutboundActionModel.kind == OutboundActionKind.VOICE)
                    )
                    == 1
                )
        finally:
            await database.stop()

    asyncio.run(scenario())


def test_voice_retention_purges_expired_bytes_and_fails_queued_delivery() -> None:
    async def scenario() -> None:
        settings = _settings()
        database = Database(settings)
        await database.start()
        try:
            async with database.session_factory() as session, session.begin():
                await session.execute(
                    text(
                        "TRUNCATE control_operator_identities, control_tenants CASCADE"
                    )
                )
                await _seed_authority(session)
            _, action_id, artifact_id = await _generate_voice(
                settings, database, owner="spec038-retention-generate"
            )
            current = datetime.now(UTC)
            async with database.session_factory() as session, session.begin():
                artifact = await session.get(GeneratedVoiceArtifactModel, artifact_id)
                assert artifact is not None
                artifact.expires_at = current - timedelta(seconds=1)
            counts = await SqlAlchemyRetentionRepository(
                database.session_factory
            ).redact_once(
                now=current,
                retention_days=36_500,
                governance_audit_retention_days=36_500,
                schedule_history_retention_days=36_500,
                batch_size=100,
            )
            assert counts.voice_artifacts == 1
            telegram = _SessionCheckingTelegram(database)
            assert (
                await deliver_once(
                    settings,
                    database,
                    adapter=telegram,  # type: ignore[arg-type]
                    rate_limiter=_AllowedRateLimiter(),
                )
                == 0
            )
            assert telegram.requests == []
            async with database.session_factory() as session:
                artifact = await session.get(GeneratedVoiceArtifactModel, artifact_id)
                assert artifact is not None
                assert artifact.status == VoiceArtifactStatus.PURGED
                assert artifact.audio_bytes is None
                assert artifact.purged_at == current
                action = await session.get(OutboundActionModel, action_id)
                assert action is not None
                assert action.status == OutboundActionStatus.PERMANENTLY_FAILED
                assert action.last_error_category == "voice_artifact_expired"
        finally:
            await database.stop()

    asyncio.run(scenario())
