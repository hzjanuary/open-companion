import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select, text

from app.application.ingress import IngressEnvelope
from app.application.model_provider import ProviderResult, ProviderUsage
from app.application.personality import PersonalityOverrides
from app.application.ports.platform import (
    PlatformAdapterError,
    PlatformCapability,
    PlatformErrorCategory,
    SendChatActionRequest,
    SentMessage,
    WebhookInfo,
)
from app.core.config import Settings
from app.domain.ambient import ParticipationTrigger
from app.domain.persistence import (
    AssistantStatus,
    IncomingUpdateStatus,
    IngressOutboxStatus,
    IngressSource,
    Platform,
    PlatformConnectionStatus,
    ResponseMode,
    TenantStatus,
)
from app.domain.planning import ProviderId
from app.domain.tenancy import LEGACY_TENANT_ID
from app.infrastructure.database.conversation import SqlAlchemyConversationProcessor
from app.infrastructure.database.database import Database
from app.infrastructure.database.group_configuration import (
    ConfigurationChange,
    SqlAlchemyGroupConfigurationService,
)
from app.infrastructure.database.ingress import (
    SqlAlchemyDurableIngressRepository,
    UnknownPlatformConnectionError,
)
from app.infrastructure.database.models import (
    AssistantModel,
    ControlTenantModel,
    ConversationModel,
    ConversationProcessingRecordModel,
    ConversationSummaryModel,
    ExplicitMemorySemanticIndexJobModel,
    IncomingPlatformUpdateModel,
    IngressOutboxEventModel,
    KnowledgeBaseModel,
    MemoryItemModel,
    MessageMediaModel,
    MessageModel,
    ModelGenerationAttemptModel,
    OutboundActionModel,
    PlatformConnectionModel,
    ResponsePlanModel,
    ResponsePlanningJobModel,
)
from app.infrastructure.queue.redis_streams import RedisIngressQueue
from app.main import create_app
from app.runtime.conversation_worker import consume_once
from app.runtime.demo_inspector import inspect_latest
from app.runtime.ingress_outbox_dispatcher import dispatch_once
from app.runtime.outbound_delivery_worker import consume_once as consume_delivery_once
from app.runtime.response_planning_worker import consume_once as consume_planning_once
from app.runtime.telegram_poller import poll_once


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
    )


async def clear(database: Database, queue: RedisIngressQueue | None = None) -> None:
    async with database.engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE conversation_processing_records, ingress_outbox_events, "
                "incoming_platform_updates, "
                "polling_cursors, messages, participants, conversations, "
                "platform_connections, assistants CASCADE"
            )
        )
    async with database.session_factory() as session, session.begin():
        if await session.get(ControlTenantModel, LEGACY_TENANT_ID) is None:
            session.add(
                ControlTenantModel(
                    id=LEGACY_TENANT_ID,
                    slug="legacy-default",
                    name="Legacy default",
                )
            )
    if queue is not None:
        await queue._client.delete(queue._settings.redis_stream_name)  # type: ignore[attr-defined]


async def seed_connection(database: Database) -> UUID:
    async with database.session_factory() as session:
        async with session.begin():
            assistant = AssistantModel(
                tenant_id=LEGACY_TENANT_ID,
                slug="ingress-test",
                name="Ingress Test",
                status=AssistantStatus.ACTIVE,
            )
            session.add(assistant)
            await session.flush()
            connection = PlatformConnectionModel(
                tenant_id=LEGACY_TENANT_ID,
                assistant_id=assistant.id,
                platform=Platform.TELEGRAM,
                external_bot_id=f"bot-{uuid4()}",
                status=PlatformConnectionStatus.ACTIVE,
            )
            session.add(connection)
            await session.flush()
            return connection.id


