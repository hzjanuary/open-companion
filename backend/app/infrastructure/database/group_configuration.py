"""Immutable per-conversation configuration mutation primitives."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.personality import PersonalityOverrides
from app.domain.ambient import AmbientFrequency
from app.domain.persistence import PersonalityProfileStatus, ResponseMode
from app.domain.safety import SafetyLevel
from app.infrastructure.database.models import (
    ConversationConfigurationRevisionModel,
    ConversationModel,
    ParticipantModel,
    PersonalityProfileModel,
    PersonalityProfileVersionModel,
)
from app.infrastructure.database.personality import ensure_conversation_configuration


class ConfigurationConflictError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ConfigurationChange:
    profile_version_id: UUID | None = None
    response_mode: ResponseMode | None = None
    stickers_enabled: bool | None = None
    ambient_frequency: AmbientFrequency | None = None
    safety_level: SafetyLevel | None = None
    teasing_cap: int | None = None
    overrides: PersonalityOverrides = PersonalityOverrides()
    source: str = "operator_cli"
    reason_code: str | None = None
    actor_participant_id: UUID | None = None


class SqlAlchemyGroupConfigurationService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def apply(
        self,
        conversation_id: UUID,
        assistant_id: UUID,
        change: ConfigurationChange,
        expected_revision: int | None,
    ) -> ConversationConfigurationRevisionModel:
        async with self._session_factory() as session:
            async with session.begin():
                conversation = await session.get(
                    ConversationModel, conversation_id, with_for_update=True
                )
                if conversation is None:
                    raise ConfigurationConflictError("conversation does not exist")
                # Resolve its Assistant through the platform connection to avoid
                # accepting a profile from another Assistant.
                from app.infrastructure.database.models import (
                    AssistantModel,
                    PlatformConnectionModel,
                )

                connection = await session.get(
                    PlatformConnectionModel, conversation.platform_connection_id
                )
                assistant = await session.get(
                    AssistantModel, connection.assistant_id if connection else None
                )
                if assistant is None or assistant.id != assistant_id:
                    raise ConfigurationConflictError(
                        "conversation belongs to another Assistant"
                    )
                current = await ensure_conversation_configuration(
                    session, assistant, conversation
                )
                if (
                    expected_revision is not None
                    and expected_revision != current.revision_number
                ):
                    raise ConfigurationConflictError("configuration revision conflict")
                profile_version_id = (
                    change.profile_version_id or current.personality_profile_version_id
                )
                version = await session.get(
                    PersonalityProfileVersionModel, profile_version_id
                )
                if version is None:
                    raise ConfigurationConflictError(
                        "personality version does not exist"
                    )
                profile = await session.get(PersonalityProfileModel, version.profile_id)
                if profile is None or profile.assistant_id != assistant.id:
                    raise ConfigurationConflictError(
                        "personality version belongs to another Assistant"
                    )
                if profile.status != PersonalityProfileStatus.ACTIVE:
                    raise ConfigurationConflictError("personality profile is archived")
                if change.actor_participant_id is not None:
                    actor = await session.get(
                        ParticipantModel, change.actor_participant_id
                    )
                    if actor is None or actor.conversation_id != conversation.id:
                        raise ConfigurationConflictError(
                            "configuration actor does not belong to the conversation"
                        )
                # Pydantic tracks supplied fields separately from defaults.  This
                # lets an operator change one override without clearing the rest,
                # while an explicit ``field=None`` creates a new revision that
                # clears that one inherited value.
                supplied_overrides = change.overrides.model_dump(exclude_unset=True)
                values = {
                    field: supplied_overrides.get(field, getattr(current, field))
                    for field in PersonalityOverrides.model_fields
                }
                same = (
                    profile_version_id == current.personality_profile_version_id
                    and (change.response_mode or current.response_mode)
                    == current.response_mode
                    and (
                        change.stickers_enabled
                        if change.stickers_enabled is not None
                        else current.stickers_enabled
                    )
                    == current.stickers_enabled
                    and (change.ambient_frequency or current.ambient_frequency)
                    == current.ambient_frequency
                    and (change.safety_level or current.safety_level)
                    == current.safety_level
                    and (
                        change.teasing_cap
                        if change.teasing_cap is not None
                        else current.teasing_cap
                    )
                    == current.teasing_cap
                    and all(
                        getattr(current, key) == value for key, value in values.items()
                    )
                )
                if same:
                    return current
                revision = ConversationConfigurationRevisionModel(
                    conversation_id=conversation.id,
                    revision_number=current.revision_number + 1,
                    personality_profile_version_id=profile_version_id,
                    response_mode=change.response_mode or current.response_mode,
                    stickers_enabled=change.stickers_enabled
                    if change.stickers_enabled is not None
                    else current.stickers_enabled,
                    ambient_frequency=change.ambient_frequency
                    or current.ambient_frequency,
                    safety_level=change.safety_level or current.safety_level,
                    teasing_cap=change.teasing_cap
                    if change.teasing_cap is not None
                    else current.teasing_cap,
                    change_source=change.source,
                    reason_code=change.reason_code,
                    actor_participant_id=change.actor_participant_id,
                    **values,
                )
                session.add(revision)
                await session.flush()
                conversation.current_configuration_revision_id = revision.id
                conversation.response_mode = revision.response_mode
                return revision
