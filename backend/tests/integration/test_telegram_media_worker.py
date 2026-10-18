"""Real planner + PostgreSQL admission + fake external media/provider I/O."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from app.application.model_provider import (
    ProviderCapabilities,
    ProviderError,
    ProviderResult,
    ProviderUsage,
    TranscriptionResult,
)
from app.core.config import Settings
from app.domain.media import EphemeralMedia, MediaKind, MediaStatus
from app.domain.persistence import MessageType
from app.domain.planning import PlanningJobStatus, ProviderErrorCategory, ProviderId
from app.domain.provider_governance import (
    BudgetMeasurement,
    BudgetMode,
    BudgetScope,
    BudgetWindowKind,
    ProviderDataClass,
    ProviderHealth,
    ProviderLifecycle,
    WorkloadClass,
)
from app.infrastructure.database.database import Database
from app.infrastructure.database.models import (
    AssistantModel,
    ConversationModel,
    MemoryItemModel,
    MessageMediaModel,
    MessageModel,
    OutboundActionModel,
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
)
from app.infrastructure.database.personality import ensure_conversation_configuration
from app.infrastructure.database.privacy import SqlAlchemyPrivacyRepository
from app.runtime.response_planning_worker import consume_once

from .test_provider_governance_schema import _AllowedRateLimiter, _seed

pytestmark = [pytest.mark.integration, pytest.mark.telegram_media_integration]


async def transcription_policy(session, actor, now):
    capability = ProviderCapabilityModel(
        provider_id=ProviderId.GROQ,
        adapter_key=ProviderId.GROQ,
        workload_class=WorkloadClass.TRANSCRIPTION,
        model="synthetic-transcription",
        capability_metadata={
            "speech_to_text": True,
            "audio_formats": ["audio/ogg", "audio/mpeg"],
            "maximum_audio_bytes": 5 * 1024 * 1024,
            "maximum_audio_duration_seconds": 120,
        },
        data_class=ProviderDataClass.APPROVED_EXTERNAL,
        credential_slot="groq",
        credential_configured=True,
        reservation_strategy="request_count",
        created_by_identity_id=actor,
    )
    session.add(capability)
    await session.flush()
    health = ProviderHealthPolicyRevisionModel(
        capability_id=capability.id,
        version=1,
        observation_window_seconds=300,
        degraded_threshold=2,
        unavailable_threshold=3,
        recovery_success_threshold=2,
        stale_after_seconds=300,
        effective_at=now,
        created_by_identity_id=actor,
    )
    policy = ProviderRoutingPolicyRevisionModel(
        scope_type=BudgetScope.DEPLOYMENT,
        scope_key="deployment",
        workload_class=WorkloadClass.TRANSCRIPTION,
        schema_version="provider-routing-v1",
        version=1,
        requirements={
            "speech_to_text": True,
            "allowed_data_classes": ["approved_external"],
            "require_current_health": True,
        },
        effective_at=now,
        created_by_identity_id=actor,
    )
    budget = ProviderBudgetModel(
        scope_type=BudgetScope.DEPLOYMENT,
        scope_key="deployment",
        workload_class=WorkloadClass.TRANSCRIPTION,
        measurement=BudgetMeasurement.REQUESTS,
        window_kind=BudgetWindowKind.DAILY_UTC,
    )
    session.add_all([health, policy, budget])
    await session.flush()
    revision = ProviderBudgetRevisionModel(
        budget_id=budget.id,
        version=1,
        amount=10,
        mode=BudgetMode.HARD,
        alert_threshold_bps=8000,
        effective_at=now,
        created_by_identity_id=actor,
    )
    session.add(revision)
    await session.flush()
    session.add_all(
        [
            ProviderCapabilityStateModel(
                capability_id=capability.id,
                lifecycle=ProviderLifecycle.ENABLED,
                health=ProviderHealth.READY,
                health_policy_revision_id=health.id,
                last_evaluated_at=now,
            ),
            ProviderRoutingPolicyRouteModel(
                policy_revision_id=policy.id, capability_id=capability.id, position=0
            ),
            ProviderRoutingPolicyHeadModel(
                scope_key="deployment",
                workload_class=WorkloadClass.TRANSCRIPTION,
                policy_revision_id=policy.id,
            ),
            ProviderPriceRevisionModel(
                capability_id=capability.id,
                currency="USD",
                unit_basis="transcription_request",
                request_rate=10,
                effective_from=now,
                created_by_identity_id=actor,
            ),
            ProviderBudgetHeadModel(
                budget_id=budget.id, budget_revision_id=revision.id
            ),
        ]
    )


@pytest.mark.parametrize(
    "kind,timeout,erase,crash",
    [
        (MediaKind.PHOTO, False, False, False),
        (MediaKind.VOICE, False, False, False),
        (MediaKind.VOICE, True, False, False),
        (MediaKind.PHOTO, False, True, False),
        (MediaKind.VOICE, False, True, False),
        (MediaKind.VOICE, True, False, True),
    ],
)
def test_worker_materializes_media_and_durable_text_once(kind, timeout, erase, crash):
    async def scenario():
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            job_id, _ = await _seed(database)
            now = datetime.now(UTC)
            async with database.session_factory() as session, session.begin():
                # This is delivery proof, not a prompt-size-dependent denial test.
                await session.execute(
                    update(ProviderBudgetRevisionModel).values(amount=1_000_000)
                )
                job = await session.get(ResponsePlanningJobModel, job_id)
                conversation = await session.get(ConversationModel, job.conversation_id)
                connection = await session.get(
                    PlatformConnectionModel, conversation.platform_connection_id
                )
                assistant = await session.get(AssistantModel, connection.assistant_id)
                configuration = await ensure_conversation_configuration(
                    session, assistant, conversation
                )
                participant = ParticipantModel(
                    conversation_id=conversation.id,
                    platform_user_id="synthetic",
                    display_name="Synthetic",
                )
                session.add(participant)
                await session.flush()
                message = await session.get(MessageModel, job.message_id)
                message.participant_id = participant.id
                message.message_type = MessageType(kind.value)
                message.platform_sent_at = now
                message.text = "caption"
                message.eligible = True
                message.metadata_ = {"content_provenance": "media_caption"}
                job.configuration_revision_id = configuration.id
                job.personality_profile_version_id = (
                    configuration.personality_profile_version_id
                )
                job.status = PlanningJobStatus.PENDING
                job.attempt_count = 0
                job.lease_owner = None
                job.lease_expires_at = None
                job.available_at = now
                mime = "image/jpeg" if kind == MediaKind.PHOTO else "audio/ogg"
                session.add(
                    MessageMediaModel(
                        message_id=message.id,
                        conversation_id=conversation.id,
                        kind=kind,
                        file_id="synthetic_file",
                        file_unique_id="synthetic_unique",
                        mime_type=mime,
                        width=1 if kind == MediaKind.PHOTO else None,
                        height=1 if kind == MediaKind.PHOTO else None,
                        duration_seconds=10 if kind == MediaKind.VOICE else None,
                        caption="caption",
                    )
                )
                capability = await session.scalar(select(ProviderCapabilityModel))
                # Test setup only: published runtime capabilities remain immutable.
                capability.capability_metadata = {
                    **capability.capability_metadata,
                    "image_input": True,
                    "maximum_image_input_tokens": 1000,
                }
                if kind == MediaKind.VOICE:
                    await transcription_policy(
                        session, capability.created_by_identity_id, now
                    )
                connection_id, message_id = connection.id, message.id
                assistant_id = assistant.id
            settings = Settings(
                _env_file=None,
                environment="test",
                telegram_enabled=True,
                telegram_bot_token="synthetic-token",
                telegram_platform_connection_id=connection_id,
                telegram_media_enabled=True,
                llm_enabled=True,
                llm_openai_model="spec026-model",
                llm_openai_api_key="synthetic",
                llm_max_output_tokens=300,
                provider_governance_mode="enforce",
                provider_governance_worker_enabled=True,
                control_plane_enabled=True,
                control_plane_jwt_secret="x" * 32,
                control_plane_jwt_issuer="issuer",
                control_plane_jwt_audience="audience",
            )
            calls = []

            class Concurrency:
                async def acquire(self, provider):
                    assert provider in {ProviderId.OPENAI, ProviderId.GROQ}
                    return SimpleNamespace(provider=provider, token="transient")

                async def release(self, lease):
                    pass

            class Downloader:
                async def download_media(self, attachment, before_io=None):
                    assert await before_io()
                    calls.append("download")
                    return EphemeralMedia(kind, mime, b"ephemeral-media", 1, 1)

            class Transcriber:
                provider_id = ProviderId.GROQ
                model = "synthetic-transcription"
                capabilities = ProviderCapabilities(False, False, None, False, True)

                async def transcribe(self, request):
                    calls.append("transcribe")
                    if crash:
                        raise asyncio.CancelledError
                    if timeout:
                        raise ProviderError(
                            ProviderErrorCategory.TIMEOUT,
                            self.provider_id,
                            self.model,
                            False,
                            "transcribe",
                            "synthetic timeout",
                        )
                    return TranscriptionResult(
                        self.provider_id,
                        self.model,
                        "derived user words",
                        None,
                        ProviderUsage(None, None, None),
                        timedelta(),
                    )

                async def aclose(self):
                    pass

            class Generator:
                provider_id = ProviderId.OPENAI
                model = "spec026-model"
                capabilities = ProviderCapabilities(
                    True, True, "max_tokens", True, True, image_input=True
                )

                async def generate(self, request):
                    calls.append("generate")
                    assert (request.current_image is not None) == (
                        kind == MediaKind.PHOTO
                    )
                    if kind == MediaKind.VOICE:
                        assert "derived user words" in request.user_content
                        assert "voice_transcript" in request.user_content
                    if erase:
                        # This must complete while provider I/O is in progress:
                        # no application DB lock/session may surround that I/O.
                        await asyncio.wait_for(
                            SqlAlchemyPrivacyRepository(
                                database.session_factory
                            ).erase_subject(
                                assistant_id=assistant_id,
                                platform_connection_id=connection_id,
                                platform_user_id="synthetic",
                                command_job_id=uuid4(),
                            ),
                            timeout=5,
                        )
                    return ProviderResult(
                        self.provider_id,
                        self.model,
                        '{"should_respond":true,"reason_code":"acknowledgement","text":"Hello","confidence":1.0}',
                        None,
                        ProviderUsage(None, None, None),
                        timedelta(),
                        "stop",
                    )

                async def aclose(self):
                    pass

            async def run():
                return await consume_once(
                    settings,
                    database,
                    owner="media-worker",
                    primary_provider=Generator(),
                    media_downloader=Downloader(),
                    transcription_provider=Transcriber(),
                    rate_limiter=_AllowedRateLimiter(),
                    concurrency_limiter=Concurrency(),
                )

            if crash:
                with pytest.raises(asyncio.CancelledError):
                    await run()
                async with database.session_factory() as session, session.begin():
                    attempt = await session.scalar(
                        select(ProviderUsageAttemptModel).where(
                            ProviderUsageAttemptModel.planning_job_id == job_id
                        )
                    )
                    assert attempt is not None and attempt.request_count == 1
                    assert attempt.state.value == "io_started"
                    expired = datetime.now(UTC) - timedelta(seconds=1)
                    await session.execute(
                        update(ResponsePlanningJobModel)
                        .where(ResponsePlanningJobModel.id == job_id)
                        .values(lease_expires_at=expired)
                    )
                    await session.execute(
                        update(MessageMediaModel)
                        .where(MessageMediaModel.message_id == message_id)
                        .values(lease_expires_at=expired)
                    )
            assert await run() == 1
            assert await run() == 0
            assert calls == (
                ["download", "transcribe"]
                if timeout
                else ["download", "generate"]
                if kind == MediaKind.PHOTO
                else ["download", "transcribe", "generate"]
            )
            async with database.session_factory() as session:
                media = await session.scalar(
                    select(MessageMediaModel).where(
                        MessageMediaModel.message_id == message_id
                    )
                )
                assert media.status == (
                    MediaStatus.REDACTED
                    if erase
                    else MediaStatus.AMBIGUOUS
                    if timeout
                    else MediaStatus.COMPLETE
                )
                message = await session.get(MessageModel, message_id)
                if erase:
                    job = await session.get(ResponsePlanningJobModel, job_id)
                    assert job.status == PlanningJobStatus.NO_RESPONSE
                assert message.text == (
                    None
                    if erase
                    else "caption"
                    if kind == MediaKind.PHOTO or timeout
                    else "derived user words"
                )
                assert await session.scalar(
                    select(func.count())
                    .select_from(ResponsePlanModel)
                    .where(ResponsePlanModel.planning_job_id == job_id)
                ) == (0 if erase else 1)
                assert await session.scalar(
                    select(func.count()).select_from(OutboundActionModel)
                ) == (0 if erase else 1)
                assert (
                    await session.scalar(
                        select(func.count()).select_from(MemoryItemModel)
                    )
                    == 0
                )
                attempts = list(
                    await session.scalars(
                        select(ProviderUsageAttemptModel).where(
                            ProviderUsageAttemptModel.planning_job_id == job_id
                        )
                    )
                )
                assert len(attempts) == (1 if kind == MediaKind.PHOTO or timeout else 2)
                assert all(item.request_count == 1 for item in attempts)
        finally:
            await database.stop()

    asyncio.run(scenario())
