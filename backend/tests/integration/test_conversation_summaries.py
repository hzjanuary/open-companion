import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from app.application.model_provider import ProviderResult, ProviderUsage
from app.core.config import Settings
from app.domain.persistence import (
    AssistantStatus,
    ConversationStatus,
    ConversationType,
    MessageDirection,
    MessageProcessingStatus,
    MessageType,
    ParticipantRole,
    Platform,
    PlatformConnectionStatus,
    ResponseMode,
)
from app.domain.planning import ProviderId
from app.domain.rate_limit import RateLimitDecision
from app.domain.summary import ConversationSummaryStatus
from app.domain.tenancy import LEGACY_TENANT_ID
from app.infrastructure.database.context import SqlAlchemyConversationContextReader
from app.infrastructure.database.database import Database
from app.infrastructure.database.models import (
    AssistantModel,
    ConversationModel,
    ConversationSummaryModel,
    MessageModel,
    ParticipantModel,
    PlatformConnectionModel,
)
from app.infrastructure.database.privacy import SqlAlchemyPrivacyRepository
from app.infrastructure.database.retention import SqlAlchemyRetentionRepository
from app.infrastructure.database.summaries import SqlAlchemySummaryRepository
from app.runtime.conversation_summary_worker import consume_once as consume_summary_once


async def _clear(database: Database) -> None:
    async with database.engine.begin() as connection:
        await connection.execute(text("TRUNCATE assistants CASCADE"))


