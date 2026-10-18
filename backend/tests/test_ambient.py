from uuid import UUID

from app.application.ambient import apply_ambient_post_policy
from app.application.response_plan import InteractionMetadata, ResponsePlanCandidate
from app.domain.ambient import (
    AMBIENT_POLICY_VERSION,
    AMBIENT_PROFILES,
    AmbientFrequency,
    deterministic_score,
    is_sampled,
)
from app.domain.planning import PlanReasonCode
from app.domain.safety import InteractionKind


def test_sampling_is_stable_and_nested_by_frequency() -> None:
    message_id = UUID("00000000-0000-0000-0000-000000000011")
    revision_id = UUID("00000000-0000-0000-0000-000000000022")
    score = deterministic_score(message_id, revision_id, AMBIENT_POLICY_VERSION)
    assert score == deterministic_score(message_id, revision_id, AMBIENT_POLICY_VERSION)
    sampled = {
        frequency
        for frequency in AmbientFrequency
        if is_sampled(message_id, revision_id, frequency)
    }
    assert AmbientFrequency.LOW not in sampled or AmbientFrequency.NORMAL in sampled
    assert AmbientFrequency.NORMAL not in sampled or AmbientFrequency.HIGH in sampled
    assert (
        AMBIENT_PROFILES[AmbientFrequency.LOW].sample_permyriad
        < AMBIENT_PROFILES[AmbientFrequency.NORMAL].sample_permyriad
        < AMBIENT_PROFILES[AmbientFrequency.HIGH].sample_permyriad
    )


def test_sampling_does_not_depend_on_message_text_or_external_identity() -> None:
    message_id = UUID("00000000-0000-0000-0000-000000000011")
    revision_id = UUID("00000000-0000-0000-0000-000000000022")
    assert deterministic_score(message_id, revision_id) == 9289


def test_post_generation_policy_preserves_silence_and_suppresses_unsafe_ambient() -> (
    None
):
    silence = ResponsePlanCandidate(
        should_respond=False, reason_code=PlanReasonCode.SILENCE, confidence=0.2
    )
    assert apply_ambient_post_policy(silence, 0.75)[1].value == "ambient_model_silence"
    low = ResponsePlanCandidate(
        should_respond=True,
        reason_code=PlanReasonCode.ANSWER,
        text="hello",
        confidence=0.74,
    )
    suppressed, reason = apply_ambient_post_policy(low, 0.75)
    assert not suppressed.should_respond and reason.value == "ambient_low_confidence"
    mention = ResponsePlanCandidate(
        should_respond=True,
        reason_code=PlanReasonCode.ANSWER,
        text="hello",
        mentions=[UUID("00000000-0000-0000-0000-000000000033")],
        confidence=0.9,
    )
    assert (
        apply_ambient_post_policy(mention, 0.75)[1].value == "ambient_policy_suppressed"
    )
    teasing = ResponsePlanCandidate(
        should_respond=True,
        reason_code=PlanReasonCode.ANSWER,
        text="hello",
        confidence=0.9,
        interaction=InteractionMetadata(
            kind=InteractionKind.TEASING,
            teasing_target_participant_ids=[
                UUID("00000000-0000-0000-0000-000000000033")
            ],
        ),
    )
    assert (
        apply_ambient_post_policy(teasing, 0.75)[1].value == "ambient_policy_suppressed"
    )
