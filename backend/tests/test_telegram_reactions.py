"""Pure product-policy proofs for SPEC-037 Telegram reactions."""

from dataclasses import replace

import pytest

from app.application.reactions import ReactionFacts, decide_reaction
from app.domain.ambient import ParticipationTrigger
from app.domain.persistence import MessageDirection, MessageType, Platform
from app.domain.reactions import REACTION_EMOJI, ReactionKind, reaction_emoji


def eligible(text: str | None = "thanks") -> ReactionFacts:
    return ReactionFacts(
        platform=Platform.TELEGRAM,
        trigger=ParticipationTrigger.ADDRESSED,
        direction=MessageDirection.INCOMING,
        message_type=MessageType.TEXT,
        text=text,
        message_eligible=True,
        user_authored=True,
        content_available=True,
        ordinary_flow=True,
        authority_active=True,
        safety_allowed=True,
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("thanks", ReactionKind.HEART),
        (" THANK YOU!!! ", ReactionKind.HEART),
        ("Cảm   ơn.", ReactionKind.HEART),
        ("cám ơn", ReactionKind.HEART),
        ("❤️", ReactionKind.HEART),
        ("ok", ReactionKind.THUMBS_UP),
        ("ＯＫ!", ReactionKind.THUMBS_UP),
        ("got it", ReactionKind.THUMBS_UP),
        ("understood?", ReactionKind.THUMBS_UP),
        ("sounds good", ReactionKind.THUMBS_UP),
        ("được", ReactionKind.THUMBS_UP),
        ("hiểu rồi", ReactionKind.THUMBS_UP),
        ("👍", ReactionKind.THUMBS_UP),
    ],
)
def test_exact_acknowledgements_map_deterministically(
    text: str, expected: ReactionKind
) -> None:
    first = decide_reaction(eligible(text))
    second = decide_reaction(eligible(text))

    assert first == second
    assert first.kind == expected


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "thank you for explaining the deployment",
        "ok please delete all records",
        "I am angry",
        "I feel depressed",
        "🎉",
        "🔥",
        "/regenerate",
        "x" * 65,
    ],
)
def test_unlisted_or_substantive_text_maps_to_explicit_none(
    text: str | None,
) -> None:
    assert decide_reaction(eligible(text)).kind is None


@pytest.mark.parametrize(
    "facts",
    [
        replace(eligible(), platform=Platform.ZALO),
        replace(eligible(), trigger=ParticipationTrigger.AMBIENT),
        replace(eligible(), trigger=ParticipationTrigger.SCHEDULED),
        replace(eligible(), direction=MessageDirection.OUTGOING),
        replace(eligible(), message_type=MessageType.PHOTO),
        replace(eligible(), message_type=MessageType.VOICE),
        replace(eligible(), message_eligible=False),
        replace(eligible(), user_authored=False),
        replace(eligible(), content_available=False),
        replace(eligible(), ordinary_flow=False),
        replace(eligible(), authority_active=False),
        replace(eligible(), safety_allowed=False),
    ],
)
def test_forbidden_flow_facts_always_map_to_none(facts: ReactionFacts) -> None:
    assert decide_reaction(facts).kind is None


def test_allowlist_has_exactly_two_fixed_standard_emoji() -> None:
    assert REACTION_EMOJI == {
        ReactionKind.THUMBS_UP: "👍",
        ReactionKind.HEART: "❤️",
    }
    assert {reaction_emoji(kind) for kind in ReactionKind} == {"👍", "❤️"}