def envelope(
    connection_id: UUID,
    update_id: str = "4000000000",
    chat_id: int = 4_000_000_001,
    message_id: int = 4_000_000_000,
) -> IngressEnvelope:
    return IngressEnvelope(
        platform=Platform.TELEGRAM,
        platform_connection_id=connection_id,
        platform_update_id=update_id,
        update_type="message",
        supported=True,
        ingress_source=IngressSource.WEBHOOK,
        received_at=datetime.now(UTC),
        raw_payload={
            "update_id": int(update_id),
            "message": {
                "message_id": message_id,
                "date": 1_700_000_000,
                "chat": {"id": chat_id, "type": "private"},
                "from": {
                    "id": 4_000_000_002,
                    "first_name": "Tester",
                    "is_bot": False,
                },
                "text": "hello",
            },
        },
    )


@pytest.mark.integration
@pytest.mark.ingress_integration
@pytest.mark.conversation_integration
def test_conversation_worker_commits_before_ack_and_deduplicates(
    settings: Settings,
) -> None:
    async def scenario() -> None:
        database = Database(settings)
        queue = RedisIngressQueue(settings)
        await database.start()
        await clear(database, queue)
        connection_id = await seed_connection(database)
        repository = SqlAlchemyDurableIngressRepository(
            database.session_factory, settings.ingress_event_schema_version
        )
        accepted = await repository.accept(envelope(connection_id))
        async with database.session_factory() as session:
            outbox_id = await session.scalar(
                select(IngressOutboxEventModel.id).where(
                    IngressOutboxEventModel.incoming_update_id
                    == accepted.incoming_update_id
                )
            )
        assert outbox_id is not None
        event = await repository.event_for(outbox_id)
        assert event is not None
        assert await dispatch_once(settings, repository, queue) == 1
        processor = SqlAlchemyConversationProcessor(database.session_factory)
        assert (
            await consume_once(
                settings, database, queue, processor, "conversation-test"
            )
            == 1
        )
        async with database.session_factory() as session:
            assert (
                await session.scalar(
                    select(func.count(ConversationProcessingRecordModel.id))
                )
                == 1
            )
        await queue.publish(event)
        assert (
            await consume_once(
                settings, database, queue, processor, "conversation-test"
            )
            == 1
        )
        async with database.session_factory() as session:
            assert (
                await session.scalar(
                    select(func.count(ConversationProcessingRecordModel.id))
                )
                == 1
            )
        await queue.publish(event)

        class FailingProcessor:
            async def process(self, *_: object) -> None:
                raise RuntimeError("temporary database failure")

        with pytest.raises(RuntimeError, match="temporary database failure"):
            await consume_once(
                settings,
                database,
                queue,
                FailingProcessor(),  # type: ignore[arg-type]
                "failing-conversation-test",
                reclaim=False,
            )
        await asyncio.sleep(0.02)
        queue._settings.redis_reclaim_idle_ms = 1  # type: ignore[misc]
        assert (
            await consume_once(
                settings,
                database,
                queue,
                processor,
                "recovery-conversation-test",
            )
            == 1
        )
        await queue.aclose()
        await clear(database)
        await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.ingress_integration
