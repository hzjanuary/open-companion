"""No-network operator CLI for immutable personality/configuration revisions."""

import argparse
import asyncio
import json
from uuid import UUID

from sqlalchemy import select

from app.application.personality import PersonalityOverrides, merge_effective
from app.core.config import Settings
from app.domain.persistence import ResponseMode
from app.infrastructure.database.database import Database
from app.infrastructure.database.group_configuration import (
    ConfigurationChange,
    ConfigurationConflictError,
    SqlAlchemyGroupConfigurationService,
)
from app.infrastructure.database.models import (
    AssistantModel,
    ConversationConfigurationRevisionModel,
    ConversationModel,
    PersonalityProfileModel,
    PersonalityProfileVersionModel,
    PlatformConnectionModel,
)
from app.infrastructure.database.personality import (
    archive_profile,
    create_profile,
    create_profile_version,
    ensure_assistant_default,
    ensure_conversation_configuration,
    revision_overrides,
    version_values,
)


async def _conversation_assistant(
    database: Database,
    conversation_id: UUID | None,
    platform_connection_id: UUID | None = None,
    platform_chat_id: str | None = None,
) -> tuple[ConversationModel, AssistantModel]:
    async with database.session_factory() as session:
        if conversation_id is not None:
            conversation = await session.get(ConversationModel, conversation_id)
        elif platform_connection_id is not None and platform_chat_id is not None:
            conversation = await session.scalar(
                select(ConversationModel).where(
                    ConversationModel.platform_connection_id == platform_connection_id,
                    ConversationModel.platform_conversation_id == platform_chat_id,
                )
            )
        else:
            raise ConfigurationConflictError(
                "provide --conversation-id or --platform-connection-id "
                "with --platform-chat-id"
            )
        if conversation is None:
            raise ConfigurationConflictError("conversation does not exist")
        connection = await session.get(
            PlatformConnectionModel, conversation.platform_connection_id
        )
        assistant = await session.get(
            AssistantModel, connection.assistant_id if connection else None
        )
        if assistant is None:
            raise ConfigurationConflictError("conversation assistant is unavailable")
        return conversation, assistant


