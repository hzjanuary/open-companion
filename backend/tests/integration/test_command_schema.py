import asyncio
from datetime import UTC, datetime
from functools import partial
from uuid import UUID

import pytest
from sqlalchemy import func, select, text

from app.application.ingress import IngressEnvelope
from app.application.personality import default_personality
from app.application.ports.platform import (
    ChatMember,
    PlatformAdapterError,
    PlatformCapability,
    PlatformErrorCategory,
    SentMessage,
)
from app.core.config import Settings
from app.domain.conversation import EligibilityReason, ProcessingOutcome
from app.domain.persistence import (
    AssistantStatus,
    ConversationType,
    IngressSource,
    MessageDirection,
    MessageType,
    Platform,
    PlatformConnectionStatus,
    ResponseMode,
)
from app.domain.tenancy import LEGACY_TENANT_ID
from app.infrastructure.database.conversation import SqlAlchemyConversationProcessor
from app.infrastructure.database.database import Database
from app.infrastructure.database.group_configuration import (
    ConfigurationChange,
    SqlAlchemyGroupConfigurationService,
)
from app.infrastructure.database.ingress import SqlAlchemyDurableIngressRepository
from app.infrastructure.database.models import (
    AssistantModel as DatabaseAssistantModel,
)
from app.infrastructure.database.models import (
    ConversationConfigurationRevisionModel,
    ConversationModel,
    ConversationProcessingRecordModel,
    IncomingPlatformUpdateModel,
    IngressOutboxEventModel,
    MessageModel,
    ParticipantModel,
    ParticipantPreferenceEventModel,
    ResponsePlanModel,
    ResponsePlanningJobModel,
    TelegramCommandJobModel,
)
from app.infrastructure.database.models import (
    PlatformConnectionModel as DatabasePlatformConnectionModel,
)
from app.infrastructure.database.personality import (
    create_profile,
    create_profile_version,
    ensure_conversation_configuration,
)
from app.infrastructure.telegram.normalizer import normalize_telegram_update
from app.infrastructure.telegram.updates import parse_telegram_update
from app.runtime.outbound_delivery_worker import consume_once as consume_delivery_once
from app.runtime.telegram_command_worker import _resolve_profile_version
from app.runtime.telegram_command_worker import consume_once as consume_command_once

AssistantModel = partial(
    DatabaseAssistantModel,
    tenant_id=LEGACY_TENANT_ID,
    slug="command-january",
    status=AssistantStatus.ACTIVE,
)
PlatformConnectionModel = partial(
    DatabasePlatformConnectionModel,
    tenant_id=LEGACY_TENANT_ID,
)