@pytest.mark.conversation_integration
@pytest.mark.demo_integration
def test_demo_disallowed_chat_is_durably_ignored_before_downstream_work(
    settings: Settings,
) -> None:
    async def scenario() -> None:
        database = Database(settings)
        queue = RedisIngressQueue(settings)
        await database.start()
        try:
            await clear(database, queue)
            connection_id = await seed_connection(database)
            configured = settings.model_copy(
                update={
                    "telegram_enabled": True,
                    "telegram_bot_token": "fake-token",
                    "telegram_delivery_mode": "polling",
                    "telegram_platform_connection_id": connection_id,
                    "llm_enabled": True,
                    "llm_primary_provider": "ollama",
                    "llm_ollama_model": "fake-model",
                    "outbound_delivery_enabled": True,
                    "demo_live_enabled": True,
                    "demo_allowed_chat_ids": ("4000000001",),
                }
            )
            repository = SqlAlchemyDurableIngressRepository(
                database.session_factory, configured.ingress_event_schema_version
            )
            accepted = await repository.accept(
                envelope(connection_id, "6000000000", 4_000_000_009)
            )
            assert accepted.duplicate is False
            assert await dispatch_once(configured, repository, queue) == 1
            processor = SqlAlchemyConversationProcessor(database.session_factory)
            assert (
                await consume_once(configured, database, queue, processor, "deny") == 1
            )
            assert (
                await repository.accept(
                    envelope(connection_id, "6000000000", 4_000_000_009)
                )
            ).duplicate
            async with database.session_factory() as session:
                record = await session.scalar(select(ConversationProcessingRecordModel))
                assert record is not None
                assert record.permanent_error == "conversation_not_allowed"
                assert (
                    await session.scalar(
                        select(func.count(ResponsePlanningJobModel.id))
                    )
                    == 0
                )
                assert (
                    await session.scalar(select(func.count(OutboundActionModel.id)))
                    == 0
                )
                assert await session.scalar(select(func.count(MessageModel.id))) == 0
        finally:
            await queue.aclose()
            await clear(database)
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.ingress_integration
@pytest.mark.conversation_integration
@pytest.mark.planning_integration
@pytest.mark.delivery_integration
@pytest.mark.demo_integration
@pytest.mark.parametrize(
    "presence_error",
    [
        None,
        PlatformErrorCategory.INVALID_REQUEST,
        PlatformErrorCategory.AUTHENTICATION,
        PlatformErrorCategory.PERMISSION,
        PlatformErrorCategory.RATE_LIMITED,
        PlatformErrorCategory.SERVER,
        PlatformErrorCategory.TIMEOUT,
        PlatformErrorCategory.NETWORK,
        PlatformErrorCategory.MALFORMED_RESPONSE,
    ],
)
def test_eligible_ingress_creates_one_durable_response_plan(
    settings: Settings, presence_error: PlatformErrorCategory | None
) -> None:
    presence_requests: list[SendChatActionRequest] = []

    class FakeProvider:
        provider_id = ProviderId.OLLAMA
        model = "fake-model"
        capabilities = None

        def __init__(self) -> None:
            self.requests: list[object] = []

        async def generate(self, request: object) -> object:
            assert len(presence_requests) == 1
            self.requests.append(request)
            message_id = request.context.current.id  # type: ignore[attr-defined]
            return ProviderResult(
                ProviderId.OLLAMA,
                self.model,
                f'{{"should_respond":true,"reason_code":"social_reply","text":"hello","reply_to_message_id":"{message_id}","mentions":[],"sticker_intent":null,"confidence":0.8,"language":"vi"}}',
                None,
                ProviderUsage(None, None, None),
                timedelta(),
                "stop",
            )

        async def aclose(self) -> None:
            return None

    class FakeDeliveryAdapter:
        def __init__(self) -> None:
            self.requests: list[object] = []

        @property
        def capabilities(self) -> frozenset[PlatformCapability]:
            return frozenset({PlatformCapability.SEND_TEXT})

        async def send_text(self, request: object) -> SentMessage:
            self.requests.append(request)
            return SentMessage(
                Platform.TELEGRAM,
                "synthetic-outgoing-1",
                request.conversation_id,  # type: ignore[attr-defined]
                "synthetic-bot",
                request.message_thread_id,  # type: ignore[attr-defined]
                datetime.now(UTC),
            )

        async def send_sticker(self, request: object) -> SentMessage:
            raise AssertionError("stickers are not part of this synthetic proof")

        async def aclose(self) -> None:
            return None

    async def scenario() -> None:
        database = Database(settings)
        queue = RedisIngressQueue(settings)
        await database.start()
        await clear(database, queue)
        connection_id = await seed_connection(database)
        repository = SqlAlchemyDurableIngressRepository(database.session_factory, 1)
        await repository.accept(envelope(connection_id, "5000000000"))
        assert await dispatch_once(settings, repository, queue) == 1
        processor = SqlAlchemyConversationProcessor(database.session_factory)
        assert (
            await consume_once(settings, database, queue, processor, "planning-source")
            == 1
        )
        async with database.session_factory() as session:
            job = await session.scalar(select(ResponsePlanningJobModel))
            assert job is not None
            assert job.personality_profile_version_id is not None
            assert job.configuration_revision_id is not None
            conversation = await session.get(ConversationModel, job.conversation_id)
            connection = (
                await session.get(
                    PlatformConnectionModel, conversation.platform_connection_id
                )
                if conversation is not None
                else None
            )
            assert conversation is not None and connection is not None
            assistant_id = connection.assistant_id
            conversation_id = conversation.id
        revision = await SqlAlchemyGroupConfigurationService(
            database.session_factory
        ).apply(
            conversation_id,
            assistant_id,
            ConfigurationChange(overrides=PersonalityOverrides(humor_level=0.1)),
            expected_revision=1,
        )
        assert revision.revision_number == 2
        configured = settings.model_copy(
            update={
                "telegram_enabled": True,
                "telegram_bot_token": "fake-token",
                "telegram_delivery_mode": "polling",
                "telegram_platform_connection_id": connection_id,
                "llm_enabled": True,
                "llm_primary_provider": "ollama",
                "llm_ollama_model": "fake-model",
                "outbound_delivery_enabled": True,
                "demo_live_enabled": True,
                "demo_allowed_chat_ids": ("4000000001",),
            }
        )

        class FakePresence:
            async def send_chat_action(self, request: SendChatActionRequest) -> None:
                assert database.engine.pool.checkedout() == 0
                presence_requests.append(request)
                if presence_error is not None:
                    raise PlatformAdapterError(presence_error, "sendChatAction")

        fake = FakeProvider()
        assert (
            await consume_planning_once(
                configured,
                database,
                "planning-test",
                fake,
                presence_adapter=FakePresence(),
            )
            == 1
        )  # type: ignore[arg-type]
        assert presence_requests == [SendChatActionRequest("4000000001")]
        assert '"configuration_revision_number":1' in fake.requests[0].user_content  # type: ignore[attr-defined]
        assert (
            await consume_planning_once(configured, database, "planning-test", fake)
            == 0
        )  # type: ignore[arg-type]
        async with database.session_factory() as session:
            assert (
                await session.scalar(select(func.count(ModelGenerationAttemptModel.id)))
                == 1
            )
            assert await session.scalar(select(func.count(ResponsePlanModel.id))) == 1
            assert await session.scalar(select(func.count(OutboundActionModel.id))) == 1
        delivery = FakeDeliveryAdapter()
        assert await consume_delivery_once(configured, database, delivery) == 1  # type: ignore[arg-type]
        assert len(delivery.requests) == 1
        assert delivery.requests[0].conversation_id == "4000000001"  # type: ignore[attr-defined]
        assert delivery.requests[0].reply_to_message_id == "4000000000"  # type: ignore[attr-defined]
        duplicate = await repository.accept(envelope(connection_id, "5000000000"))
        assert duplicate.duplicate is True
        assert await dispatch_once(configured, repository, queue) == 0
        assert (
            await consume_planning_once(configured, database, "planning-test", fake)
            == 0
        )  # type: ignore[arg-type]
        assert await consume_delivery_once(configured, database, delivery) == 0  # type: ignore[arg-type]
        assert len(delivery.requests) == 1
        async with database.session_factory() as session:
            assert (
                await session.scalar(select(func.count(IncomingPlatformUpdateModel.id)))
                == 1
            )
            assert (
                await session.scalar(select(func.count(ModelGenerationAttemptModel.id)))
                == 1
            )
            assert await session.scalar(select(func.count(ResponsePlanModel.id))) == 1
            assert await session.scalar(select(func.count(OutboundActionModel.id))) == 1
            assert await session.scalar(select(func.count(MessageModel.id))) == 2
            assert await session.scalar(select(func.count(MemoryItemModel.id))) == 0
            assert (
                await session.scalar(
                    select(func.count(ExplicitMemorySemanticIndexJobModel.id))
                )
                == 0
            )
            assert await session.scalar(select(func.count(KnowledgeBaseModel.id))) == 0
            assert (
                await session.scalar(select(func.count(ConversationSummaryModel.id)))
                == 0
            )
            assert await session.scalar(select(func.count(MessageMediaModel.id))) == 0
        trace = await inspect_latest(configured, platform_update_id="5000000000")
        assert trace["latest_update"] is not None
        trace_stages = trace["trace"]
        assert trace_stages["ingress_outbox"]["status"] == "published"
        assert len(trace_stages["planning_jobs"]) == 1
        assert trace_stages["planning_jobs"][0]["configuration_revision_id"] is not None
        assert (
            trace_stages["planning_jobs"][0]["personality_profile_version_id"]
            is not None
        )
        assert len(trace_stages["generation_attempts"]) == 1
        assert len(trace_stages["response_plans"]) == 1
        assert trace_stages["outbound_actions"][0]["status"] == "delivered"
        assert trace_stages["delivery_attempts"][0]["certainty"] == "confirmed"
        paused = await SqlAlchemyGroupConfigurationService(
            database.session_factory
        ).apply(
            conversation_id,
            assistant_id,
            ConfigurationChange(response_mode=ResponseMode.PAUSED),
            expected_revision=2,
        )
        assert paused.revision_number == 3
        await repository.accept(
            envelope(connection_id, "5000000001", message_id=4_000_000_001)
        )
        assert await dispatch_once(configured, repository, queue) == 1
        assert (
            await consume_once(configured, database, queue, processor, "paused-source")
            == 1
        )
        async with database.session_factory() as session:
            assert (
                await session.scalar(select(func.count(ResponsePlanningJobModel.id)))
                == 1
            )
        assert (
            await consume_planning_once(configured, database, "planning-test", fake)
            == 0
        )  # type: ignore[arg-type]
        assert await consume_delivery_once(configured, database, delivery) == 0  # type: ignore[arg-type]
        assert len(fake.requests) == 1
        assert len(delivery.requests) == 1
        await queue.aclose()
        await clear(database)
        await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.ingress_integration
