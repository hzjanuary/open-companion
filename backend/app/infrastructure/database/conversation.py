"""Transactional PostgreSQL business processing for normalized conversation events."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.conversation import (
    ConversationProcessResult,
    EligibilityInput,
    evaluate_eligibility,
)
from app.application.ingress import IngressQueueEvent
from app.domain.ambient import AMBIENT_POLICY_VERSION, ParticipationTrigger
from app.domain.conversation import (
    EligibilityDecision,
    EligibilityReason,
    NormalizedMembership,
    NormalizedMessage,
    ParticipantIdentity,
    ProcessingOutcome,
)
from app.domain.persistence import (
    ConversationStatus,
    MessageDirection,
    MessageProcessingStatus,
    MessageType,
    Platform,
)
from app.infrastructure.database.media import redact_media_values
from app.infrastructure.database.models import (
    AssistantModel,
    ControlTenantModel,
    ConversationModel,
    ConversationProcessingRecordModel,
    IncomingPlatformUpdateModel,
    MessageMediaModel,
    MessageModel,
    ParticipantModel,
    PlatformConnectionModel,
    ResponsePlanningJobModel,
    TelegramCommandJobModel,
)
from app.infrastructure.database.personality import ensure_conversation_configuration
from app.infrastructure.database.tenancy import connection_authority


class ConversationProcessingError(ValueError):
    """Permanent queue/database contract disagreement."""


class SqlAlchemyConversationProcessor:
    """Own one business transaction; callers acknowledge only after return."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        prompt_version: str = "spec-006-v1",
        response_schema_version: str = "response-plan-v1",
        stickers_enabled: bool = False,
    ) -> None:
        self._session_factory = session_factory
        self._prompt_version = prompt_version
        self._response_schema_version = response_schema_version
        self._stickers_enabled = stickers_enabled

    async def process(
        self,
        event: IngressQueueEvent,
        normalized: NormalizedMessage | NormalizedMembership,
    ) -> ConversationProcessResult:
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    return await self._process_in_transaction(
                        session, event, normalized
                    )
        except IntegrityError:
            return await self._duplicate_result(event.incoming_update_id)

    async def reject_malformed(
        self, event: IngressQueueEvent
    ) -> ConversationProcessResult:
        async with self._session_factory() as session:
            async with session.begin():
                existing = await session.scalar(
                    select(ConversationProcessingRecordModel).where(
                        ConversationProcessingRecordModel.incoming_update_id
                        == event.incoming_update_id
                    )
                )
                if existing is not None:
                    return self._record_result(existing, duplicate=True)
                await self._validate_ingress(session, event)
                record = ConversationProcessingRecordModel(
                    incoming_update_id=event.incoming_update_id,
                    outcome=ProcessingOutcome.REJECTED_MALFORMED,
                    permanent_error="malformed_durable_update",
                )
                session.add(record)
                await session.flush()
                return self._record_result(record, duplicate=False)

    async def ignore_not_allowed(
        self, event: IngressQueueEvent
    ) -> ConversationProcessResult:
        """Durably suppress demo traffic before it can create product state."""

        async with self._session_factory() as session:
            async with session.begin():
                existing = await session.scalar(
                    select(ConversationProcessingRecordModel).where(
                        ConversationProcessingRecordModel.incoming_update_id
                        == event.incoming_update_id
                    )
                )
                if existing is not None:
                    return self._record_result(existing, duplicate=True)
                incoming, _, _, _ = await self._validate_ingress(session, event)
                record = ConversationProcessingRecordModel(
                    incoming_update_id=incoming.id,
                    outcome=ProcessingOutcome.IGNORED,
                    permanent_error="conversation_not_allowed",
                )
                session.add(record)
                await session.flush()
                return self._record_result(record, duplicate=False)

    async def _process_in_transaction(
        self,
        session: AsyncSession,
        event: IngressQueueEvent,
        normalized: NormalizedMessage | NormalizedMembership,
    ) -> ConversationProcessResult:
        existing = await session.scalar(
            select(ConversationProcessingRecordModel).where(
                ConversationProcessingRecordModel.incoming_update_id
                == event.incoming_update_id
            )
        )
        if existing is not None:
            return self._record_result(existing, duplicate=True)
        incoming, tenant, connection, assistant = await self._validate_ingress(
            session, event
        )
        if normalized.conversation.platform_connection_id != connection.id:
            raise ConversationProcessingError("normalized connection mismatch")
        # PostgreSQL transaction advisory locks serialize a conversation/topic across
        # worker processes without surviving a crash or spanning provider I/O.
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
            {
                "identity": (
                    f"{connection.id}:"
                    f"{normalized.conversation.platform_conversation_id}"
                ),
            },
        )
        conversation = await self._upsert_conversation(session, normalized)
        configuration = await ensure_conversation_configuration(
            session, assistant, conversation, stickers_enabled=self._stickers_enabled
        )
        if isinstance(normalized, NormalizedMembership):
            participant = await self._upsert_participant(
                session,
                conversation,
                normalized.participant,
                normalized.occurred_at,
                True,
            )
            if normalized.is_assistant_membership:
                conversation.assistant_membership_status = (
                    normalized.participant.membership_status
                )
                conversation.assistant_membership_updated_at = normalized.occurred_at
            record = ConversationProcessingRecordModel(
                incoming_update_id=incoming.id,
                outcome=ProcessingOutcome.MEMBERSHIP_APPLIED,
                conversation_id=conversation.id,
            )
            session.add(record)
            await session.flush()
            return self._record_result(record, duplicate=False)
        participant = await self._upsert_participant(
            session, conversation, normalized.sender, normalized.sent_at, False
        )
        message, created = await self._upsert_message(
            session, conversation, participant, normalized
        )
        if normalized.command is not None and not normalized.is_edit:
            message.eligible = False
            message.eligibility_reason = EligibilityReason.COMMAND_HANDOFF
            conversation.last_platform_activity_at = normalized.sent_at
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
            session.add(
                TelegramCommandJobModel(
                    conversation_processing_record_id=record.id,
                    conversation_id=conversation.id,
                    message_id=message.id,
                    participant_id=participant.id,
                    command_name=normalized.command.name,
                    arguments=normalized.command.arguments,
                )
            )
            await session.flush()
            return ConversationProcessResult(
                incoming_update_id=incoming.id,
                duplicate=False,
                outcome=record.outcome.value,
                conversation_id=conversation.id,
                message_id=message.id,
                eligibility=EligibilityDecision(
                    False, EligibilityReason.COMMAND_HANDOFF
                ),
            )
        decision = evaluate_eligibility(
            EligibilityInput(
                tenant_status=tenant.status,
                assistant_status=assistant.status,
                connection_status=connection.status,
                conversation_status=conversation.status,
                conversation_type=conversation.conversation_type.value,
                response_mode=conversation.response_mode,
                assistant_platform_user_id=connection.external_bot_id,
                assistant_display_name=assistant.name,
                sender_platform_user_id=normalized.sender.platform_user_id,
                sender_is_bot=normalized.sender.is_bot,
                message_type=normalized.message_type,
                message_text=normalized.text,
                mentions_assistant=normalized.mentions_assistant,
                replies_to_assistant=normalized.replies_to_assistant,
                is_edit=normalized.is_edit,
                is_membership_event=False,
            )
        )
        message.eligible = decision.eligible
        message.eligibility_reason = decision.reason
        conversation.last_platform_activity_at = normalized.sent_at
        record = ConversationProcessingRecordModel(
            incoming_update_id=incoming.id,
            outcome=(
                ProcessingOutcome.MESSAGE_EDITED
                if normalized.is_edit and not created
                else ProcessingOutcome.MESSAGE_CREATED
            ),
            conversation_id=conversation.id,
            message_id=message.id,
            eligible=decision.eligible,
            eligibility_reason=decision.reason,
        )
        session.add(record)
        await session.flush()
        if decision.eligible and (
            created
            or normalized.message_type
            not in {"photo", "voice", "audio", "unsupported_media"}
        ):
            if (
                conversation.status == ConversationStatus.PAUSED
                or configuration.response_mode.value == "paused"
            ):
                return ConversationProcessResult(
                    incoming_update_id=incoming.id,
                    duplicate=False,
                    outcome=record.outcome.value,
                    conversation_id=conversation.id,
                    message_id=message.id,
                    eligibility=decision,
                )
            session.add(
                ResponsePlanningJobModel(
                    conversation_processing_record_id=record.id,
                    conversation_id=conversation.id,
                    message_id=message.id,
                    prompt_version=self._prompt_version,
                    response_schema_version=self._response_schema_version,
                    personality_profile_version_id=configuration.personality_profile_version_id,
                    configuration_revision_id=configuration.id,
                    trigger=decision.trigger or ParticipationTrigger.ADDRESSED,
                    ambient_policy_version=(
                        AMBIENT_POLICY_VERSION
                        if decision.trigger == ParticipationTrigger.AMBIENT
                        else None
                    ),
                )
            )
            await session.flush()
        return ConversationProcessResult(
            incoming_update_id=incoming.id,
            duplicate=False,
            outcome=record.outcome.value,
            conversation_id=conversation.id,
            message_id=message.id,
            eligibility=decision,
        )

    async def _validate_ingress(
        self, session: AsyncSession, event: IngressQueueEvent
    ) -> tuple[
        IncomingPlatformUpdateModel,
        ControlTenantModel,
        PlatformConnectionModel,
        AssistantModel,
    ]:
        incoming = await session.get(
            IncomingPlatformUpdateModel, event.incoming_update_id
        )
        if incoming is None:
            raise ConversationProcessingError("incoming update is missing")
        if (
            incoming.platform != event.platform
            or incoming.platform_connection_id != event.platform_connection_id
            or incoming.platform_update_id != event.platform_update_id
            or incoming.update_type != event.update_type
            or incoming.received_at != event.received_at
        ):
            raise ConversationProcessingError(
                "queue metadata does not match durable ingress"
            )
        if incoming.platform != Platform.TELEGRAM:
            raise ConversationProcessingError("unsupported ingress platform")
        authority = await connection_authority(session, incoming.platform_connection_id)
        if authority is None or authority.connection.platform != Platform.TELEGRAM:
            raise ConversationProcessingError("platform connection is unavailable")
        return (
            incoming,
            authority.tenant,
            authority.connection,
            authority.assistant,
        )

    async def _upsert_conversation(
        self,
        session: AsyncSession,
        normalized: NormalizedMessage | NormalizedMembership,
    ) -> ConversationModel:
        identity = normalized.conversation
        conversation = await session.scalar(
            select(ConversationModel).where(
                ConversationModel.platform_connection_id
                == identity.platform_connection_id,
                ConversationModel.platform_conversation_id
                == identity.platform_conversation_id,
            )
        )
        if conversation is None:
            conversation = ConversationModel(
                platform_connection_id=identity.platform_connection_id,
                platform_conversation_id=identity.platform_conversation_id,
                conversation_type=identity.conversation_type,
                title=identity.title,
                status=ConversationStatus.ACTIVE,
            )
            session.add(conversation)
            await session.flush()
        else:
            conversation.conversation_type = identity.conversation_type
            if identity.title is not None:
                conversation.title = identity.title
        return conversation

    async def _upsert_participant(
        self,
        session: AsyncSession,
        conversation: ConversationModel,
        identity: ParticipantIdentity,
        observed_at: datetime,
        membership_update: bool,
    ) -> ParticipantModel:
        participant = await session.scalar(
            select(ParticipantModel).where(
                ParticipantModel.conversation_id == conversation.id,
                ParticipantModel.platform_user_id == identity.platform_user_id,
            )
        )
        if participant is None:
            participant = ParticipantModel(
                conversation_id=conversation.id,
                platform_user_id=identity.platform_user_id,
                username=identity.username,
                display_name=identity.display_name,
                role=identity.role,
                membership_status=identity.membership_status,
                is_bot=identity.is_bot,
                last_seen_at=observed_at,
                last_membership_updated_at=observed_at if membership_update else None,
            )
            session.add(participant)
            await session.flush()
            return participant
        if participant.privacy_deleted_at is None:
            participant.username = identity.username
            participant.display_name = identity.display_name
        participant.is_bot = identity.is_bot
        participant.last_seen_at = observed_at
        if membership_update:
            participant.membership_status = identity.membership_status
            participant.role = identity.role
            participant.last_membership_updated_at = observed_at
        return participant

    async def _upsert_message(
        self,
        session: AsyncSession,
        conversation: ConversationModel,
        participant: ParticipantModel,
        normalized: NormalizedMessage,
    ) -> tuple[MessageModel, bool]:
        message = await session.scalar(
            select(MessageModel).where(
                MessageModel.conversation_id == conversation.id,
                MessageModel.platform_message_id == normalized.platform_message_id,
            )
        )
        reply_to_id = (
            await session.scalar(
                select(MessageModel.id).where(
                    MessageModel.conversation_id == conversation.id,
                    MessageModel.platform_message_id
                    == normalized.reply_to_platform_message_id,
                )
            )
            if normalized.reply_to_platform_message_id is not None
            else None
        )
        message_type = {
            "text": MessageType.TEXT,
            "sticker": MessageType.STICKER,
            "photo": MessageType.PHOTO,
            "voice": MessageType.VOICE,
            "audio": MessageType.AUDIO,
        }.get(normalized.message_type, MessageType.OTHER)
        metadata: dict[str, object] = {
            "mentions": [
                ref.platform_user_id or ref.username for ref in normalized.mentions[:20]
            ]
        }
        is_media = normalized.message_type in {
            "photo",
            "voice",
            "audio",
            "unsupported_media",
        }
        if is_media:
            metadata["content_provenance"] = "media_caption"
            metadata["media_kind"] = normalized.message_type
            if normalized.media_failure is not None:
                metadata["media_failure"] = normalized.media_failure.value
        if message is None:
            message = MessageModel(
                conversation_id=conversation.id,
                participant_id=participant.id,
                platform_message_id=normalized.platform_message_id,
                direction=MessageDirection.INCOMING,
                message_type=message_type,
                text=normalized.text,
                reply_to_message_id=reply_to_id,
                reply_to_platform_message_id=normalized.reply_to_platform_message_id,
                metadata_=metadata,
                processing_status=MessageProcessingStatus.PROCESSED,
                platform_sent_at=normalized.sent_at,
                platform_thread_id=normalized.platform_thread_id,
                edited_at=normalized.edited_at,
                mentions_assistant=normalized.mentions_assistant,
                replies_to_assistant=normalized.replies_to_assistant,
            )
            session.add(message)
            if is_media and participant.privacy_deleted_at is not None:
                message.text = None
                message.metadata_ = {}
                message.content_redacted_at = datetime.now(UTC)
            await session.flush()
            if (
                normalized.attachment is not None
                and participant.privacy_deleted_at is None
            ):
                attachment = normalized.attachment
                session.add(
                    MessageMediaModel(
                        message_id=message.id,
                        conversation_id=conversation.id,
                        kind=attachment.kind,
                        file_id=attachment.file_id,
                        file_unique_id=attachment.file_unique_id,
                        mime_type=attachment.mime_type,
                        file_size=attachment.file_size,
                        width=attachment.width,
                        height=attachment.height,
                        duration_seconds=attachment.duration_seconds,
                        caption=normalized.text,
                    )
                )
                await session.flush()
            return message, True
        if normalized.is_edit:
            await session.execute(
                update(MessageMediaModel)
                .where(MessageMediaModel.message_id == message.id)
                .values(**redact_media_values(datetime.now(UTC)))
            )
            message.participant_id = participant.id
            message.message_type = message_type
            message.text = normalized.text
            message.metadata_ = metadata
            message.platform_sent_at = normalized.sent_at
            message.platform_thread_id = normalized.platform_thread_id
            message.edited_at = normalized.edited_at or datetime.now(UTC)
            message.mentions_assistant = normalized.mentions_assistant
            message.replies_to_assistant = normalized.replies_to_assistant
            message.reply_to_message_id = reply_to_id
            message.reply_to_platform_message_id = (
                normalized.reply_to_platform_message_id
            )
        return message, False

    async def _duplicate_result(
        self, incoming_update_id: UUID
    ) -> ConversationProcessResult:
        async with self._session_factory() as session:
            record = await session.scalar(
                select(ConversationProcessingRecordModel).where(
                    ConversationProcessingRecordModel.incoming_update_id
                    == incoming_update_id
                )
            )
            if record is None:
                raise ConversationProcessingError(
                    "conversation processing record was not created"
                )
            return self._record_result(record, duplicate=True)

    def _record_result(
        self, record: ConversationProcessingRecordModel, *, duplicate: bool
    ) -> ConversationProcessResult:
        eligibility = (
            EligibilityDecision(record.eligible, record.eligibility_reason)
            if record.eligible is not None and record.eligibility_reason is not None
            else None
        )
        return ConversationProcessResult(
            incoming_update_id=record.incoming_update_id,
            duplicate=duplicate,
            outcome=record.outcome.value,
            conversation_id=record.conversation_id,
            message_id=record.message_id,
            eligibility=eligibility,
        )
