"""Pure, deterministic policy for optional Telegram acknowledgement reactions."""

from dataclasses import dataclass
from unicodedata import normalize

from app.domain.ambient import ParticipationTrigger
from app.domain.persistence import MessageDirection, MessageType, Platform
from app.domain.reactions import ReactionKind

MAX_REACTION_TEXT_CODEPOINTS = 64

_HEART_ACKNOWLEDGEMENTS = frozenset({"thanks", "thank you", "cảm ơn", "cám ơn", "❤️"})
_THUMBS_UP_ACKNOWLEDGEMENTS = frozenset(
    {"ok", "okay", "got it", "understood", "sounds good", "được", "hiểu rồi", "👍"}
)


@dataclass(frozen=True, slots=True)
class ReactionFacts:
    platform: Platform
    trigger: ParticipationTrigger
    direction: MessageDirection
    message_type: MessageType
    text: str | None
    message_eligible: bool
    user_authored: bool
    content_available: bool
    ordinary_flow: bool
    authority_active: bool
    safety_allowed: bool


@dataclass(frozen=True, slots=True)
class ReactionDecision:
    kind: ReactionKind | None

    @property
    def selected(self) -> bool:
        return self.kind is not None


NO_REACTION = ReactionDecision(None)


def decide_reaction(facts: ReactionFacts) -> ReactionDecision:
    """Return one allowlisted reaction or explicit NONE from bounded facts."""

    if not (
        facts.platform == Platform.TELEGRAM
        and facts.trigger == ParticipationTrigger.ADDRESSED
        and facts.direction == MessageDirection.INCOMING
        and facts.message_type == MessageType.TEXT
        and facts.message_eligible
        and facts.user_authored
        and facts.content_available
        and facts.ordinary_flow
        and facts.authority_active
        and facts.safety_allowed
        and facts.text is not None
        and len(facts.text) <= MAX_REACTION_TEXT_CODEPOINTS
    ):
        return NO_REACTION
    text = _normalized_acknowledgement(facts.text)
    if text in _HEART_ACKNOWLEDGEMENTS:
        return ReactionDecision(ReactionKind.HEART)
    if text in _THUMBS_UP_ACKNOWLEDGEMENTS:
        return ReactionDecision(ReactionKind.THUMBS_UP)
    return NO_REACTION


def _normalized_acknowledgement(value: str) -> str:
    normalized = " ".join(normalize("NFKC", value).casefold().split())
    return normalized.rstrip(".!? ").strip()