def add_conversation_selector(parser: argparse.ArgumentParser) -> None:
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--conversation-id", type=UUID)
    selector.add_argument("--platform-connection-id", type=UUID)
    parser.add_argument("--platform-chat-id")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    seed = sub.add_parser("seed-default")
    seed.add_argument("--assistant-id", type=UUID, required=True)
    seed.add_argument("--apply", action="store_true")
    profiles_parser = sub.add_parser("list-profiles")
    profiles_parser.add_argument("--assistant-id", type=UUID, required=True)
    versions_parser = sub.add_parser("list-versions")
    versions_parser.add_argument("--profile-id", type=UUID, required=True)
    default_parser = sub.add_parser("show-default")
    default_parser.add_argument("--assistant-id", type=UUID, required=True)
    create = sub.add_parser("create-profile")
    create.add_argument("--assistant-id", type=UUID, required=True)
    create.add_argument("--slug", required=True)
    create.add_argument("--display-name", required=True)
    create.add_argument("--apply", action="store_true")
    version_parser = sub.add_parser("create-version")
    version_parser.add_argument("--profile-id", type=UUID, required=True)
    version_parser.add_argument("--humor-level", type=float, required=True)
    version_parser.add_argument("--teasing-level", type=float, required=True)
    version_parser.add_argument("--apply", action="store_true")
    archive = sub.add_parser("archive-profile")
    archive.add_argument("--profile-id", type=UUID, required=True)
    archive.add_argument("--apply", action="store_true")
    set_default = sub.add_parser("set-default")
    set_default.add_argument("--assistant-id", type=UUID, required=True)
    set_default.add_argument("--profile-version-id", type=UUID, required=True)
    set_default.add_argument("--apply", action="store_true")
    show = sub.add_parser("show-current")
    add_conversation_selector(show)
    history = sub.add_parser("list-history")
    add_conversation_selector(history)
    effective = sub.add_parser("show-effective")
    add_conversation_selector(effective)
    pause = sub.add_parser("pause")
    add_conversation_selector(pause)
    pause.add_argument("--expected-revision", type=int)
    pause.add_argument("--apply", action="store_true")
    resume = sub.add_parser("resume")
    add_conversation_selector(resume)
    resume.add_argument(
        "--response-mode",
        required=True,
        choices=[item.value for item in ResponseMode if item != ResponseMode.PAUSED],
    )
    resume.add_argument("--expected-revision", type=int)
    resume.add_argument("--apply", action="store_true")
    mutate = sub.add_parser("set")
    add_conversation_selector(mutate)
    mutate.add_argument("--expected-revision", type=int)
    mutate.add_argument(
        "--response-mode", choices=[item.value for item in ResponseMode]
    )
    mutate.add_argument("--profile-version-id", type=UUID)
    mutate.add_argument("--stickers-enabled", choices=["true", "false"])
    mutate.add_argument("--default-length", choices=["short", "medium"])
    mutate.add_argument("--formality", choices=["casual", "neutral"])
    mutate.add_argument("--humor-level", type=float)
    mutate.add_argument("--teasing-level", type=float)
    mutate.add_argument("--emoji-frequency", type=float)
    mutate.add_argument("--sticker-frequency", type=float)
    mutate.add_argument("--use-member-names", choices=["true", "false"])
    mutate.add_argument(
        "--ask-follow-up-questions", choices=["never", "sometimes", "often"]
    )
    mutate.add_argument(
        "--clear-override", choices=sorted(PersonalityOverrides.model_fields)
    )
    mutate.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    database = Database(settings)
    await database.start()
    try:
        if args.command == "seed-default":
            if not args.apply:
                parser.error("seed-default requires --apply")
            async with database.session_factory() as session:
                async with session.begin():
                    assistant = await session.get(AssistantModel, args.assistant_id)
                    if assistant is None:
                        raise ConfigurationConflictError("assistant does not exist")
                    default_version = await ensure_assistant_default(session, assistant)
                    conversations = list(
                        await session.scalars(
                            select(ConversationModel)
                            .join(
                                PlatformConnectionModel,
                                ConversationModel.platform_connection_id
                                == PlatformConnectionModel.id,
                            )
                            .where(PlatformConnectionModel.assistant_id == assistant.id)
                        )
                    )
                    for conversation in conversations:
                        await ensure_conversation_configuration(
                            session,
                            assistant,
                            conversation,
                            stickers_enabled=bool(settings.telegram_sticker_mapping),
                        )
                    result: dict[str, object] = {
                        "assistant_id": str(assistant.id),
                        "profile_version_id": str(default_version.id),
                        "version_number": default_version.version_number,
                        "reconciled_conversations": len(conversations),
                    }
        elif args.command == "list-profiles":
            async with database.session_factory() as session:
                profile_rows = list(
                    await session.scalars(
                        select(PersonalityProfileModel)
                        .where(
                            PersonalityProfileModel.assistant_id == args.assistant_id
                        )
                        .order_by(PersonalityProfileModel.slug)
                    )
                )
            result = {
                "profiles": [
                    {"id": str(item.id), "slug": item.slug, "status": item.status.value}
                    for item in profile_rows
                ]
            }
        elif args.command == "list-versions":
            async with database.session_factory() as session:
                version_rows = list(
                    await session.scalars(
                        select(PersonalityProfileVersionModel)
                        .where(
                            PersonalityProfileVersionModel.profile_id == args.profile_id
                        )
                        .order_by(PersonalityProfileVersionModel.version_number)
                    )
                )
            result = {
                "versions": [
                    {
                        "id": str(item.id),
                        "version_number": item.version_number,
                        "content_hash": item.content_hash,
                    }
                    for item in version_rows
                ]
            }
        elif args.command == "show-default":
            async with database.session_factory() as session:
                assistant = await session.get(AssistantModel, args.assistant_id)
                if assistant is None:
                    raise ConfigurationConflictError("assistant does not exist")
                version = await session.get(
                    PersonalityProfileVersionModel,
                    assistant.default_personality_profile_version_id,
                )
            result = {
                "assistant_id": str(args.assistant_id),
                "profile_version_id": str(version.id) if version else None,
                "version_number": version.version_number if version else None,
            }
        elif args.command == "create-profile":
            if not args.apply:
                parser.error("create-profile requires --apply")
            async with database.session_factory() as session:
                async with session.begin():
                    assistant = await session.get(AssistantModel, args.assistant_id)
                    if assistant is None:
                        raise ConfigurationConflictError("assistant does not exist")
                    profile = await create_profile(
                        session,
                        assistant,
                        slug=args.slug,
                        display_name=args.display_name,
                    )
                    result = {"profile_id": str(profile.id), "slug": profile.slug}
        elif args.command == "create-version":
            if not args.apply:
                parser.error("create-version requires --apply")
            async with database.session_factory() as session:
                async with session.begin():
                    target_profile = await session.get(
                        PersonalityProfileModel, args.profile_id
                    )
                    if target_profile is None:
                        raise ConfigurationConflictError("profile does not exist")
                    assistant = await session.get(
                        AssistantModel, target_profile.assistant_id
                    )
                    if assistant is None:
                        raise ConfigurationConflictError("profile assistant is missing")
                    latest = await session.scalar(
                        select(PersonalityProfileVersionModel)
                        .where(
                            PersonalityProfileVersionModel.profile_id
                            == target_profile.id
                        )
                        .order_by(PersonalityProfileVersionModel.version_number.desc())
                        .limit(1)
                    )
                    base = version_values(
                        latest or await ensure_assistant_default(session, assistant)
                    )
                    values = base.model_copy(
                        update={
                            "humor_level": args.humor_level,
                            "teasing_level": args.teasing_level,
                        }
                    )
                    created = await create_profile_version(
                        session, target_profile, values, source="operator_cli"
                    )
                    result = {
                        "profile_version_id": str(created.id),
                        "version_number": created.version_number,
                    }
        elif args.command == "archive-profile":
            if not args.apply:
                parser.error("archive-profile requires --apply")
            async with database.session_factory() as session:
                async with session.begin():
                    archived_profile = await session.get(
                        PersonalityProfileModel, args.profile_id
                    )
                    if archived_profile is None:
                        raise ConfigurationConflictError("profile does not exist")
                    await archive_profile(session, archived_profile)
                    result = {
                        "profile_id": str(archived_profile.id),
                        "status": archived_profile.status.value,
                    }
        elif args.command == "set-default":
            if not args.apply:
                parser.error("set-default requires --apply")
            async with database.session_factory() as session:
                async with session.begin():
                    assistant = await session.get(AssistantModel, args.assistant_id)
                    version = await session.get(
                        PersonalityProfileVersionModel, args.profile_version_id
                    )
                    if version is None:
                        raise ConfigurationConflictError(
                            "personality version does not exist"
                        )
                    default_profile = await session.get(
                        PersonalityProfileModel, version.profile_id
                    )
                    if (
                        assistant is None
                        or default_profile is None
                        or default_profile.assistant_id != assistant.id
                    ):
                        raise ConfigurationConflictError(
                            "personality version belongs to another Assistant"
                        )
                    if default_profile.status.value != "active":
                        raise ConfigurationConflictError(
                            "personality profile is archived"
                        )
                    assistant.default_personality_profile_version_id = version.id
                    result = {
                        "assistant_id": str(assistant.id),
                        "profile_version_id": str(version.id),
                    }
        elif args.command in {"show-current", "show-effective"}:
            conversation, _ = await _conversation_assistant(
                database,
                args.conversation_id,
                args.platform_connection_id,
                args.platform_chat_id,
            )
            async with database.session_factory() as session:
                revision = await session.get(
                    ConversationConfigurationRevisionModel,
                    conversation.current_configuration_revision_id,
                )
                current_version = await session.get(
                    PersonalityProfileVersionModel,
                    revision.personality_profile_version_id if revision else None,
                )
                current_profile = await session.get(
                    PersonalityProfileModel,
                    current_version.profile_id if current_version else None,
                )
            if revision is None or current_version is None or current_profile is None:
                raise ConfigurationConflictError(
                    "conversation configuration is missing"
                )
            result = merge_effective(
                version_values(current_version),
                revision_overrides(revision),
                profile_id=current_profile.id,
                profile_version_id=current_version.id,
                profile_version_number=current_version.version_number,
                configuration_revision_id=revision.id,
                configuration_revision_number=revision.revision_number,
            )
            result["response_mode"] = revision.response_mode.value
            result["stickers_enabled"] = revision.stickers_enabled
        elif args.command == "list-history":
            conversation, _ = await _conversation_assistant(
                database,
                args.conversation_id,
                args.platform_connection_id,
                args.platform_chat_id,
            )
            async with database.session_factory() as session:
                revision_rows = list(
                    await session.scalars(
                        select(ConversationConfigurationRevisionModel)
                        .where(
                            ConversationConfigurationRevisionModel.conversation_id
                            == conversation.id
                        )
                        .order_by(
                            ConversationConfigurationRevisionModel.revision_number
                        )
                    )
                )
            result = {
                "revisions": [
                    {
                        "id": str(item.id),
                        "revision_number": item.revision_number,
                        "profile_version_id": str(item.personality_profile_version_id),
                        "response_mode": item.response_mode.value,
                        "stickers_enabled": item.stickers_enabled,
                    }
                    for item in revision_rows
                ]
            }
        elif args.command in {"pause", "resume"}:
            if not args.apply:
                parser.error(f"{args.command} requires --apply")
            conversation, assistant = await _conversation_assistant(
                database,
                args.conversation_id,
                args.platform_connection_id,
                args.platform_chat_id,
            )
            response_mode = (
                ResponseMode.PAUSED
                if args.command == "pause"
                else ResponseMode(args.response_mode)
            )
            revision = await SqlAlchemyGroupConfigurationService(
                database.session_factory
            ).apply(
                conversation.id,
                assistant.id,
                ConfigurationChange(response_mode=response_mode),
                args.expected_revision,
            )
            result = {
                "conversation_id": str(conversation.id),
                "revision": revision.revision_number,
            }
        else:
            if not args.apply:
                parser.error("set requires --apply")
            conversation, assistant = await _conversation_assistant(
                database,
                args.conversation_id,
                args.platform_connection_id,
                args.platform_chat_id,
            )
            override_values = {
                key: value
                for key, value in {
                    "default_length": args.default_length,
                    "formality": args.formality,
                    "humor_level": args.humor_level,
                    "teasing_level": args.teasing_level,
                    "emoji_frequency": args.emoji_frequency,
                    "sticker_frequency": args.sticker_frequency,
                    "use_member_names": (
                        args.use_member_names == "true"
                        if args.use_member_names is not None
                        else None
                    ),
                    "ask_follow_up_questions": args.ask_follow_up_questions,
                }.items()
                if value is not None
            }
            if args.clear_override is not None:
                if args.clear_override in override_values:
                    parser.error("cannot set and clear the same override")
                override_values[args.clear_override] = None
            overrides = PersonalityOverrides.model_validate(override_values)
            revision = await SqlAlchemyGroupConfigurationService(
                database.session_factory
            ).apply(
                conversation.id,
                assistant.id,
                ConfigurationChange(
                    profile_version_id=args.profile_version_id,
                    response_mode=ResponseMode(args.response_mode)
                    if args.response_mode
                    else None,
                    stickers_enabled=args.stickers_enabled == "true"
                    if args.stickers_enabled is not None
                    else None,
                    overrides=overrides,
                ),
                args.expected_revision,
            )
            result = {
                "conversation_id": str(conversation.id),
                "revision": revision.revision_number,
            }
        print(
            json.dumps(result, sort_keys=True)
            if args.json
            else json.dumps(result, indent=2, sort_keys=True)
        )
        return 0
    except ConfigurationConflictError as error:
        parser.error(str(error))
    finally:
        await database.stop()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
