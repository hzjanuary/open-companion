"""Live PostgreSQL authority and response-isolation proof for SPEC-037."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.application.model_provider import (
    ProviderCapabilities,
    ProviderResult,
    ProviderUsage,
)
from app.application.ports.platform import (
    PlatformAdapterError,
    PlatformErrorCategory,
    SetReactionRequest,
)
from app.application.ports.telemetry import NoOpMetricsRecorder
from app.core.config import Settings
from app.domain.ambient import ParticipationTrigger
from app.domain.conversation import MembershipStatus
from app.domain.persistence import (
    AssistantStatus,
    ConversationStatus,
    IngressSource,
    MessageType,
    Platform,
    PlatformConnectionStatus,
    TenantStatus,
)
from app.domain.planning import PlanningJobStatus, ProviderId
from app.domain.reactions import ReactionKind
from app.infrastructure.database.conversation import SqlAlchemyConversationProcessor
from app.infrastructure.database.database import Database
from app.infrastructure.database.ingress import SqlAlchemyDurableIngressRepository
from app.infrastructure.database.models import (
    AssistantModel,
    ControlTenantModel,
    ConversationModel,
    ConversationProcessingRecordModel,
    ConversationSummaryJobModel,
    ConversationSummaryModel,
    ExplicitMemorySemanticIndexJobModel,
    IncomingPlatformUpdateModel,
    IngressOutboxEventModel,
    KnowledgeChunkModel,
    KnowledgeDocumentModel,
    KnowledgeDocumentRevisionModel,
    KnowledgeIndexJobModel,
    MemoryControlOperationModel,
    MemoryEventModel,
    MemoryItemModel,
    MessageModel,
    OutboundActionModel,
    ParticipantModel,
    PlatformConnectionModel,
    ResponsePlanModel,
    ResponsePlanningJobModel,
    TelegramCommandJobModel,
)
from app.infrastructure.database.reactions import (
    ReactionScope,
    SqlAlchemyReactionAuthority,
)
from app.infrastructure.telegram.updates import parse_telegram_update
from app.runtime.conversation_worker import process_event
from app.runtime.response_planning_worker import _attempt_reaction, consume_once

from .test_ingress import clear, seed_connection
from .test_provider_governance_schema import _AllowedRateLimiter
from .test_telegram_presence_worker import _Concurrency, _prepare_job

pytestmark = [pytest.mark.integration, pytest.mark.telegram_reactions_integration]
FIXED_TIME = datetime(2026, 9, 20, 12, tzinfo=UTC)


class _Generator:
    provider_id = ProviderId.OPENAI
    model = "spec026-model"
    capabilities = ProviderCapabilities(True, True, "max_tokens", True, True)

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, request: object) -> ProviderResult:
        del request
        self.calls += 1
        return ProviderResult(
            self.provider_id,
            self.model,
            '{"should_respond":true,"reason_code":"answer",'
            '"text":"You are welcome.","confidence":1.0}',
            None,
            ProviderUsage(None, None, None),
            timedelta(),
            "stop",
        )

    async def aclose(self) -> None:
        return None


class _ReactionRecorder:
    def __init__(
        self,
        database: Database,
        failure: PlatformErrorCategory | None = None,
    ) -> None:
        self.database = database
        self.failure = failure
        self.requests: list[SetReactionRequest] = []

    async def set_reaction(self, request: SetReactionRequest) -> None:
        assert self.database.engine.pool.checkedout() == 0
        self.requests.append(request)
        if self.failure is not None:
            raise PlatformAdapterError(
                self.failure,
                "setMessageReaction",
                retryable=self.failure
                in {PlatformErrorCategory.RATE_LIMITED, PlatformErrorCategory.SERVER},
            )


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        telegram_enabled=True,
        telegram_bot_token="synthetic-token",
        llm_enabled=True,
        llm_openai_model="spec026-model",
        llm_openai_api_key="synthetic",
        llm_max_output_tokens=300,
        provider_governance_mode="legacy",
        provider_governance_worker_enabled=False,
        control_plane_enabled=True,
        control_plane_jwt_secret="x" * 32,
        control_plane_jwt_issuer="issuer",
        control_plane_jwt_audience="audience",
    )


async def _prepare_reaction_job(database: Database) -> tuple[UUID, ReactionScope]:
    job_id, conversation_id = await _prepare_job(database)
    async with database.session_factory() as session, session.begin():
        job = await session.get(ResponsePlanningJobModel, job_id)
        conversation = await session.get(ConversationModel, conversation_id)
        assert job is not None and conversation is not None
        connection = await session.get(
            PlatformConnectionModel, conversation.platform_connection_id
        )
        assert connection is not None
        participant = ParticipantModel(
            conversation_id=conversation.id,
            platform_user_id="37",
            display_name="User",
            membership_status=MembershipStatus.MEMBER,
            is_bot=False,
        )
        session.add(participant)
        await session.flush()
        message = await session.get(MessageModel, job.message_id)
        assert message is not None
        message.participant_id = participant.id
        message.platform_message_id = "42"
        message.text = "thanks"
        message.message_type = MessageType.TEXT
        message.eligible = True
        message.edited_at = None
        message.content_redacted_at = None
        message.platform_sent_at = FIXED_TIME
        conversation.platform_conversation_id = "-100"
        return job.id, ReactionScope(
            tenant_id=connection.tenant_id,
            assistant_id=connection.assistant_id,
            connection_id=connection.id,
            conversation_id=conversation.id,
        )


async def _counts(database: Database) -> dict[str, int]:
    models = {
        "memory_items": MemoryItemModel,
        "memory_events": MemoryEventModel,
        "memory_controls": MemoryControlOperationModel,
        "semantic_jobs": ExplicitMemorySemanticIndexJobModel,
        "knowledge_documents": KnowledgeDocumentModel,
        "knowledge_revisions": KnowledgeDocumentRevisionModel,
        "knowledge_chunks": KnowledgeChunkModel,
        "knowledge_jobs": KnowledgeIndexJobModel,
        "summaries": ConversationSummaryModel,
        "summary_jobs": ConversationSummaryJobModel,
    }
    async with database.session_factory() as session:
        return {
            name: int(await session.scalar(select(func.count()).select_from(model)))
            for name, model in models.items()
        }


async def _run_worker(
    database: Database,
    adapter: _ReactionRecorder,
    provider: _Generator | None = None,
) -> int:
    return await consume_once(
        _settings(),
        database,
        owner="reaction-worker",
        primary_provider=provider or _Generator(),
        rate_limiter=_AllowedRateLimiter(),
        concurrency_limiter=_Concurrency(),
        reaction_adapter=adapter,
    )


def test_reaction_runs_once_after_durable_response_and_outside_database() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            job_id, _ = await _prepare_reaction_job(database)
            before = await _counts(database)
            adapter = _ReactionRecorder(database)
            provider = _Generator()

            assert await _run_worker(database, adapter, provider) == 1
            assert provider.calls == 1
            assert adapter.requests == [
                SetReactionRequest("-100", "42", kind=ReactionKind.HEART)
            ]
            async with database.session_factory() as session:
                job = await session.get(ResponsePlanningJobModel, job_id)
                assert job is not None
                assert job.status == PlanningJobStatus.COMPLETED
                assert (
                    await session.scalar(
                        select(func.count()).select_from(ResponsePlanModel)
                    )
                    == 1
                )
                actions = list(await session.scalars(select(OutboundActionModel)))
                assert len(actions) == 1
                assert actions[0].kind.value == "text"
            assert await _counts(database) == before
            assert await _run_worker(database, adapter, provider) == 0
            assert provider.calls == 1
            assert len(adapter.requests) == 1
            assert database.engine.pool.checkedout() == 0
        finally:
            await database.stop()

    asyncio.run(scenario())


def test_duplicate_update_identity_creates_one_job_and_one_reaction() -> None:
    async def scenario() -> None:
        settings = _settings()
        database = Database(settings)
        await database.start()
        try:
            await clear(database)
            connection_id = await seed_connection(database)
            repository = SqlAlchemyDurableIngressRepository(
                database.session_factory, settings.ingress_event_schema_version
            )
            update = parse_telegram_update(
                {
                    "update_id": 9_037,
                    "message": {
                        "message_id": 42,
                        "date": 1_700_000_000,
                        "chat": {"id": -100, "type": "private"},
                        "from": {
                            "id": 37,
                            "first_name": "User",
                            "is_bot": False,
                        },
                        "text": "thanks",
                    },
                }
            )
            envelope = update.to_ingress(
                platform_connection_id=connection_id,
                ingress_source=IngressSource.WEBHOOK,
                received_at=FIXED_TIME,
            )

            first, replay = await asyncio.gather(
                repository.accept(envelope), repository.accept(envelope)
            )
            assert {first.duplicate, replay.duplicate} == {False, True}
            assert first.incoming_update_id == replay.incoming_update_id

            async with database.session_factory() as session:
                outbox = await session.scalar(select(IngressOutboxEventModel))
                assert outbox is not None
                event = await repository.event_for(outbox.id)
            assert event is not None
            processor = SqlAlchemyConversationProcessor(database.session_factory)
            await process_event(event, settings, database, processor)
            await process_event(event, settings, database, processor)

            adapter = _ReactionRecorder(database)
            provider = _Generator()
            assert await _run_worker(database, adapter, provider) == 1
            assert provider.calls == 1
            assert await _run_worker(database, adapter, provider) == 0
            assert provider.calls == 1
            assert adapter.requests == [
                SetReactionRequest("-100", "42", ReactionKind.HEART)
            ]
            async with database.session_factory() as session:
                assert (
                    await session.scalar(
                        select(func.count()).select_from(IncomingPlatformUpdateModel)
                    )
                    == 1
                )
                assert (
                    await session.scalar(
                        select(func.count()).select_from(IngressOutboxEventModel)
                    )
                    == 1
                )
                assert (
                    await session.scalar(
                        select(func.count()).select_from(
                            ConversationProcessingRecordModel
                        )
                    )
                    == 1
                )
                assert (
                    await session.scalar(
                        select(func.count()).select_from(ResponsePlanningJobModel)
                    )
                    == 1
                )
        finally:
            await database.stop()

    asyncio.run(scenario())


def test_reaction_updates_stop_at_unsupported_durable_ingress() -> None:
    async def scenario() -> None:
        settings = Settings(_env_file=None, environment="test")
        database = Database(settings)
        await database.start()
        try:
            await clear(database)
            connection_id = await seed_connection(database)
            repository = SqlAlchemyDurableIngressRepository(
                database.session_factory, settings.ingress_event_schema_version
            )
            for index, update_type in enumerate(
                ("message_reaction", "message_reaction_count"), start=1
            ):
                update = parse_telegram_update(
                    {
                        "update_id": 8_000 + index,
                        update_type: {"chat": {"id": -100}, "message_id": 42},
                    }
                )
                accepted = await repository.accept(
                    update.to_ingress(
                        platform_connection_id=connection_id,
                        ingress_source=IngressSource.WEBHOOK,
                        received_at=FIXED_TIME,
                    )
                )
                assert accepted.duplicate is False
            async with database.session_factory() as session:
                incoming = list(
                    await session.scalars(select(IncomingPlatformUpdateModel))
                )
                assert len(incoming) == 2
                assert all(item.status.value == "rejected" for item in incoming)
                assert (
                    await session.scalar(
                        select(func.count()).select_from(IngressOutboxEventModel)
                    )
                    == 0
                )
                assert (
                    await session.scalar(
                        select(func.count()).select_from(ResponsePlanningJobModel)
                    )
                    == 0
                )
                assert (
                    await session.scalar(select(func.count()).select_from(MessageModel))
                    == 0
                )
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "failure",
    [
        PlatformErrorCategory.INVALID_REQUEST,
        PlatformErrorCategory.PERMISSION,
        PlatformErrorCategory.RATE_LIMITED,
        PlatformErrorCategory.SERVER,
        PlatformErrorCategory.TIMEOUT,
        PlatformErrorCategory.NETWORK,
        PlatformErrorCategory.MALFORMED_RESPONSE,
    ],
)
def test_every_typed_reaction_failure_leaves_response_ready(
    failure: PlatformErrorCategory,
) -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            job_id, _ = await _prepare_reaction_job(database)
            adapter = _ReactionRecorder(database, failure)
            provider = _Generator()

            assert await _run_worker(database, adapter, provider) == 1
            assert provider.calls == 1
            assert len(adapter.requests) == 1
            async with database.session_factory() as session:
                job = await session.get(ResponsePlanningJobModel, job_id)
                assert job is not None and job.status == PlanningJobStatus.COMPLETED
                assert (
                    await session.scalar(
                        select(func.count()).select_from(ResponsePlanModel)
                    )
                    == 1
                )
                assert (
                    await session.scalar(
                        select(func.count()).select_from(OutboundActionModel)
                    )
                    == 1
                )
            assert await _run_worker(database, adapter, provider) == 0
            assert provider.calls == 1
            assert len(adapter.requests) == 1
        finally:
            await database.stop()

    asyncio.run(scenario())


def test_current_authority_redaction_media_and_foreign_scope_fail_closed() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            job_id, scope = await _prepare_reaction_job(database)
            initial = _ReactionRecorder(database)
            assert await _run_worker(database, initial) == 1
            assert len(initial.requests) == 1
            authority = SqlAlchemyReactionAuthority(database.session_factory)

            async with database.session_factory() as session:
                job = await session.get(ResponsePlanningJobModel, job_id)
                assert job is not None
                attempt = job.attempt_count

            invalid_scopes = [
                ReactionScope(
                    uuid4(),
                    scope.assistant_id,
                    scope.connection_id,
                    scope.conversation_id,
                ),
                ReactionScope(
                    scope.tenant_id,
                    uuid4(),
                    scope.connection_id,
                    scope.conversation_id,
                ),
                ReactionScope(
                    scope.tenant_id,
                    scope.assistant_id,
                    uuid4(),
                    scope.conversation_id,
                ),
                ReactionScope(
                    scope.tenant_id,
                    scope.assistant_id,
                    scope.connection_id,
                    uuid4(),
                ),
            ]
            for invalid_scope in invalid_scopes:
                assert (
                    await authority.resolve(
                        job_id,
                        scope=invalid_scope,
                        expected_attempt=attempt,
                        safety_allowed=True,
                    )
                    is None
                )

            async def rejected_after(change: str) -> None:
                adapter = _ReactionRecorder(database)
                await _attempt_reaction(
                    authority,
                    adapter,
                    NoOpMetricsRecorder(),
                    job_id,
                    attempt,
                    scope=scope,
                    safety_allowed=True,
                )
                assert adapter.requests == [], change

            async with database.session_factory() as session, session.begin():
                assistant = await session.get(AssistantModel, scope.assistant_id)
                assert assistant is not None
                assistant.status = AssistantStatus.DISABLED
            await rejected_after("disabled Assistant")
            async with database.session_factory() as session, session.begin():
                assistant = await session.get(AssistantModel, scope.assistant_id)
                connection = await session.get(
                    PlatformConnectionModel, scope.connection_id
                )
                assert assistant is not None and connection is not None
                assistant.status = AssistantStatus.ACTIVE
                connection.status = PlatformConnectionStatus.DISABLED
            await rejected_after("disabled connection")
            async with database.session_factory() as session, session.begin():
                connection = await session.get(
                    PlatformConnectionModel, scope.connection_id
                )
                tenant = await session.get(ControlTenantModel, scope.tenant_id)
                assert connection is not None and tenant is not None
                connection.status = PlatformConnectionStatus.ACTIVE
                tenant.status = TenantStatus.DISABLED
            await rejected_after("disabled tenant")
            async with database.session_factory() as session, session.begin():
                tenant = await session.get(ControlTenantModel, scope.tenant_id)
                job = await session.get(ResponsePlanningJobModel, job_id)
                assert tenant is not None and job is not None
                message = await session.get(MessageModel, job.message_id)
                assert message is not None
                tenant.status = TenantStatus.ACTIVE
                message.content_redacted_at = FIXED_TIME
                message.text = None
            await rejected_after("redacted target")
            async with database.session_factory() as session, session.begin():
                job = await session.get(ResponsePlanningJobModel, job_id)
                assert job is not None
                message = await session.get(MessageModel, job.message_id)
                assert message is not None
                message.content_redacted_at = None
                message.text = "thanks"
                message.edited_at = FIXED_TIME
            await rejected_after("edited target")
            async with database.session_factory() as session, session.begin():
                job = await session.get(ResponsePlanningJobModel, job_id)
                assert job is not None
                message = await session.get(MessageModel, job.message_id)
                assert message is not None
                participant = await session.get(
                    ParticipantModel, message.participant_id
                )
                assert participant is not None
                message.edited_at = None
                participant.privacy_deleted_at = FIXED_TIME
            await rejected_after("privacy-erased participant")
            async with database.session_factory() as session, session.begin():
                job = await session.get(ResponsePlanningJobModel, job_id)
                assert job is not None
                message = await session.get(MessageModel, job.message_id)
                assert message is not None
                participant = await session.get(
                    ParticipantModel, message.participant_id
                )
                assert participant is not None
                participant.privacy_deleted_at = None
                message.message_type = MessageType.PHOTO
            await rejected_after("photo target")
            async with database.session_factory() as session, session.begin():
                job = await session.get(ResponsePlanningJobModel, job_id)
                assert job is not None
                message = await session.get(MessageModel, job.message_id)
                assert message is not None
                message.message_type = MessageType.VOICE
            await rejected_after("voice target")
            async with database.session_factory() as session, session.begin():
                job = await session.get(ResponsePlanningJobModel, job_id)
                assert job is not None
                message = await session.get(MessageModel, job.message_id)
                assert message is not None
                message.message_type = MessageType.TEXT
                job.trigger = ParticipationTrigger.AMBIENT
            await rejected_after("ambient target")
            async with database.session_factory() as session, session.begin():
                job = await session.get(ResponsePlanningJobModel, job_id)
                assert job is not None
                job.trigger = ParticipationTrigger.SCHEDULED
            await rejected_after("scheduled/proactive target")
            async with database.session_factory() as session, session.begin():
                job = await session.get(ResponsePlanningJobModel, job_id)
                connection = await session.get(
                    PlatformConnectionModel, scope.connection_id
                )
                assert job is not None and connection is not None
                job.trigger = ParticipationTrigger.ADDRESSED
                connection.platform = Platform.ZALO
            await rejected_after("non-Telegram target")
            async with database.session_factory() as session, session.begin():
                connection = await session.get(
                    PlatformConnectionModel, scope.connection_id
                )
                conversation = await session.get(
                    ConversationModel, scope.conversation_id
                )
                assert connection is not None and conversation is not None
                connection.platform = Platform.TELEGRAM
                conversation.status = ConversationStatus.PAUSED
            await rejected_after("paused conversation")
            async with database.session_factory() as session, session.begin():
                conversation = await session.get(
                    ConversationModel, scope.conversation_id
                )
                job = await session.get(ResponsePlanningJobModel, job_id)
                assert conversation is not None and job is not None
                message = await session.get(MessageModel, job.message_id)
                assert message is not None and message.participant_id is not None
                conversation.status = ConversationStatus.ACTIVE
                command = TelegramCommandJobModel(
                    conversation_processing_record_id=(
                        job.conversation_processing_record_id
                    ),
                    conversation_id=conversation.id,
                    message_id=message.id,
                    participant_id=message.participant_id,
                    command_name="memory",
                    arguments="",
                )
                session.add(command)
            await rejected_after("deterministic command")
            async with database.session_factory() as session, session.begin():
                command = await session.scalar(select(TelegramCommandJobModel))
                assert command is not None
                command.command_name = "regenerate"
            await rejected_after("/regenerate command")
            adapter = _ReactionRecorder(database)
            await _attempt_reaction(
                authority,
                adapter,
                NoOpMetricsRecorder(),
                job_id,
                attempt,
                scope=scope,
                safety_allowed=False,
            )
            assert adapter.requests == []
            assert database.engine.pool.checkedout() == 0
        finally:
            await database.stop()

    asyncio.run(scenario())
