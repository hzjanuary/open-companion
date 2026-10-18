"""Small persistence ports that do not expose SQLAlchemy objects."""

from typing import Protocol
from uuid import UUID

from app.domain.persistence import (
    AssistantRecord,
    ConversationRecord,
    MessageRecord,
    ParticipantRecord,
    Platform,
    PlatformConnectionRecord,
)


class AssistantRepository(Protocol):
    async def add(self, tenant_id: UUID, slug: str, name: str) -> AssistantRecord: ...

    async def get(self, assistant_id: UUID) -> AssistantRecord | None: ...


class PlatformConnectionRepository(Protocol):
    async def get_by_platform_identity(
        self, platform: Platform, external_bot_id: str
    ) -> PlatformConnectionRecord | None: ...


class ConversationRepository(Protocol):
    async def get_by_platform_identity(
        self, platform_connection_id: UUID, platform_conversation_id: str
    ) -> ConversationRecord | None: ...


class ParticipantRepository(Protocol):
    async def get_by_platform_identity(
        self, conversation_id: UUID, platform_user_id: str
    ) -> ParticipantRecord | None: ...


class MessageRepository(Protocol):
    async def get_by_platform_identity(
        self, conversation_id: UUID, platform_message_id: str
    ) -> MessageRecord | None: ...
