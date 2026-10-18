"""Telegram-only rendering of internal outbound intent."""

from dataclasses import dataclass
from uuid import UUID

from app.application.ports.platform import TextEntity


@dataclass(frozen=True, slots=True)
class MentionTarget:
    id: UUID
    username: str | None


def render_text_with_mentions(
    text: str, mentions: tuple[MentionTarget, ...]
) -> tuple[str, tuple[TextEntity, ...]]:
    """Append unique usernames and calculate Bot API UTF-16 entity offsets.

    Users without usernames are intentionally omitted; this avoids rendering a
    misleading visible mention when an entity target cannot be represented.
    """

    names = tuple(
        f"@{target.username}"
        for target in dict.fromkeys(mentions)
        if target.username is not None and target.username.strip()
    )
    if not names:
        return text, ()
    separator = "\n" if text else ""
    rendered = text + separator + " ".join(names)
    start = _utf16_length(text + separator)
    entities: list[TextEntity] = []
    for index, name in enumerate(names):
        if index:
            start += 1
        length = _utf16_length(name)
        entities.append(TextEntity("mention", start, length))
        start += length
    return rendered, tuple(entities)


def _utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2
