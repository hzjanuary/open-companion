from dataclasses import replace

import pytest

from app.application.regeneration import (
    EditTargetFacts,
    RegenerationPresentation,
    choose_regeneration_presentation,
)
from app.application.response_plan import ResponsePlanCandidate
from app.domain.planning import PlanReasonCode, StickerIntent


def candidate(
    *, text: str = "replacement", sticker: StickerIntent | None = None
) -> ResponsePlanCandidate:
    return ResponsePlanCandidate(
        should_respond=True,
        reason_code=PlanReasonCode.ANSWER,
        text=text,
        sticker_intent=sticker,
        confidence=1,
    )


def eligible_facts() -> EditTargetFacts:
    return EditTargetFacts(
        exactly_one_delivered_text=True,
        platform_message_id_known=True,
        same_authority=True,
        target_content_available=True,
        ambiguous_prior_edit=False,
        deterministically_editable=True,
    )


def test_single_certain_text_presentation_is_edit_eligible() -> None:
    assert (
        choose_regeneration_presentation(candidate(), eligible_facts())
        == RegenerationPresentation.EDIT_EXISTING
    )


@pytest.mark.parametrize(
    "facts",
    [
        replace(eligible_facts(), exactly_one_delivered_text=False),
        replace(eligible_facts(), platform_message_id_known=False),
        replace(eligible_facts(), same_authority=False),
        replace(eligible_facts(), target_content_available=False),
        replace(eligible_facts(), ambiguous_prior_edit=True),
        replace(eligible_facts(), deterministically_editable=False),
    ],
)
def test_authority_or_certainty_failure_selects_new_message(
    facts: EditTargetFacts,
) -> None:
    assert (
        choose_regeneration_presentation(candidate(), facts)
        == RegenerationPresentation.SEND_NEW
    )


def test_split_or_sticker_regeneration_selects_new_message() -> None:
    assert (
        choose_regeneration_presentation(candidate(text="x" * 3401), eligible_facts())
        == RegenerationPresentation.SEND_NEW
    )
    assert (
        choose_regeneration_presentation(
            candidate(sticker=StickerIntent.SUPPORT), eligible_facts()
        )
        == RegenerationPresentation.SEND_NEW
    )
