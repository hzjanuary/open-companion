import asyncio

import pytest
from sqlalchemy import text

from app.application.personality import PersonalityOverrides, default_personality
from app.core.config import Settings
from app.domain.persistence import (
    AssistantStatus,
    ConversationType,
    Platform,
    PlatformConnectionStatus,
)
from app.domain.tenancy import LEGACY_TENANT_ID
from app.infrastructure.database.database import Database
from app.infrastructure.database.group_configuration import (
    ConfigurationChange,
    ConfigurationConflictError,
    SqlAlchemyGroupConfigurationService,
)
from app.infrastructure.database.models import (
    AssistantModel,
    ConversationModel,
    PersonalityProfileModel,
    PlatformConnectionModel,
)
from app.infrastructure.database.personality import (
    archive_profile,
    create_profile,
    create_profile_version,
    ensure_conversation_configuration,
)


@pytest.mark.integration
@pytest.mark.personality_integration
def test_immutable_personality_revisions_are_idempotent_and_isolated() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            async with database.engine.begin() as connection:
                await connection.execute(text("TRUNCATE assistants CASCADE"))
            async with database.session_factory() as session:
                async with session.begin():
                    assistant = AssistantModel(
                        tenant_id=LEGACY_TENANT_ID,
                        slug="personality-january",
                        name="January",
                        status=AssistantStatus.ACTIVE,
                    )
                    session.add(assistant)
                    await session.flush()
                    connection = PlatformConnectionModel(
                        tenant_id=LEGACY_TENANT_ID,
                        assistant_id=assistant.id,
                        platform=Platform.TELEGRAM,
                        external_bot_id="bot-personality",
                        status=PlatformConnectionStatus.ACTIVE,
                    )
                    session.add(connection)
                    await session.flush()
                    first = ConversationModel(
                        platform_connection_id=connection.id,
                        platform_conversation_id="1001",
                        conversation_type=ConversationType.GROUP,
                    )
                    second = ConversationModel(
                        platform_connection_id=connection.id,
                        platform_conversation_id="1002",
                        conversation_type=ConversationType.GROUP,
                    )
                    session.add_all([first, second])
                    await session.flush()
                    first_revision = await ensure_conversation_configuration(
                        session, assistant, first
                    )
                    assert (
                        await ensure_conversation_configuration(
                            session, assistant, first
                        )
                    ).id == first_revision.id
                    second_revision = await ensure_conversation_configuration(
                        session, assistant, second
                    )
                    profile = await create_profile(
                        session, assistant, slug="calmer", display_name="Calmer"
                    )
                    values = default_personality().model_copy(
                        update={"humor_level": 0.1, "teasing_level": 0.0}
                    )
                    version = await create_profile_version(
                        session, profile, values, source="test"
                    )
                    assert (
                        await create_profile_version(
                            session, profile, values, source="test"
                        )
                    ).id == version.id
                    first_id, second_id, assistant_id = (
                        first.id,
                        second.id,
                        assistant.id,
                    )
                    assert second_revision.personality_profile_version_id != version.id
            service = SqlAlchemyGroupConfigurationService(database.session_factory)
            changed = await service.apply(
                first_id,
                assistant_id,
                ConfigurationChange(
                    profile_version_id=version.id,
                    overrides=PersonalityOverrides(
                        humor_level=0, use_member_names=False
                    ),
                ),
                expected_revision=1,
            )
            assert changed.revision_number == 2
            retained = await service.apply(
                first_id,
                assistant_id,
                ConfigurationChange(
                    overrides=PersonalityOverrides(emoji_frequency=0.1)
                ),
                2,
            )
            assert retained.revision_number == 3
            assert retained.humor_level == 0
            assert retained.use_member_names is False
            cleared = await service.apply(
                first_id,
                assistant_id,
                ConfigurationChange(overrides=PersonalityOverrides(humor_level=None)),
                3,
            )
            assert cleared.revision_number == 4
            assert cleared.humor_level is None
            assert (
                await service.apply(
                    first_id,
                    assistant_id,
                    ConfigurationChange(
                        profile_version_id=version.id,
                        overrides=PersonalityOverrides(emoji_frequency=0.1),
                    ),
                    4,
                )
            ).id == cleared.id
            with pytest.raises(ConfigurationConflictError, match="revision conflict"):
                await service.apply(first_id, assistant_id, ConfigurationChange(), 1)
            async with database.session_factory() as session:
                async with session.begin():
                    profile_to_archive = await session.get(
                        PersonalityProfileModel, profile.id
                    )
                    assert profile_to_archive is not None
                    await archive_profile(session, profile_to_archive)
            with pytest.raises(ConfigurationConflictError, match="profile is archived"):
                await service.apply(
                    first_id,
                    assistant_id,
                    ConfigurationChange(profile_version_id=version.id),
                    4,
                )
            async with database.session_factory() as session:
                second = await session.get(ConversationModel, second_id)
                assert second is not None
                assert second.current_configuration_revision_id != cleared.id
        finally:
            await database.stop()

    asyncio.run(scenario())
