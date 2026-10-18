"""Pure Telegram regeneration presentation policy."""

from dataclasses import dataclass
from enum import StrEnum

from app.application.outbound import split_telegram_text
from app.application.response_plan import ResponsePlanCandidate


class RegenerationPresentation(StrEnum):
    EDIT_EXISTING = "edit_existing"
    SEND_NEW = "send_new"


@dataclass(frozen=True, slots=True)
class EditTargetFacts:
    exactly_one_delivered_text: bool
    platform_message_id_known: bool
    same_authority: bool
    target_content_available: bool
    ambiguous_prior_edit: bool
    deterministically_editable: bool


def choose_regeneration_presentation(
    candidate: ResponsePlanCandidate, facts: EditTargetFacts
) -> RegenerationPresentation:
    """Choose edit only when every authoritative safety fact is positive."""

    chunks = split_telegram_text(candidate.text) if candidate.text else ()
    if (
        candidate.should_respond
        and candidate.sticker_intent is None
        and len(chunks) == 1
        and facts.exactly_one_delivered_text
        and facts.platform_message_id_known
        and facts.same_authority
        and facts.target_content_available
        and not facts.ambiguous_prior_edit
        and facts.deterministically_editable
    ):
        return RegenerationPresentation.EDIT_EXISTING
    return RegenerationPresentation.SEND_NEW
