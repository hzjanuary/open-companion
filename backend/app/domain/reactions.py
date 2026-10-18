"""Bounded Telegram reaction values."""

from enum import StrEnum


class ReactionKind(StrEnum):
    THUMBS_UP = "thumbs_up"
    HEART = "heart"


REACTION_EMOJI: dict[ReactionKind, str] = {
    ReactionKind.THUMBS_UP: "👍",
    ReactionKind.HEART: "❤️",
}


def reaction_emoji(kind: ReactionKind) -> str:
    """Serialize only the product-approved standard emoji allowlist."""

    return REACTION_EMOJI[kind]