def test_durable_inbox_outbox_idempotency_and_dispatch(settings: Settings) -> None:
    async def scenario() -> None:
        database = Database(settings)
        queue = RedisIngressQueue(settings)
        await database.start()
        await clear(database, queue)
        connection_id = await seed_connection(database)
        repository = SqlAlchemyDurableIngressRepository(
            database.session_factory, settings.ingress_event_schema_version
        )
        first, duplicate = await asyncio.gather(
            repository.accept(envelope(connection_id)),
            repository.accept(envelope(connection_id)),
        )
        assert {first.duplicate, duplicate.duplicate} == {False, True}
        assert first.incoming_update_id == duplicate.incoming_update_id

        async with database.session_factory() as session:
            incoming_count = await session.scalar(
                select(func.count(IncomingPlatformUpdateModel.id))
            )
            outbox_count = await session.scalar(
                select(func.count(IngressOutboxEventModel.id))
            )
            assert incoming_count == 1
            assert outbox_count == 1

        assert await dispatch_once(settings, repository, queue) == 1
        async with database.session_factory() as session:
            incoming = await session.scalar(select(IncomingPlatformUpdateModel))
            outbox = await session.scalar(select(IngressOutboxEventModel))
            assert (
                incoming is not None and incoming.status == IncomingUpdateStatus.QUEUED
            )
            assert outbox is not None and outbox.status == IngressOutboxStatus.PUBLISHED

        await queue.ensure_group()
        received = await queue.read_new("test-consumer")
        assert len(received) == 1
        entry_id, event = received[0]
        assert event.incoming_update_id == first.incoming_update_id
        await queue.acknowledge(entry_id)

        await queue.publish(event)
        pending = await queue.read_new("failing-consumer")
        assert pending
        await asyncio.sleep(0.02)
        queue._settings.redis_reclaim_idle_ms = 1  # type: ignore[misc]
        reclaimed = await queue.reclaim("recovery-consumer")
        assert reclaimed
        await queue.aclose()
        await clear(database)
        await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.ingress_integration