@pytest.mark.integration
@pytest.mark.command_integration
def test_command_schema_is_current_and_enforces_response_plan_source_xor() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            async with database.engine.connect() as connection:
                assert (
                    await connection.scalar(
                        text("SELECT version_num FROM alembic_version")
                    )
                    == "0026_conversation_feedback"
                )
                constraints = await connection.scalars(
                    text(
                        "SELECT conname FROM pg_constraint "
                        "WHERE conname = "
                        "'ck_response_plans_response_plan_exactly_one_source'"
                    )
                )
                assert list(constraints) == [
                    "ck_response_plans_response_plan_exactly_one_source"
                ]
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.command_integration
def test_recognized_command_handoffs_without_model_planning_work() -> None:
    async def scenario() -> None:
        settings = Settings(_env_file=None, environment="test")
        database = Database(settings)
        await database.start()
        try:
            async with database.session_factory() as session:
                async with session.begin():
                    await session.execute(text("TRUNCATE assistants CASCADE"))
                    assistant = AssistantModel(name="January")
                    session.add(assistant)
                    await session.flush()
                    connection = PlatformConnectionModel(
                        assistant_id=assistant.id,
                        platform=Platform.TELEGRAM,
                        external_bot_id="commands-bot",
                        status=PlatformConnectionStatus.ACTIVE,
                    )
                    session.add(connection)
                    await session.flush()
                    connection_id = connection.id
            payload: dict[str, object] = {
                "update_id": 99,
                "message": {
                    "message_id": 8,
                    "date": 1_700_000_000,
                    "chat": {"id": 7, "type": "private"},
                    "from": {"id": 9, "is_bot": False, "first_name": "Member"},
                    "text": "/status",
                    "entities": [{"type": "bot_command", "offset": 0, "length": 7}],
                },
            }
            ingress = SqlAlchemyDurableIngressRepository(database.session_factory, 1)
            accepted = await ingress.accept(
                IngressEnvelope(
                    platform=Platform.TELEGRAM,
                    platform_connection_id=connection_id,
                    platform_update_id="99",
                    update_type="message",
                    supported=True,
                    ingress_source=IngressSource.WEBHOOK,
                    received_at=datetime.now(UTC),
                    raw_payload=payload,
                )
            )
            async with database.session_factory() as session:
                event_id = await session.scalar(
                    select(IngressOutboxEventModel.id).where(
                        IngressOutboxEventModel.incoming_update_id
                        == accepted.incoming_update_id
                    )
                )
            assert event_id is not None
            event = await ingress.event_for(event_id)
            assert event is not None
            normalized = normalize_telegram_update(
                parse_telegram_update(payload),
                platform_connection_id=connection_id,
                assistant_platform_user_id="commands-bot",
                assistant_display_name="January",
                assistant_username=None,
            )
            result = await SqlAlchemyConversationProcessor(
                database.session_factory
            ).process(event, normalized)
            assert result.eligibility is not None
            assert result.eligibility.reason == EligibilityReason.COMMAND_HANDOFF
            async with database.session_factory() as session:
                assert (
                    await session.scalar(select(func.count(TelegramCommandJobModel.id)))
                    == 1
                )
                assert (
                    await session.scalar(
                        select(func.count(ResponsePlanningJobModel.id))
                    )
                    == 0
                )
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.command_integration
@pytest.mark.parametrize(
    "authorization_case",
    [
        "administrator",
        "member",
        "retry",
        "already_paused",
        "conflict",
        "private",
        "resume",
        "resume_noop",
    ],
)
def test_command_configuration_completion_creates_one_revision_plan_and_action(
    authorization_case: str,
) -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            async with database.session_factory() as session:
                async with session.begin():
                    await session.execute(text("TRUNCATE assistants CASCADE"))
                    assistant = AssistantModel(name="January")
                    session.add(assistant)
                    await session.flush()
                    connection = PlatformConnectionModel(
                        assistant_id=assistant.id,
                        platform=Platform.TELEGRAM,
                        external_bot_id="commands-bot",
                        status=PlatformConnectionStatus.ACTIVE,
                    )
                    session.add(connection)
                    await session.flush()
                    conversation = ConversationModel(
                        platform_connection_id=connection.id,
                        platform_conversation_id="123",
                        conversation_type=(
                            ConversationType.PRIVATE
                            if authorization_case == "private"
                            else ConversationType.GROUP
                        ),
                    )
                    session.add(conversation)
                    await session.flush()
                    await ensure_conversation_configuration(
                        session, assistant, conversation
                    )
                    participant = ParticipantModel(
                        conversation_id=conversation.id,
                        platform_user_id="user-1",
                        display_name="User",
                    )
                    session.add(participant)
                    await session.flush()
                    message = MessageModel(
                        conversation_id=conversation.id,
                        participant_id=participant.id,
                        platform_message_id="1",
                        direction=MessageDirection.INCOMING,
                        message_type=MessageType.TEXT,
                        text=(
                            "/resume"
                            if authorization_case in {"resume", "resume_noop"}
                            else "/quiet"
                        ),
                    )
                    incoming = IncomingPlatformUpdateModel(
                        platform_connection_id=connection.id,
                        platform=Platform.TELEGRAM,
                        platform_update_id="1",
                        update_type="message",
                        ingress_source=IngressSource.POLLING,
                        raw_payload={},
                        received_at=datetime.now(UTC),
                    )
                    session.add_all([message, incoming])
                    await session.flush()
                    record = ConversationProcessingRecordModel(
                        incoming_update_id=incoming.id,
                        outcome=ProcessingOutcome.MESSAGE_CREATED,
                        conversation_id=conversation.id,
                        message_id=message.id,
                        eligible=False,
                        eligibility_reason=EligibilityReason.COMMAND_HANDOFF,
                    )
                    session.add(record)
                    await session.flush()
                    job = TelegramCommandJobModel(
                        conversation_processing_record_id=record.id,
                        conversation_id=conversation.id,
                        message_id=message.id,
                        participant_id=participant.id,
                        command_name=(
                            "resume"
                            if authorization_case in {"resume", "resume_noop"}
                            else "quiet"
                        ),
                    )
                    session.add(job)
                    await session.flush()
                    job_id, internal_conversation_id, connection_id = (
                        job.id,
                        conversation.id,
                        connection.id,
                    )

            if authorization_case in {"already_paused", "resume"}:
                await SqlAlchemyGroupConfigurationService(
                    database.session_factory
                ).apply(
                    internal_conversation_id,
                    assistant.id,
                    ConfigurationChange(response_mode=ResponseMode.PAUSED),
                    expected_revision=1,
                )

            class AllowedAdministrator:
                calls = 0

                async def get_chat_member(
                    self, conversation_id: str, user_id: str
                ) -> ChatMember:
                    self.calls += 1
                    if authorization_case == "retry" and self.calls == 1:
                        raise PlatformAdapterError(
                            PlatformErrorCategory.TIMEOUT,
                            "getChatMember",
                            retryable=True,
                        )
                    if authorization_case == "conflict":
                        await SqlAlchemyGroupConfigurationService(
                            database.session_factory
                        ).apply(
                            internal_conversation_id,
                            assistant.id,
                            ConfigurationChange(
                                response_mode=ResponseMode.MENTION_AND_NAME
                            ),
                            expected_revision=1,
                        )
                    return ChatMember(
                        conversation_id=conversation_id,
                        user_id=user_id,
                        status="administrator",
                        is_administrator=authorization_case != "member",
                        is_owner=False,
                        permissions=frozenset(),
                    )

            adapter = AllowedAdministrator()
            expected_mode = {
                "administrator": ResponseMode.PAUSED,
                "member": ResponseMode.MENTION_ONLY,
                "retry": ResponseMode.PAUSED,
                "already_paused": ResponseMode.PAUSED,
                "conflict": ResponseMode.MENTION_AND_NAME,
                "private": ResponseMode.PAUSED,
                "resume": ResponseMode.MENTION_ONLY,
                "resume_noop": ResponseMode.MENTION_ONLY,
            }[authorization_case]
            expected_result = {
                "administrator": "success",
                "member": "denied",
                "retry": "success",
                "already_paused": "unchanged",
                "conflict": "conflict",
                "private": "success",
                "resume": "success",
                "resume_noop": "unchanged",
            }[authorization_case]
            expected_revisions = {
                "administrator": 2,
                "member": 1,
                "retry": 2,
                "already_paused": 2,
                "conflict": 2,
                "private": 2,
                "resume": 3,
                "resume_noop": 1,
            }[authorization_case]
            settings = Settings(
                _env_file=None,
                environment="test",
                command_worker_enabled=True,
                telegram_enabled=True,
                telegram_bot_token="fake-token",
                telegram_platform_connection_id=connection_id,
                outbound_delivery_enabled=True,
            )
            assert await consume_command_once(settings, database, adapter, "test") == 1
            assert adapter.calls == (0 if authorization_case == "private" else 1)
            if authorization_case == "retry":
                async with database.session_factory() as session:
                    async with session.begin():
                        retrying = await session.get(TelegramCommandJobModel, job_id)
                        assert retrying is not None and retrying.result_code is None
                        assert (
                            list(await session.scalars(select(ResponsePlanModel))) == []
                        )
                        retrying.available_at = datetime.now(UTC)
                assert (
                    await consume_command_once(settings, database, adapter, "test") == 1
                )
                assert adapter.calls == 2
            assert await consume_command_once(settings, database, adapter, "test") == 0
            assert adapter.calls == (
                2
                if authorization_case == "retry"
                else 0
                if authorization_case == "private"
                else 1
            )
            async with database.session_factory() as session:
                conversation = await session.get(
                    ConversationModel, internal_conversation_id
                )
                assert conversation is not None
                assert conversation.response_mode == expected_mode
                plans = list(await session.scalars(select(ResponsePlanModel)))
                assert len(plans) == 1 and plans[0].command_job_id == job_id
                result = await session.get(TelegramCommandJobModel, job_id)
                assert result is not None
                assert result.result_code == expected_result
                assert (
                    await session.scalar(
                        select(func.count(ConversationConfigurationRevisionModel.id))
                    )
                    == expected_revisions
                )

            class FakeDeliveryAdapter:
                requests: list[object] = []

                @property
                def capabilities(self) -> frozenset[PlatformCapability]:
                    return frozenset({PlatformCapability.SEND_TEXT})

                async def send_text(self, request: object) -> SentMessage:
                    self.requests.append(request)
                    return SentMessage(
                        Platform.TELEGRAM,
                        "command-delivery",
                        "123",
                        "commands-bot",
                        None,
                        datetime.now(UTC),
                    )

                async def send_sticker(self, request: object) -> SentMessage:
                    raise AssertionError("command responses do not send stickers")

            delivery = FakeDeliveryAdapter()
            assert await consume_delivery_once(settings, database, delivery) == 1  # type: ignore[arg-type]
            assert len(delivery.requests) == 1
            assert await consume_delivery_once(settings, database, delivery) == 0  # type: ignore[arg-type]
            assert len(delivery.requests) == 1
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.command_integration
@pytest.mark.parametrize("initially_allowed", [True, False])
def test_private_preference_command_skips_authorization_and_updates_only_sender(
    initially_allowed: bool,
) -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            async with database.session_factory() as session:
                async with session.begin():
                    await session.execute(text("TRUNCATE assistants CASCADE"))
                    assistant = AssistantModel(name="January")
                    session.add(assistant)
                    await session.flush()
                    connection = PlatformConnectionModel(
                        assistant_id=assistant.id,
                        platform=Platform.TELEGRAM,
                        external_bot_id="commands-bot",
                        status=PlatformConnectionStatus.ACTIVE,
                    )
                    session.add(connection)
                    await session.flush()
                    conversation = ConversationModel(
                        platform_connection_id=connection.id,
                        platform_conversation_id="321",
                        conversation_type=ConversationType.PRIVATE,
                    )
                    session.add(conversation)
                    await session.flush()
                    await ensure_conversation_configuration(
                        session, assistant, conversation
                    )
                    sender = ParticipantModel(
                        conversation_id=conversation.id,
                        platform_user_id="sender",
                        display_name="Sender",
                        mention_allowed=initially_allowed,
                    )
                    other = ParticipantModel(
                        conversation_id=conversation.id,
                        platform_user_id="other",
                        display_name="Other",
                    )
                    session.add_all([sender, other])
                    await session.flush()
                    message = MessageModel(
                        conversation_id=conversation.id,
                        participant_id=sender.id,
                        platform_message_id="2",
                        direction=MessageDirection.INCOMING,
                        message_type=MessageType.TEXT,
                        text="/mentions off",
                    )
                    incoming = IncomingPlatformUpdateModel(
                        platform_connection_id=connection.id,
                        platform=Platform.TELEGRAM,
                        platform_update_id="2",
                        update_type="message",
                        ingress_source=IngressSource.POLLING,
                        raw_payload={},
                        received_at=datetime.now(UTC),
                    )
                    session.add_all([message, incoming])
                    await session.flush()
                    record = ConversationProcessingRecordModel(
                        incoming_update_id=incoming.id,
                        outcome=ProcessingOutcome.MESSAGE_CREATED,
                        conversation_id=conversation.id,
                        message_id=message.id,
                        eligible=False,
                        eligibility_reason=EligibilityReason.COMMAND_HANDOFF,
                    )
                    session.add(record)
                    await session.flush()
                    job = TelegramCommandJobModel(
                        conversation_processing_record_id=record.id,
                        conversation_id=conversation.id,
                        message_id=message.id,
                        participant_id=sender.id,
                        command_name="mentions",
                        arguments="off",
                    )
                    session.add(job)
                    await session.flush()
                    sender_id, other_id = sender.id, other.id

            class ForbiddenAuthorizationCall:
                calls = 0

                async def get_chat_member(self, *_: str) -> ChatMember:
                    self.calls += 1
                    raise AssertionError(
                        "private preference must not authorize remotely"
                    )

            adapter = ForbiddenAuthorizationCall()
            settings = Settings(
                _env_file=None, environment="test", command_worker_enabled=True
            )
            assert await consume_command_once(settings, database, adapter, "test") == 1
            assert adapter.calls == 0
            async with database.session_factory() as session:
                sender_now = await session.get(ParticipantModel, sender_id)
                other_now = await session.get(ParticipantModel, other_id)
                assert sender_now is not None and sender_now.mention_allowed is False
                assert other_now is not None and other_now.mention_allowed is True
                events = list(
                    await session.scalars(select(ParticipantPreferenceEventModel))
                )
                assert len(events) == (1 if initially_allowed else 0)
                job = await session.scalar(select(TelegramCommandJobModel))
                assert job is not None
                assert job.result_code == (
                    "success" if initially_allowed else "unchanged"
                )
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.command_integration
def test_personality_command_profile_resolution_is_assistant_scoped() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            async with database.session_factory() as session:
                async with session.begin():
                    await session.execute(text("TRUNCATE assistants CASCADE"))
                    assistant = AssistantModel(name="January")
                    other_assistant = AssistantModel(
                        slug="command-other", name="Other January"
                    )
                    session.add_all([assistant, other_assistant])
                    await session.flush()
                    connection = PlatformConnectionModel(
                        assistant_id=assistant.id,
                        platform=Platform.TELEGRAM,
                        external_bot_id="profiles-bot",
                        status=PlatformConnectionStatus.ACTIVE,
                    )
                    session.add(connection)
                    await session.flush()
                    conversation = ConversationModel(
                        platform_connection_id=connection.id,
                        platform_conversation_id="profiles",
                        conversation_type=ConversationType.GROUP,
                    )
                    session.add(conversation)
                    await session.flush()
                    await ensure_conversation_configuration(
                        session, assistant, conversation
                    )
                    lively = await create_profile(
                        session, assistant, slug="lively", display_name="Lively"
                    )
                    first = await create_profile_version(
                        session,
                        lively,
                        default_personality(),
                        source="test",
                    )
                    second = await create_profile_version(
                        session,
                        lively,
                        default_personality().model_copy(
                            update={"primary_language": "en"}
                        ),
                        source="test",
                    )
                    foreign = await create_profile(
                        session,
                        other_assistant,
                        slug="foreign",
                        display_name="Foreign",
                    )
                    await create_profile_version(
                        session,
                        foreign,
                        default_personality(),
                        source="test",
                    )
                    scoped = await create_profile(
                        session, assistant, slug="scoped", display_name="Scoped"
                    )
                    scoped.conversation_id = conversation.id
                    await create_profile_version(
                        session,
                        scoped,
                        default_personality(),
                        source="test",
                    )
                    assistant_id = assistant.id

            latest, latest_code = await _resolve_profile_version(
                database, assistant_id, "lively"
            )
            exact, exact_code = await _resolve_profile_version(
                database, assistant_id, "lively@1"
            )
            foreign_value, foreign_code = await _resolve_profile_version(
                database, assistant_id, "foreign"
            )
            scoped_value, scoped_code = await _resolve_profile_version(
                database, assistant_id, "scoped"
            )
            missing_value, missing_code = await _resolve_profile_version(
                database, assistant_id, "missing"
            )
            assert (latest, latest_code) == (second.id, "success")
            assert (exact, exact_code) == (first.id, "success")
            assert (foreign_value, foreign_code) == (None, "profile_not_owned")
            assert (scoped_value, scoped_code) == (None, "profile_not_owned")
            assert (missing_value, missing_code) == (None, "profile_not_found")
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.command_integration
def test_profile_and_sticker_commands_mutate_once_and_report_noops() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            async with database.session_factory() as session:
                async with session.begin():
                    await session.execute(text("TRUNCATE assistants CASCADE"))
                    assistant = AssistantModel(name="January")
                    session.add(assistant)
                    await session.flush()
                    connection = PlatformConnectionModel(
                        assistant_id=assistant.id,
                        platform=Platform.TELEGRAM,
                        external_bot_id="command-options-bot",
                        status=PlatformConnectionStatus.ACTIVE,
                    )
                    session.add(connection)
                    await session.flush()
                    conversation = ConversationModel(
                        platform_connection_id=connection.id,
                        platform_conversation_id="options-chat",
                        conversation_type=ConversationType.GROUP,
                    )
                    session.add(conversation)
                    await session.flush()
                    await ensure_conversation_configuration(
                        session, assistant, conversation
                    )
                    participant = ParticipantModel(
                        conversation_id=conversation.id,
                        platform_user_id="options-user",
                        display_name="Options",
                    )
                    session.add(participant)
                    profile = await create_profile(
                        session, assistant, slug="lively", display_name="Lively"
                    )
                    profile_version = await create_profile_version(
                        session,
                        profile,
                        default_personality().model_copy(
                            update={"primary_language": "en"}
                        ),
                        source="test",
                    )
                    connection_id = connection.id
                    conversation_id = conversation.id
                    participant_id = participant.id

            async def enqueue(name: str, arguments: str, sequence: int) -> UUID:
                async with database.session_factory() as session:
                    async with session.begin():
                        message = MessageModel(
                            conversation_id=conversation_id,
                            participant_id=participant_id,
                            platform_message_id=str(sequence),
                            direction=MessageDirection.INCOMING,
                            message_type=MessageType.TEXT,
                            text=f"/{name} {arguments}".strip(),
                        )
                        incoming = IncomingPlatformUpdateModel(
                            platform_connection_id=connection_id,
                            platform=Platform.TELEGRAM,
                            platform_update_id=f"options-{sequence}",
                            update_type="message",
                            ingress_source=IngressSource.POLLING,
                            raw_payload={},
                            received_at=datetime.now(UTC),
                        )
                        session.add_all([message, incoming])
                        await session.flush()
                        record = ConversationProcessingRecordModel(
                            incoming_update_id=incoming.id,
                            outcome=ProcessingOutcome.MESSAGE_CREATED,
                            conversation_id=conversation_id,
                            message_id=message.id,
                            eligible=False,
                            eligibility_reason=EligibilityReason.COMMAND_HANDOFF,
                        )
                        session.add(record)
                        await session.flush()
                        job = TelegramCommandJobModel(
                            conversation_processing_record_id=record.id,
                            conversation_id=conversation_id,
                            message_id=message.id,
                            participant_id=participant_id,
                            command_name=name,
                            arguments=arguments,
                        )
                        session.add(job)
                        await session.flush()
                        return job.id

            class Administrator:
                async def get_chat_member(
                    self, conversation_id: str, user_id: str
                ) -> ChatMember:
                    return ChatMember(
                        conversation_id=conversation_id,
                        user_id=user_id,
                        status="administrator",
                        is_administrator=True,
                        is_owner=False,
                        permissions=frozenset(),
                    )

            adapter = Administrator()
            settings = Settings(
                _env_file=None,
                environment="test",
                command_worker_enabled=True,
                command_batch_size=1,
                telegram_sticker_mapping={"celebrate": "fake-sticker"},
            )
            jobs = [
                await enqueue("personality", "use lively", 1),
                await enqueue("personality", "use lively", 2),
                await enqueue("stickers", "on", 3),
                await enqueue("stickers", "on", 4),
                await enqueue("stickers", "off", 5),
            ]
            for _ in jobs:
                assert (
                    await consume_command_once(settings, database, adapter, "test") == 1
                )
            unavailable = await enqueue("stickers", "on", 6)
            no_mapping = Settings(
                _env_file=None, environment="test", command_worker_enabled=True
            )
            assert (
                await consume_command_once(no_mapping, database, adapter, "test") == 1
            )
            profile_list = await enqueue("personality", "list", 7)
            assert (
                await consume_command_once(no_mapping, database, adapter, "test") == 1
            )
            async with database.session_factory() as session:
                conversation = await session.get(ConversationModel, conversation_id)
                assert conversation is not None
                revision = await session.get(
                    ConversationConfigurationRevisionModel,
                    conversation.current_configuration_revision_id,
                )
                assert revision is not None
                assert revision.personality_profile_version_id == profile_version.id
                assert revision.stickers_enabled is False
                assert (
                    await session.scalar(
                        select(func.count(ConversationConfigurationRevisionModel.id))
                    )
                    == 4
                )
                codes = list(
                    await session.scalars(
                        select(TelegramCommandJobModel.result_code).order_by(
                            TelegramCommandJobModel.created_at
                        )
                    )
                )
                assert codes == [
                    "success",
                    "unchanged",
                    "success",
                    "unchanged",
                    "success",
                    "sticker_mapping_unavailable",
                    "status",
                ]
                plans = list(await session.scalars(select(ResponsePlanModel)))
                assert len(plans) == 7
                assert {plan.command_job_id for plan in plans} == {
                    *jobs,
                    unavailable,
                    profile_list,
                }
                listed = next(
                    plan for plan in plans if plan.command_job_id == profile_list
                )
                assert listed.text is not None and "lively" in listed.text
        finally:
            await database.stop()

    asyncio.run(scenario())
