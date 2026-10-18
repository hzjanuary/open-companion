"""Pure bounded Telegram media normalization; no network or file access."""

import re
from typing import Any

from app.domain.media import (
    MediaAttachment,
    MediaFailureReason,
    MediaKind,
    MediaLimits,
)

_FILE_REFERENCE = re.compile(r"[A-Za-z0-9_-]{1,255}\Z")
_UNSUPPORTED_FIELDS = frozenset(
    {"video", "video_note", "document", "animation", "paid_media", "live_photo"}
)


def normalize_media(
    payload: dict[str, Any], limits: MediaLimits
) -> tuple[str | None, MediaAttachment | None, MediaFailureReason | None]:
    """Choose one attachment; invalid metadata produces a content-safe fallback."""

    active = [key for key in ("photo", "voice", "audio") if key in payload]
    if len(active) > 1:
        return "unsupported_media", None, MediaFailureReason.INVALID_FORMAT
    if not active:
        if _UNSUPPORTED_FIELDS.intersection(payload):
            return "unsupported_media", None, MediaFailureReason.UNSUPPORTED
        return None, None, None
    kind = MediaKind(active[0])
    if kind == MediaKind.PHOTO:
        return _photo(payload["photo"], limits)
    raw = payload[kind.value]
    if not isinstance(raw, dict):
        return kind.value, None, MediaFailureReason.INVALID_FORMAT
    mime = "audio/ogg" if kind == MediaKind.VOICE else "audio/mpeg"
    if raw.get("mime_type", mime) != mime:
        return kind.value, None, MediaFailureReason.UNSUPPORTED
    try:
        file_id, unique_id, size = _file(raw)
        duration = _integer(raw.get("duration"), minimum=0)
    except ValueError:
        return kind.value, None, MediaFailureReason.INVALID_FORMAT
    if (
        size is not None and size > limits.audio_max_bytes
    ) or duration > limits.audio_max_duration_seconds:
        return kind.value, None, MediaFailureReason.TOO_LARGE
    return (
        kind.value,
        MediaAttachment(
            kind, file_id, unique_id, mime, size, duration_seconds=duration
        ),
        None,
    )


def _photo(
    value: object, limits: MediaLimits
) -> tuple[str, MediaAttachment | None, MediaFailureReason | None]:
    if not isinstance(value, list) or not 1 <= len(value) <= 20:
        return "photo", None, MediaFailureReason.INVALID_FORMAT
    candidates: list[MediaAttachment] = []
    oversized = False
    for raw in value:
        if not isinstance(raw, dict):
            continue
        try:
            file_id, unique_id, size = _file(raw)
            width = _integer(raw.get("width"), minimum=1)
            height = _integer(raw.get("height"), minimum=1)
        except ValueError:
            continue
        if max(width, height) > limits.photo_max_side or (
            size is not None and size > limits.photo_max_bytes
        ):
            oversized = True
            continue
        candidates.append(
            MediaAttachment(
                MediaKind.PHOTO, file_id, unique_id, "image/jpeg", size, width, height
            )
        )
    if not candidates:
        return (
            "photo",
            None,
            MediaFailureReason.TOO_LARGE
            if oversized
            else MediaFailureReason.INVALID_FORMAT,
        )
    selected = min(
        candidates,
        key=lambda item: (
            -(item.width or 0) * (item.height or 0),
            -(item.width or 0),
            -(item.height or 0),
            item.file_size
            if item.file_size is not None
            else limits.photo_max_bytes + 1,
            item.file_unique_id,
            item.file_id,
        ),
    )
    return "photo", selected, None


def _file(raw: dict[str, Any]) -> tuple[str, str, int | None]:
    file_id, unique_id = raw.get("file_id"), raw.get("file_unique_id")
    if not (
        isinstance(file_id, str)
        and _FILE_REFERENCE.fullmatch(file_id)
        and isinstance(unique_id, str)
        and _FILE_REFERENCE.fullmatch(unique_id)
    ):
        raise ValueError("invalid media reference")
    size = raw.get("file_size")
    return (
        file_id,
        unique_id,
        _integer(size, minimum=1) if size is not None else None,
    )


def _integer(value: object, *, minimum: int) -> int:
    if type(value) is not int or value < minimum or value > 2**63 - 1:
        raise ValueError("invalid media dimension")
    return value
