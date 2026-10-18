"""Small SQLAlchemy repository implementations for SPEC-002 lookups."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.persistence import (
    AssistantRecord,
    AssistantStatus,
    ConversationRecord,
    MessageRecord,
    ParticipantRecord,
    Platform,
    PlatformConnectionRecord,
)
from app.infrastructure.database.models import (
    AssistantModel,
    ConversationModel,
    MessageModel,
    ParticipantModel,
    PlatformConnectionModel,
)


def assistant_record(model: AssistantModel) -> AssistantRecord:
    return AssistantRecord(
        id=model.id,
        tenant_id=model.tenant_id,
        slug=model.slug,
        name=model.name,
        status=model.status,
        revision=model.revision,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def connection_record(model: PlatformConnectionModel) -> PlatformConnectionRecord:
    return PlatformConnectionRecord(
        id=model.id,
        tenant_id=model.tenant_id,
        assistant_id=model.assistant_id,
        platform=model.platform,
        external_bot_id=model.external_bot_id,
        status=model.status,
        credential_reference=model.credential_reference,
        configuration=model.configuration,
        revision=model.revision,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def conversation_record(model: ConversationModel) -> ConversationRecord:
    return ConversationRecord(
        id=model.id,
        platform_connection_id=model.platform_connection_id,
        platform_conversation_id=model.platform_conversation_id,
        conversation_type=model.conversation_type,
        title=model.title,
        status=model.status,
        response_mode=model.response_mode,
        settings=model.settings,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def participant_record(model: ParticipantModel) -> ParticipantRecord:
    return ParticipantRecord(
        id=model.id,
        conversation_id=model.conversation_id,
        platform_user_id=model.platform_user_id,
        username=model.username,
        display_name=model.display_name,
        role=model.role,
        mention_allowed=model.mention_allowed,
        teasing_allowed=model.teasing_allowed,
        metadata=model.metadata_,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def message_record(model: MessageModel) -> MessageRecord:
    return MessageRecord(
        id=model.id,
        conversation_id=model.conversation_id,
        participant_id=model.participant_id,
        platform_message_id=model.platform_message_id,
        direction=model.direction,
        message_type=model.message_type,
        text=model.text,
        reply_to_message_id=model.reply_to_message_id,
        metadata=model.metadata_,
        processing_status=model.processing_status,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class SqlAlchemyAssistantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, tenant_id: object, slug: str, name: str) -> AssistantRecord:
        model = AssistantModel(
            tenant_id=tenant_id,
            slug=slug,
            name=name,
            status=AssistantStatus.DISABLED,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return assistant_record(model)

    async def get(self, assistant_id: object) -> AssistantRecord | None:
        model = await self._session.get(AssistantModel, assistant_id)
        return assistant_record(model) if model is not None else None


class SqlAlchemyPlatformConnectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_platform_identity(
        self, platform: Platform, external_bot_id: str
    ) -> PlatformConnectionRecord | None:
        model = await self._session.scalar(
            select(PlatformConnectionModel).where(
                PlatformConnectionModel.platform == platform,
                PlatformConnectionModel.external_bot_id == external_bot_id,
            )
        )
        return connection_record(model) if model is not None else None


class SqlAlchemyConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_platform_identity(
        self, platform_connection_id: object, platform_conversation_id: str
    ) -> ConversationRecord | None:
        model = await self._session.scalar(
            select(ConversationModel).where(
                ConversationModel.platform_connection_id == platform_connection_id,
                ConversationModel.platform_conversation_id == platform_conversation_id,
            )
        )
        return conversation_record(model) if model is not None else None


class SqlAlchemyParticipantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_platform_identity(
        self, conversation_id: object, platform_user_id: str
    ) -> ParticipantRecord | None:
        model = await self._session.scalar(
            select(ParticipantModel).where(
                ParticipantModel.conversation_id == conversation_id,
                ParticipantModel.platform_user_id == platform_user_id,
            )
        )
        return participant_record(model) if model is not None else None


class SqlAlchemyMessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_platform_identity(
        self, conversation_id: object, platform_message_id: str
    ) -> MessageRecord | None:
        model = await self._session.scalar(
            select(MessageModel).where(
                MessageModel.conversation_id == conversation_id,
                MessageModel.platform_message_id == platform_message_id,
            )
        )
        return message_record(model) if model is not None else None