@pytest.mark.integration
def test_summary_window_context_privacy_and_expiry_are_bounded() -> None:
    async def scenario() -> None:
        now = datetime.now(UTC).replace(microsecond=0)
        settings = Settings(
            _env_file=None,
            environment="test",
            conversation_summaries_enabled=True,
            summary_min_source_messages=2,
            summary_max_source_messages=3,
            raw_content_retention_days=30,
            context_token_budget=1000,
        )
        database = Database(settings)
        await database.start()
        await _clear(database)
        try:
            async with database.session_factory() as session:
                async with session.begin():
                    assistant = AssistantModel(
                        tenant_id=LEGACY_TENANT_ID,
                        slug="summary-test",
                        name="Summary test",
                        status=AssistantStatus.ACTIVE,
                    )
                    session.add(assistant)
                    await session.flush()
                    connection = PlatformConnectionModel(
                        tenant_id=LEGACY_TENANT_ID,
                        assistant_id=assistant.id,
                        platform=Platform.TELEGRAM,
                        external_bot_id=f"summary-{uuid4()}",
                        status=PlatformConnectionStatus.ACTIVE,
                    )
                    session.add(connection)
                    await session.flush()
                    conversation = ConversationModel(
                        platform_connection_id=connection.id,
                        platform_conversation_id=f"summary-{uuid4()}",
                        conversation_type=ConversationType.GROUP,
                        status=ConversationStatus.ACTIVE,
                        response_mode=ResponseMode.MENTION_ONLY,
                    )
                    session.add(conversation)
                    await session.flush()
                    participant = ParticipantModel(
                        conversation_id=conversation.id,
                        platform_user_id="summary-user",
                        display_name="Summary user",
                        role=ParticipantRole.MEMBER,
                    )
                    session.add(participant)
                    await session.flush()
                    messages: list[MessageModel] = []
                    for index in range(4):
                        message = MessageModel(
                            conversation_id=conversation.id,
                            participant_id=participant.id,
                            platform_message_id=f"summary-message-{index}",
                            direction=MessageDirection.INCOMING,
                            message_type=MessageType.TEXT,
                            processing_status=MessageProcessingStatus.PROCESSED,
                            text=f"synthetic message {index}",
                            platform_sent_at=now - timedelta(days=4 - index),
                        )
                        session.add(message)
                        messages.append(message)
                    await session.flush()
                    assistant_id, connection_id, focal_id = (
                        assistant.id,
                        connection.id,
                        messages[-1].id,
                    )

            summaries = SqlAlchemySummaryRepository(database.session_factory)
            assert (
                await summaries.schedule_available(
                    retention_days=30, minimum=2, maximum=3
                )
                == 1
            )
            assert (
                await summaries.schedule_available(
                    retention_days=30, minimum=2, maximum=3
                )
                == 0
            )
            claimed = await summaries.claim("summary-test", 1, 60)
            assert len(claimed) == 1
            source = await summaries.source_for_job(claimed[0], 30)
            assert source is not None and source.source_count == 3
            assert source.last_message_id != focal_id
            assert await summaries.complete(
                claimed[0].id,
                "summary-test",
                "compact synthetic history",
                None,
                None,
            )
            reader = SqlAlchemyConversationContextReader(
                database.session_factory, settings
            )
            context = await reader.build_for_message(focal_id, now=now)
            assert context is not None and context.historical_summary is not None
            assert context.historical_summary.summary == "compact synthetic history"
            assert not context.recent_history

            class FakeProvider:
                provider_id = ProviderId.OLLAMA
                model = "fake-summary-model"
                capabilities = None

                def __init__(self) -> None:
                    self.requests: list[object] = []

                async def generate(self, request: object) -> ProviderResult:
                    self.requests.append(request)
                    return ProviderResult(
                        ProviderId.OLLAMA,
                        self.model,
                        '{"summary":"next compact history"}',
                        None,
                        ProviderUsage(None, None, None),
                        timedelta(),
                        "stop",
                    )

                async def aclose(self) -> None:
                    return None

            async with database.session_factory() as session:
                async with session.begin():
                    for index in range(2):
                        session.add(
                            MessageModel(
                                conversation_id=claimed[0].conversation_id,
                                participant_id=participant.id,
                                platform_message_id=f"summary-next-{index}",
                                direction=MessageDirection.INCOMING,
                                message_type=MessageType.TEXT,
                                processing_status=MessageProcessingStatus.PROCESSED,
                                text=f"next synthetic message {index}",
                                platform_sent_at=now + timedelta(seconds=index + 1),
                            )
                        )
            fake = FakeProvider()
            configured = settings.model_copy(
                update={"summary_worker_enabled": True, "llm_enabled": True}
            )
            assert await consume_summary_once(configured, database, provider=fake) == 1
            assert len(fake.requests) == 1
            assert "compact synthetic history" not in fake.requests[0].user_content  # type: ignore[attr-defined]

            class DenyLimiter:
                async def check(self, *_: object) -> RateLimitDecision:
                    return RateLimitDecision(False, retry_after_seconds=1)

                async def is_ready(self) -> bool:
                    return True

                async def aclose(self) -> None:
                    return None

            async with database.session_factory() as session:
                async with session.begin():
                    for index in range(2):
                        session.add(
                            MessageModel(
                                conversation_id=claimed[0].conversation_id,
                                participant_id=participant.id,
                                platform_message_id=f"summary-rate-{index}",
                                direction=MessageDirection.INCOMING,
                                message_type=MessageType.TEXT,
                                processing_status=MessageProcessingStatus.PROCESSED,
                                text=f"rate limited synthetic {index}",
                                platform_sent_at=now + timedelta(seconds=index + 3),
                            )
                        )
            rate_limited = configured.model_copy(update={"rate_limit_enabled": True})
            assert (
                await consume_summary_once(
                    rate_limited,
                    database,
                    provider=fake,
                    rate_limiter=DenyLimiter(),  # type: ignore[arg-type]
                )
                == 0
            )
            assert len(fake.requests) == 1

            # Earliest source was day -4, so the exact deadline is now + 26 days.
            await SqlAlchemyRetentionRepository(database.session_factory).redact_once(
                now=now + timedelta(days=26), retention_days=30, batch_size=100
            )
            async with database.session_factory() as session:
                expired = await session.scalar(
                    select(ConversationSummaryModel).where(
                        ConversationSummaryModel.source_window_hash
                        == claimed[0].source_window_hash
                    )
                )
                assert expired is not None
                assert expired.status == ConversationSummaryStatus.EXPIRED
                assert expired.summary_text is None

            # Recreate one valid summary, then prove /forget_me invalidates it.
            async with database.session_factory() as session:
                async with session.begin():
                    summary = ConversationSummaryModel(
                        conversation_id=claimed[0].conversation_id,
                        platform_thread_id=None,
                        schema_version="conversation-summary-v1",
                        prompt_version="conversation-summary-prompt-v1",
                        source_first_message_id=claimed[0].source_first_message_id,
                        source_last_message_id=claimed[0].source_last_message_id,
                        source_started_at=claimed[0].source_started_at,
                        source_ended_at=claimed[0].source_ended_at,
                        source_count=claimed[0].source_count,
                        source_window_hash=f"privacy-{uuid4().hex}",
                        summary_text="will be invalidated",
                        status=ConversationSummaryStatus.COMPLETED,
                        expires_at=now + timedelta(days=1),
                    )
                    session.add(summary)
            erased = await SqlAlchemyPrivacyRepository(
                database.session_factory
            ).erase_subject(
                assistant_id=assistant_id,
                platform_connection_id=connection_id,
                platform_user_id="summary-user",
                command_job_id=uuid4(),
                now=now,
            )
            assert erased.summaries == 2
            context = await reader.build_for_message(focal_id, now=now)
            assert context is not None and context.historical_summary is None
        finally:
            await _clear(database)
            await database.stop()

    asyncio.run(scenario())