def test_webhook_acknowledges_new_and_duplicate_without_queue_io() -> None:
    async def scenario() -> None:
        connection_id = uuid4()
        settings = Settings(
            _env_file=None,
            environment="test",
            telegram_enabled=True,
            telegram_bot_token="fake-token",
            telegram_delivery_mode="webhook",
            telegram_platform_connection_id=connection_id,
            telegram_webhook_secret_token="test-secret",
            telegram_webhook_public_base_url="https://example.invalid",
        )
        database = Database(settings)
        await database.start()
        await clear(database)
        actual_connection_id = await seed_connection(database)
        app = create_app(
            settings.model_copy(
                update={"telegram_platform_connection_id": actual_connection_id}
            )
        )
        app.state.database = database
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            path = f"/api/v1/platforms/telegram/webhook/{actual_connection_id}"
            headers = {
                "X-Telegram-Bot-Api-Secret-Token": "test-secret",
                "X-Request-ID": "hook-1",
            }
            payload = {"update_id": 4_000_000_001, "message": {"message_id": 1}}
            first = await client.post(path, headers=headers, json=payload)
            second = await client.post(path, headers=headers, json=payload)
            bad = await client.post(path, json=payload)
            assert first.status_code == 200 and first.json() == {
                "status": "accepted",
                "duplicate": False,
            }
            assert second.status_code == 200 and second.json() == {
                "status": "accepted",
                "duplicate": True,
            }
            assert bad.status_code == 401 and bad.json()["request_id"]
            assert first.headers["X-Request-ID"] == "hook-1"

        async with database.session_factory() as session:
            assert (
                await session.scalar(select(func.count(IncomingPlatformUpdateModel.id)))
                == 1
            )
            assert (
                await session.scalar(select(func.count(IngressOutboxEventModel.id)))
                == 1
            )
        await clear(database)
        await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.ingress_integration
