"""Pure post-generation ambient participation policy."""

from app.application.response_plan import ResponsePlanCandidate
from app.domain.ambient import AmbientReason
from app.domain.planning import PlanReasonCode
from app.domain.safety import InteractionKind


def apply_ambient_post_policy(
    candidate: ResponsePlanCandidate, minimum_confidence: float
) -> tuple[ResponsePlanCandidate, AmbientReason]:
    """Suppress unsolicited actions that fail the ambient social policy."""
    if not candidate.should_respond:
        return candidate, AmbientReason.MODEL_SILENCE
    if candidate.confidence < minimum_confidence:
        return _silence(candidate), AmbientReason.LOW_CONFIDENCE
    if candidate.mentions or candidate.interaction.kind == InteractionKind.TEASING:
        return _silence(candidate), AmbientReason.POLICY_SUPPRESSED
    return candidate, AmbientReason.RESPONSE


def _silence(candidate: ResponsePlanCandidate) -> ResponsePlanCandidate:
    return ResponsePlanCandidate(
        should_respond=False,
        reason_code=PlanReasonCode.SILENCE,
        confidence=candidate.confidence,
        language=candidate.language,
    )
