from uuid import UUID

import pytest

from app.domain.conversation import (
    MembershipStatus,
    NormalizedMembership,
    NormalizedMessage,
)
from app.infrastructure.telegram.normalizer import (
    TelegramNormalizationError,
    normalize_telegram_update,
)
from app.infrastructure.telegram.updates import parse_telegram_update

CONNECTION_ID = UUID("00000000-0000-0000-0000-000000000001")


def normalize(payload: dict[str, object]) -> NormalizedMessage | NormalizedMembership:
    return normalize_telegram_update(
        parse_telegram_update(payload),
        platform_connection_id=CONNECTION_ID,
        assistant_platform_user_id="9000000000",
        assistant_display_name="Lumi",
        assistant_username="lumi_bot",
    )


def message(*, chat_type: str = "group", **values: object) -> dict[str, object]:
    raw: dict[str, object] = {
        "update_id": 4_000_000_000,
        "message": {
            "message_id": 5_000_000_000,
            "date": 1_700_000_000,
            "chat": {"id": -1000000000001, "type": chat_type, "title": "Group"},
            "from": {"id": 7_000_000_000, "is_bot": False, "first_name": "Member"},
            "text": "hello @lumi_bot",
            "entities": [{"type": "mention", "offset": 6, "length": 9}],
        },
    }
    raw["message"].update(values)  # type: ignore[union-attr]
    return raw


@pytest.mark.parametrize("chat_type", ["private", "group", "supergroup"])
def test_message_normalizes_large_ids_text_mentions_and_threads(chat_type: str) -> None:
    normalized = normalize(message(chat_type=chat_type, message_thread_id=42))

    assert isinstance(normalized, NormalizedMessage)
    assert normalized.conversation.conversation_type.value == chat_type
    assert normalized.platform_message_id == "5000000000"
    assert normalized.platform_thread_id == "42"
    assert normalized.mentions_assistant is True


def test_caption_sticker_edit_and_reply_normalize() -> None:
    caption = message(text=None, caption="caption", caption_entities=[])
    normalized = normalize(caption)
    assert isinstance(normalized, NormalizedMessage)
    assert normalized.text == "caption" and normalized.message_type == "text"

    sticker = normalize(message(text=None, sticker={"file_id": "not-domain"}))
    assert isinstance(sticker, NormalizedMessage)
    assert sticker.message_type == "sticker" and sticker.text is None

    edited = message()
    edited["edited_message"] = edited.pop("message")
    normalized_edit = normalize(edited)
    assert isinstance(normalized_edit, NormalizedMessage) and normalized_edit.is_edit

    reply = normalize(
        message(reply_to_message={"message_id": 4, "from": {"id": 9_000_000_000}})
    )
    assert isinstance(reply, NormalizedMessage) and reply.replies_to_assistant


def test_command_requires_a_zero_offset_bot_command_entity() -> None:
    normalized = normalize(
        message(
            text="/mode@lumi_bot mention_only",
            entities=[{"type": "bot_command", "offset": 0, "length": 14}],
        )
    )
    assert isinstance(normalized, NormalizedMessage)
    assert normalized.command is not None
    assert normalized.command.name == "mode"
    assert normalized.command.arguments == "mention_only"

    other_bot = normalize(
        message(
            text="/status@other_bot",
            entities=[{"type": "bot_command", "offset": 0, "length": 17}],
        )
    )
    assert isinstance(other_bot, NormalizedMessage) and other_bot.command is None
    prose = normalize(message(text="/status", entities=[]))
    assert isinstance(prose, NormalizedMessage) and prose.command is None


def test_membership_is_conservative_and_unknown_never_gains_role() -> None:
    payload = {
        "update_id": 4_000_000_001,
        "chat_member": {
            "date": 1_700_000_001,
            "chat": {"id": -100, "type": "group", "title": "Group"},
            "new_chat_member": {
                "status": "future-status",
                "user": {"id": 8, "is_bot": False, "first_name": "Member"},
            },
        },
    }
    normalized = normalize(payload)
    assert isinstance(normalized, NormalizedMembership)
    assert normalized.participant.membership_status == MembershipStatus.UNKNOWN
    assert normalized.participant.role.value == "member"


@pytest.mark.parametrize(
    "payload",
    [
        {"update_id": 1, "message": {"message_id": 1}},
        message(**{"from": {"id": 1, "is_bot": "wrong", "first_name": "x"}}),
        message(entities=["wrong"]),
    ],
)
def test_malformed_nested_payload_is_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(TelegramNormalizationError):
        normalize(payload)