@pytest.mark.demo_integration
def test_polling_uses_persisted_cursor_and_refuses_configured_webhook() -> None:
    class FakeAdapter:
        def __init__(self, webhook_url: str = "") -> None:
            self.webhook_url = webhook_url
            self.offset: str | None = None
            self.external_calls = 0

        async def get_webhook_info(self) -> WebhookInfo:
            self.external_calls += 1
            return WebhookInfo(
                url=self.webhook_url,
                pending_update_count=0,
                allowed_updates=(),
                max_connections=None,
                last_error_at=None,
                last_error_message=None,
                ip_address=None,
                has_custom_certificate=False,
            )

        async def get_updates(self, **kwargs: object) -> tuple[object, ...]:
            self.external_calls += 1
            self.offset = (
                kwargs["offset"] if isinstance(kwargs["offset"], str) else None
            )
            from app.infrastructure.telegram.updates import parse_telegram_update

            return (parse_telegram_update({"update_id": 9001, "message": {}}),)

    async def scenario() -> None:
        connection_id = uuid4()
        settings = Settings(
            _env_file=None,
            environment="test",
            telegram_enabled=True,
            telegram_bot_token="fake-token",
            telegram_delivery_mode="polling",
            telegram_platform_connection_id=connection_id,
        )
        database = Database(settings)
        await database.start()
        await clear(database)
        actual_connection_id = await seed_connection(database)
        configured = settings.model_copy(
            update={"telegram_platform_connection_id": actual_connection_id}
        )
        adapter = FakeAdapter()
        assert await poll_once(configured, database, adapter) == 1  # type: ignore[arg-type]
        repository = SqlAlchemyDurableIngressRepository(
            database.session_factory, configured.ingress_event_schema_version
        )
        assert adapter.offset is None
        assert await repository.polling_offset(actual_connection_id) == "9002"
        second_adapter = FakeAdapter()
        assert await poll_once(configured, database, second_adapter) == 1  # type: ignore[arg-type]
        assert second_adapter.offset == "9002"
        with pytest.raises(RuntimeError, match="refusing to poll"):
            await poll_once(
                configured, database, FakeAdapter("https://example.invalid")
            )  # type: ignore[arg-type]
        async with database.session_factory() as session, session.begin():
            tenant = await session.get(ControlTenantModel, LEGACY_TENANT_ID)
            assert tenant is not None
            tenant.status = TenantStatus.DISABLED
            tenant.revision += 1
        inactive_adapter = FakeAdapter()
        with pytest.raises(UnknownPlatformConnectionError):
            await poll_once(configured, database, inactive_adapter)  # type: ignore[arg-type]
        assert inactive_adapter.external_calls == 0
        async with database.session_factory() as session, session.begin():
            tenant = await session.get(ControlTenantModel, LEGACY_TENANT_ID)
            assert tenant is not None
            tenant.status = TenantStatus.ACTIVE
            tenant.revision += 1
        await clear(database)
        await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.ingress_integration
