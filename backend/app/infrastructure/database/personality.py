"""Transactional immutable personality/default configuration reconciliation."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.personality import (
    PERSONALITY_SCHEMA_VERSION,
    PersonalityOverrides,
    PersonalityValues,
    content_hash,
    default_personality,
)
from app.domain.ambient import AmbientFrequency
from app.domain.persistence import PersonalityProfileStatus, ResponseMode
from app.infrastructure.database.models import (
    AssistantModel,
    ConversationConfigurationRevisionModel,
    ConversationModel,
    PersonalityProfileModel,
    PersonalityProfileVersionModel,
)


def _version_kwargs(values: PersonalityValues) -> dict[str, object]:
    return values.model_dump(mode="python")


async def create_profile(
    session: AsyncSession,
    assistant: AssistantModel,
    *,
    slug: str,
    display_name: str,
) -> PersonalityProfileModel:
    existing = await session.scalar(
        select(PersonalityProfileModel).where(
            PersonalityProfileModel.assistant_id == assistant.id,
            PersonalityProfileModel.slug == slug,
        )
    )
    if existing is not None:
        return existing
    profile = PersonalityProfileModel(
        assistant_id=assistant.id, slug=slug, display_name=display_name
    )
    session.add(profile)
    await session.flush()
    return profile


async def create_profile_version(
    session: AsyncSession,
    profile: PersonalityProfileModel,
    values: PersonalityValues,
    *,
    source: str,
    actor: str | None = None,
) -> PersonalityProfileVersionModel:
    digest = content_hash(values)
    existing = await session.scalar(
        select(PersonalityProfileVersionModel).where(
            PersonalityProfileVersionModel.profile_id == profile.id,
            PersonalityProfileVersionModel.content_hash == digest,
        )
    )
    if existing is not None:
        return existing
    previous = await session.scalar(
        select(PersonalityProfileVersionModel.version_number)
        .where(PersonalityProfileVersionModel.profile_id == profile.id)
        .order_by(PersonalityProfileVersionModel.version_number.desc())
        .limit(1)
    )
    version = PersonalityProfileVersionModel(
        profile_id=profile.id,
        version_number=(previous or 0) + 1,
        schema_version=PERSONALITY_SCHEMA_VERSION,
        content_hash=digest,
        created_source=source,
        created_actor=actor,
        **_version_kwargs(values),
    )
    session.add(version)
    await session.flush()
    return version


async def archive_profile(
    session: AsyncSession, profile: PersonalityProfileModel
) -> None:
    profile.status = PersonalityProfileStatus.ARCHIVED


async def ensure_assistant_default(
    session: AsyncSession, assistant: AssistantModel
) -> PersonalityProfileVersionModel:
    if assistant.default_personality_profile_version_id is not None:
        version = await session.get(
            PersonalityProfileVersionModel,
            assistant.default_personality_profile_version_id,
        )
        if version is not None:
            return version
    profile = await session.scalar(
        select(PersonalityProfileModel).where(
            PersonalityProfileModel.assistant_id == assistant.id,
            PersonalityProfileModel.slug == "january-default",
        )
    )
    if profile is None:
        profile = PersonalityProfileModel(
            assistant_id=assistant.id,
            slug="january-default",
            display_name="January Default",
        )
        session.add(profile)
        await session.flush()
    version = await session.scalar(
        select(PersonalityProfileVersionModel).where(
            PersonalityProfileVersionModel.profile_id == profile.id
        )
    )
    if version is None:
        values = default_personality()
        version = PersonalityProfileVersionModel(
            profile_id=profile.id,
            version_number=1,
            schema_version=PERSONALITY_SCHEMA_VERSION,
            content_hash=content_hash(values),
            created_source="bootstrap",
            **_version_kwargs(values),
        )
        session.add(version)
        await session.flush()
    assistant.default_personality_profile_version_id = version.id
    return version


async def ensure_conversation_configuration(
    session: AsyncSession,
    assistant: AssistantModel,
    conversation: ConversationModel,
    *,
    stickers_enabled: bool = False,
) -> ConversationConfigurationRevisionModel:
    if conversation.current_configuration_revision_id is not None:
        revision = await session.get(
            ConversationConfigurationRevisionModel,
            conversation.current_configuration_revision_id,
        )
        if revision is not None:
            return revision
    version = await ensure_assistant_default(session, assistant)
    revision = ConversationConfigurationRevisionModel(
        conversation_id=conversation.id,
        revision_number=1,
        personality_profile_version_id=version.id,
        response_mode=ResponseMode.MENTION_ONLY,
        stickers_enabled=stickers_enabled,
        ambient_frequency=AmbientFrequency.NORMAL,
        change_source="bootstrap",
    )
    session.add(revision)
    await session.flush()
    conversation.current_configuration_revision_id = revision.id
    conversation.response_mode = ResponseMode.MENTION_ONLY
    return revision


def revision_overrides(
    revision: ConversationConfigurationRevisionModel,
) -> PersonalityOverrides:
    return PersonalityOverrides(
        default_length=revision.default_length,  # type: ignore[arg-type]
        formality=revision.formality,  # type: ignore[arg-type]
        humor_level=revision.humor_level,
        teasing_level=revision.teasing_level,
        emoji_frequency=revision.emoji_frequency,
        sticker_frequency=revision.sticker_frequency,
        use_member_names=revision.use_member_names,
        ask_follow_up_questions=revision.ask_follow_up_questions,  # type: ignore[arg-type]
    )


def version_values(version: PersonalityProfileVersionModel) -> PersonalityValues:
    return PersonalityValues(
        role=version.role,  # type: ignore[arg-type]
        primary_language=version.primary_language,  # type: ignore[arg-type]
        self_reference=version.self_reference,
        default_length=version.default_length,  # type: ignore[arg-type]
        formality=version.formality,  # type: ignore[arg-type]
        humor_level=version.humor_level,
        teasing_level=version.teasing_level,
        emoji_frequency=version.emoji_frequency,
        sticker_frequency=version.sticker_frequency,
        use_member_names=version.use_member_names,
        use_inside_jokes=version.use_inside_jokes,
        ask_follow_up_questions=version.ask_follow_up_questions,  # type: ignore[arg-type]
        allow_sensitive_teasing=version.allow_sensitive_teasing,
        stop_teasing_on_request=version.stop_teasing_on_request,
        reveal_private_memory_in_groups=version.reveal_private_memory_in_groups,
    )
