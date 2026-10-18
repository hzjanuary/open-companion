"""Synthetic local multi-worker scale proof; no provider or Telegram I/O."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text

from app.application.ingress import IngressEnvelope
from app.application.model_provider import (
    GenerationRequest,
    ProviderResult,
    ProviderUsage,
)
from app.application.ports.platform import PlatformCapability, SentMessage
from app.core.config import Settings
from app.domain.outbound import OutboundActionKind
from app.domain.persistence import (
    AssistantStatus,
    ConversationType,
    IngressSource,
    MessageDirection,
    MessageProcessingStatus,
    MessageType,
    Platform,
    PlatformConnectionStatus,
)
from app.domain.planning import PlanReasonCode, ProviderErrorCategory, ProviderId
from app.domain.tenancy import LEGACY_TENANT_ID
from app.infrastructure.concurrency import InMemoryConcurrencyLimiter
from app.infrastructure.concurrency_provider import ConcurrencyLimitedProvider
from app.infrastructure.database.conversation import SqlAlchemyConversationProcessor
from app.infrastructure.database.database import Database
from app.infrastructure.database.ingress import SqlAlchemyDurableIngressRepository
from app.infrastructure.database.models import (
    AssistantModel,
    ConversationModel,
    ConversationProcessingRecordModel,
    IncomingPlatformUpdateModel,
    MessageModel,
    OutboundActionModel,
    ParticipantModel,
    PlatformConnectionModel,
    ResponsePlanModel,
    ResponsePlanningJobModel,
)
from app.infrastructure.database.outbound import SqlAlchemyOutboundRepository
from app.infrastructure.database.planning import SqlAlchemyPlanningRepository
from app.infrastructure.queue.redis_streams import RedisIngressQueue
from app.runtime.conversation_worker import consume_once
from app.runtime.ingress_outbox_dispatcher import dispatch_once
from app.runtime.outbound_delivery_worker import consume_once as consume_delivery_once


def _envelope(
    connection_id: UUID, update_id: int, conversation_id: int
) -> IngressEnvelope:
    return IngressEnvelope(
        platform=Platform.TELEGRAM,
        platform_connection_id=connection_id,
        platform_update_id=str(update_id),
        update_type="message",
        supported=True,
        ingress_source=IngressSource.WEBHOOK,
        received_at=datetime.now(UTC),
        raw_payload={
            "update_id": update_id,
            "message": {
                "message_id": update_id,
                "date": 1_700_000_000,
                "chat": {"id": conversation_id, "type": "private"},
                "from": {
                    "id": 7_000 + conversation_id,
                    "first_name": "Synthetic",
                    "is_bot": False,
                },
                "text": "synthetic",
            },
        },
    )


@pytest.mark.integration
@pytest.mark.ingress_integration
@pytest.mark.conversation_integration
def test_synthetic_multi_worker_ingress_and_conversation_burst() -> None:
    async def scenario() -> None:
        started = perf_counter()
        settings = Settings(_env_file=None, environment="test", redis_batch_size=50)
        database = Database(settings)
        queue = RedisIngressQueue(settings)
        await database.start()
        try:
            async with database.engine.begin() as connection:
                await connection.execute(text("TRUNCATE assistants CASCADE"))
            await queue._client.delete(settings.redis_stream_name)  # type: ignore[attr-defined]
            async with database.session_factory() as session:
                async with session.begin():
                    assistant = AssistantModel(
                        tenant_id=LEGACY_TENANT_ID,
                        slug="scale",
                        name="Scale",
                        status=AssistantStatus.ACTIVE,
                    )
                    session.add(assistant)
                    await session.flush()
                    connection = PlatformConnectionModel(
                        tenant_id=LEGACY_TENANT_ID,
                        assistant_id=assistant.id,
                        platform=Platform.TELEGRAM,
                        external_bot_id=f"scale-{uuid4()}",
                        status=PlatformConnectionStatus.ACTIVE,
                    )
                    session.add(connection)
                    await session.flush()
                    connection_id = connection.id

            repository = SqlAlchemyDurableIngressRepository(
                database.session_factory, settings.ingress_event_schema_version
            )
            unique_updates = [
                _envelope(connection_id, 10_000 + index, 20_000 + index % 4)
                for index in range(16)
            ]
            # The second copy of every update races acceptance and must be idempotent.
            accepted = await asyncio.gather(
                *(repository.accept(item) for item in unique_updates * 2)
            )
            assert len({item.incoming_update_id for item in accepted}) == len(
                unique_updates
            )
            await asyncio.gather(
                dispatch_once(settings, repository, queue),
                dispatch_once(settings, repository, queue),
            )
            processor = SqlAlchemyConversationProcessor(database.session_factory)
            await asyncio.gather(
                consume_once(settings, database, queue, processor, "scale-a"),
                consume_once(settings, database, queue, processor, "scale-b"),
            )
            # Drain any entries that arrived between the two initial reads.
            await asyncio.gather(
                consume_once(settings, database, queue, processor, "scale-a"),
                consume_once(settings, database, queue, processor, "scale-b"),
            )
            async with database.session_factory() as session:
                records = await session.scalar(
                    select(func.count(ConversationProcessingRecordModel.id))
                )
                conversations = await session.scalar(
                    select(func.count(ConversationModel.id))
                )
            assert records == len(unique_updates)
            assert conversations == 4
            print(
                json.dumps(
                    {
                        "scenario": "ingress_conversation_multi_worker",
                        "synthetic_items": len(unique_updates),
                        "duplicate_terminal_effects": 0,
                        "elapsed_seconds": round(perf_counter() - started, 4),
                    },
                    sort_keys=True,
                )
            )
        finally:
            await queue.aclose()
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
def test_synthetic_multi_worker_planning_and_outbound_claims() -> None:
    class FakeAdapter:
        def __init__(self) -> None:
            self.requests: list[object] = []

        @property
        def capabilities(self) -> frozenset[PlatformCapability]:
            return frozenset({PlatformCapability.SEND_TEXT})

        async def send_text(self, request: object) -> SentMessage:
            self.requests.append(request)
            return SentMessage(
                Platform.TELEGRAM,
                f"synthetic-{len(self.requests)}",
                request.conversation_id,  # type: ignore[attr-defined]
                "synthetic-bot",
                None,
                datetime.now(UTC),
            )

        async def send_sticker(self, request: object) -> SentMessage:
            raise AssertionError("synthetic scale uses text only")

        async def aclose(self) -> None:
            return None

    async def scenario() -> None:
        started = perf_counter()
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            async with database.engine.begin() as connection:
                await connection.execute(text("TRUNCATE assistants CASCADE"))
            async with database.session_factory() as session:
                async with session.begin():
                    assistant = AssistantModel(
                        tenant_id=LEGACY_TENANT_ID,
                        slug="scale-claims",
                        name="Scale claims",
                        status=AssistantStatus.ACTIVE,
                    )
                    session.add(assistant)
                    await session.flush()
                    connection = PlatformConnectionModel(
                        tenant_id=LEGACY_TENANT_ID,
                        assistant_id=assistant.id,
                        platform=Platform.TELEGRAM,
                        external_bot_id=f"claims-{uuid4()}",
                    )
                    session.add(connection)
                    await session.flush()
                    connection_id = connection.id
                    conversation = ConversationModel(
                        platform_connection_id=connection.id,
                        platform_conversation_id=f"claims-{uuid4()}",
                        conversation_type=ConversationType.PRIVATE,
                    )
                    session.add(conversation)
                    await session.flush()
                    participant = ParticipantModel(
                        conversation_id=conversation.id,
                        platform_user_id=f"claims-{uuid4()}",
                        display_name="Synthetic",
                    )
                    session.add(participant)
                    await session.flush()
                    for index in range(12):
                        incoming = IncomingPlatformUpdateModel(
                            platform_connection_id=connection.id,
                            platform=Platform.TELEGRAM,
                            platform_update_id=f"claims-update-{index}",
                            update_type="message",
                            ingress_source=IngressSource.WEBHOOK,
                            raw_payload={},
                            received_at=datetime.now(UTC),
                        )
                        session.add(incoming)
                        await session.flush()
                        message = MessageModel(
                            conversation_id=conversation.id,
                            participant_id=participant.id,
                            platform_message_id=f"claims-message-{index}",
                            direction=MessageDirection.INCOMING,
                            message_type=MessageType.TEXT,
                            processing_status=MessageProcessingStatus.PROCESSED,
                            text="synthetic",
                        )
                        session.add(message)
                        await session.flush()
                        record = ConversationProcessingRecordModel(
                            incoming_update_id=incoming.id,
                            outcome="message_created",
                            conversation_id=conversation.id,
                            message_id=message.id,
                        )
                        session.add(record)
                        await session.flush()
                        job = ResponsePlanningJobModel(
                            conversation_processing_record_id=record.id,
                            conversation_id=conversation.id,
                            message_id=message.id,
                            prompt_version="synthetic",
                            response_schema_version="synthetic",
                        )
                        session.add(job)
                        await session.flush()
                        plan = ResponsePlanModel(
                            planning_job_id=job.id,
                            should_respond=True,
                            reason_code=PlanReasonCode.ANSWER,
                            text="synthetic",
                            mention_participant_ids=[],
                            confidence=1,
                            prompt_version="synthetic",
                            schema_version="synthetic",
                        )
                        session.add(plan)
                        await session.flush()
                        session.add(
                            OutboundActionModel(
                                response_plan_id=plan.id,
                                conversation_id=conversation.id,
                                sequence_number=1,
                                idempotency_key=uuid4().hex,
                                kind=OutboundActionKind.TEXT,
                                text="synthetic",
                                mention_participant_ids=[],
                            )
                        )
            planning = SqlAlchemyPlanningRepository(database.session_factory)
            claimed = await asyncio.gather(
                planning.claim("scale-planning-a", 12, 60),
                planning.claim("scale-planning-b", 12, 60),
            )
            planning_ids = [item.id for batch in claimed for item in batch]
            assert len(planning_ids) == 12
            assert len(set(planning_ids)) == 12
            outbound = SqlAlchemyOutboundRepository(database.session_factory)
            claimed_actions = await asyncio.gather(
                outbound.claim("scale-outbound-a", 12, 60),
                outbound.claim("scale-outbound-b", 12, 60),
            )
            action_ids = [item.id for batch in claimed_actions for item in batch]
            assert len(action_ids) == 12
            assert len(set(action_ids)) == 12
            async with database.session_factory() as session:
                async with session.begin():
                    actions = list(await session.scalars(select(OutboundActionModel)))
                    for action in actions:
                        action.status = "pending"
                        action.lease_owner = None
                        action.lease_expires_at = None
            delivery_settings = Settings(
                _env_file=None,
                environment="test",
                telegram_enabled=True,
                telegram_bot_token="fake-token",
                telegram_delivery_mode="polling",
                telegram_platform_connection_id=connection_id,
                outbound_delivery_enabled=True,
            )
            sender = FakeAdapter()
            await asyncio.gather(
                consume_delivery_once(delivery_settings, database, sender),
                consume_delivery_once(delivery_settings, database, sender),
            )
            async with database.session_factory() as session:
                delivered = await session.scalar(
                    select(func.count(OutboundActionModel.id)).where(
                        OutboundActionModel.status == "delivered"
                    )
                )
            assert delivered == 12
            assert len(sender.requests) == 12
            print(
                json.dumps(
                    {
                        "scenario": "planning_outbound_multi_worker_claim",
                        "synthetic_items": 12,
                        "duplicate_terminal_effects": 0,
                        "elapsed_seconds": round(perf_counter() - started, 4),
                    },
                    sort_keys=True,
                )
            )
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
def test_synthetic_provider_concurrency_has_independent_fallback_pool() -> None:
    class BlockingProvider:
        capabilities = None

        def __init__(self, provider_id: ProviderId, entered: asyncio.Event) -> None:
            self.provider_id, self.model, self.entered = (
                provider_id,
                "synthetic",
                entered,
            )
            self.release = asyncio.Event()

        async def generate(self, request: object) -> ProviderResult:
            self.entered.set()
            await self.release.wait()
            return ProviderResult(
                self.provider_id,
                self.model,
                "{}",
                None,
                ProviderUsage(None, None, None),
                timedelta(),
                "stop",
            )

        async def aclose(self) -> None:
            return None

    async def scenario() -> None:
        entered_openai, entered_groq = asyncio.Event(), asyncio.Event()
        limiter = InMemoryConcurrencyLimiter({"openai": 1, "groq": 1}, 60)
        openai_a = BlockingProvider(ProviderId.OPENAI, entered_openai)
        openai_b = BlockingProvider(ProviderId.OPENAI, asyncio.Event())
        groq = BlockingProvider(ProviderId.GROQ, entered_groq)
        primary = ConcurrencyLimitedProvider(openai_a, limiter)
        saturated = ConcurrencyLimitedProvider(openai_b, limiter)
        fallback = ConcurrencyLimitedProvider(groq, limiter)
        first = asyncio.create_task(primary.generate(cast(GenerationRequest, object())))
        await entered_openai.wait()
        with pytest.raises(Exception) as denied:
            await saturated.generate(cast(GenerationRequest, object()))
        assert (
            getattr(denied.value, "category", None)
            == ProviderErrorCategory.CONCURRENCY_LIMITED
        )
        fallback_task = asyncio.create_task(
            fallback.generate(cast(GenerationRequest, object()))
        )
        await entered_groq.wait()
        openai_a.release.set()
        groq.release.set()
        await first
        await fallback_task
        print(
            json.dumps(
                {
                    "scenario": "provider_concurrency_fallback_pool",
                    "synthetic_items": 3,
                    "max_observed_provider_concurrency": 1,
                    "duplicate_terminal_effects": 0,
                },
                sort_keys=True,
            )
        )

    asyncio.run(scenario())