@pytest.mark.conversation_integration
@pytest.mark.planning_integration
def test_disabled_ambient_job_completes_without_provider_io(settings: Settings) -> None:
    class FakeProvider:
        provider_id = ProviderId.OLLAMA
        model = "fake-model"
        capabilities = None

        def __init__(self) -> None:
            self.calls = 0

        async def generate(self, _: object) -> object:
            self.calls += 1
            raise AssertionError("disabled ambient work must not reach the provider")

        async def aclose(self) -> None:
            return None

    async def scenario() -> None:
        database = Database(settings)
        queue = RedisIngressQueue(settings)
        await database.start()
        await clear(database, queue)
        connection_id = await seed_connection(database)
        repository = SqlAlchemyDurableIngressRepository(database.session_factory, 1)
        await repository.accept(envelope(connection_id, "5000000100"))
        assert await dispatch_once(settings, repository, queue) == 1
        processor = SqlAlchemyConversationProcessor(database.session_factory)
        assert (
            await consume_once(settings, database, queue, processor, "ambient-source")
            == 1
        )
        async with database.session_factory() as session:
            job = await session.scalar(select(ResponsePlanningJobModel))
            assert job is not None
            conversation = await session.get(ConversationModel, job.conversation_id)
            assert conversation is not None
            connection = await session.get(
                PlatformConnectionModel, conversation.platform_connection_id
            )
            assert connection is not None
            job.trigger = ParticipationTrigger.AMBIENT
            job.ambient_policy_version = "ambient-policy-v1"
            conversation_id = conversation.id
            assistant_id = connection.assistant_id
            await session.commit()
        await SqlAlchemyGroupConfigurationService(database.session_factory).apply(
            conversation_id,
            assistant_id,
            ConfigurationChange(response_mode=ResponseMode.AMBIENT_SELECTIVE),
            expected_revision=1,
        )
        configured = settings.model_copy(
            update={
                "telegram_enabled": True,
                "telegram_bot_token": "fake-token",
                "llm_enabled": True,
                "llm_primary_provider": "ollama",
                "llm_ollama_model": "fake-model",
                "ambient_selective_enabled": False,
            }
        )

        class FakePresence:
            def __init__(self) -> None:
                self.calls = 0

            async def send_chat_action(self, _: SendChatActionRequest) -> None:
                self.calls += 1

        fake = FakeProvider()
        presence = FakePresence()
        assert (
            await consume_planning_once(
                configured,
                database,
                "ambient-test",
                fake,
                presence_adapter=presence,
            )
            == 1
        )  # type: ignore[arg-type]
        assert fake.calls == 0
        assert presence.calls == 0
        async with database.session_factory() as session:
            job = await session.scalar(select(ResponsePlanningJobModel))
            plan = await session.scalar(select(ResponsePlanModel))
            assert job is not None and job.ambient_reason == "ambient_feature_disabled"
            assert plan is not None and plan.should_respond is False
            attempts = await session.scalar(
                select(func.count(ModelGenerationAttemptModel.id))
            )
            assert attempts == 0
        await clear(database, queue)
        await database.stop()

    asyncio.run(scenario())
