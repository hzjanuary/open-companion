"""SPEC-028 deterministic media boundary proof; no external credentials."""

from uuid import uuid4

import pytest

from app.domain.conversation import NormalizedMessage
from app.domain.media import EphemeralMedia, MediaFailureReason, MediaKind, MediaLimits
from app.infrastructure.telegram.media import normalize_media
from app.infrastructure.telegram.normalizer import normalize_telegram_update
from app.infrastructure.telegram.updates import parse_telegram_update


def normalized(**content: object) -> NormalizedMessage:
    result = normalize_telegram_update(
        parse_telegram_update(
            {
                "update_id": 100,
                "message": {
                    "message_id": 20,
                    "date": 1_700_000_000,
                    "chat": {"id": 123, "type": "private"},
                    "from": {"id": 42, "first_name": "Test", "is_bot": False},
                    **content,
                },
            }
        ),
        platform_connection_id=uuid4(),
        assistant_platform_user_id="777",
        assistant_display_name="Lumi",
        assistant_username="lumi_bot",
    )
    assert isinstance(result, NormalizedMessage)
    return result


def photo(reference: str, width: int, size: int | None = None) -> dict[str, object]:
    result: dict[str, object] = {
        "file_id": reference,
        "file_unique_id": f"unique_{reference}",
        "width": width,
        "height": width,
    }
    if size is not None:
        result["file_size"] = size
    return result


def test_text_and_sticker_remain_unchanged() -> None:
    result = normalized(text="hello")
    assert result.text == "hello" and result.message_type == "text"
    assert result.attachment is None and result.media_failure is None
    sticker = normalized(sticker={"file_id": "existing_sticker"})
    assert sticker.message_type == "sticker" and sticker.attachment is None


def test_photo_selection_is_bounded_and_independent_of_input_order() -> None:
    variants = [
        photo("small", 320, 100),
        photo("chosen", 1280, 4000),
        photo("big", 4096),
    ]
    first = normalized(photo=variants, caption="What is this?")
    second = normalized(photo=list(reversed(variants)))
    assert first.attachment == second.attachment
    assert first.attachment is not None
    assert first.attachment.file_id == "chosen"
    assert first.text == "What is this?"
    assert first.message_type == "photo"


def test_photo_ties_prefer_known_size_then_stable_reference() -> None:
    variants = [photo("z", 300), photo("b", 300, 200), photo("a", 300, 200)]
    result = normalized(photo=variants)
    assert result.attachment is not None and result.attachment.file_id == "a"


def test_unknown_size_photo_requires_later_stream_bound_not_all_sizes() -> None:
    result = normalized(photo=[photo("one", 500)])
    assert result.attachment is not None and result.attachment.file_size is None


def test_caption_uses_utf16_addressing_and_never_becomes_command() -> None:
    result = normalized(
        photo=[photo("one", 400)],
        caption="😀 @lumi_bot explain",
        caption_entities=[{"type": "mention", "offset": 3, "length": 9}],
    )
    assert result.mentions_assistant
    command_caption = normalized(
        photo=[photo("one", 400)],
        caption="/forget_me confirm",
        caption_entities=[{"type": "bot_command", "offset": 0, "length": 10}],
    )
    assert command_caption.command is None
    typed = normalized(
        text="/forget_me confirm",
        entities=[{"type": "bot_command", "offset": 0, "length": 10}],
    )
    assert typed.command is not None


@pytest.mark.parametrize("kind,mime", [("voice", "audio/ogg"), ("audio", "audio/mpeg")])
def test_audio_pipeline_metadata(kind: str, mime: str) -> None:
    result = normalized(
        **{
            kind: {
                "file_id": "sensitive_reference",
                "file_unique_id": "sensitive_unique",
                "duration": 60,
                "mime_type": mime,
                "file_size": 200,
            }
        }
    )
    assert result.message_type == kind
    assert result.attachment is not None
    assert result.attachment.duration_seconds == 60
    assert result.attachment.mime_type == mime
    assert "sensitive" not in repr(result.attachment)


@pytest.mark.parametrize("kind", ["video", "video_note", "document", "animation"])
def test_unsupported_media_has_no_fetch_reference(kind: str) -> None:
    result = normalized(**{kind: {"file_id": "do_not_fetch"}})
    assert result.message_type == "unsupported_media"
    assert result.attachment is None
    assert result.media_failure == MediaFailureReason.UNSUPPORTED


@pytest.mark.parametrize(
    "payload,reason",
    [
        ({"photo": [photo("large", 400, 6 * 1024 * 1024)]}, "too_large"),
        ({"photo": [photo("large", 2000)]}, "too_large"),
        ({"photo": []}, "invalid_format"),
        ({"photo": [photo("a", 1)] * 21}, "invalid_format"),
        ({"photo": [photo("https://evil.invalid/", 1)]}, "invalid_format"),
        ({"photo": [{**photo("one", 20), "file_size": True}]}, "invalid_format"),
        ({"photo": [photo("one", 20)], "voice": {}}, "invalid_format"),
        (
            {"voice": {"file_id": "a", "file_unique_id": "b", "duration": 121}},
            "too_large",
        ),
        (
            {"voice": {"file_id": "a", "file_unique_id": "b", "duration": True}},
            "invalid_format",
        ),
        ({"audio": {"mime_type": "audio/mp4"}}, "unsupported"),
    ],
)
def test_rejected_media_metadata(payload: dict[str, object], reason: str) -> None:
    _, attachment, failure = normalize_media(payload, MediaLimits())
    assert attachment is None and failure == reason


def test_caption_limit_and_album_independence() -> None:
    long_caption = normalized(photo=[photo("one", 200)], caption="x" * 1025)
    assert long_caption.text is None and long_caption.attachment is None
    assert long_caption.media_failure == MediaFailureReason.TOO_LARGE
    album = normalized(photo=[photo("one", 200)], media_group_id="group")
    single = normalized(photo=[photo("one", 200)])
    assert album.attachment == single.attachment


def test_ephemeral_bytes_are_not_in_representation() -> None:
    value = EphemeralMedia(MediaKind.PHOTO, "image/jpeg", b"private_raw_media")
    assert "private_raw_media" not in repr(value)


@pytest.mark.parametrize("limit", [0, -1, True, 10 * 1024 * 1024 + 1])
def test_limits_cannot_exceed_product_caps(limit: int) -> None:
    with pytest.raises(ValueError, match="approved bounds"):
        MediaLimits(photo_max_bytes=limit)
