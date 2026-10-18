"""Closed domain values and outcomes for explicit conversation feedback."""

from enum import StrEnum

MAX_FEEDBACK_REVISIONS = 10


class FeedbackValue(StrEnum):
    HELPFUL = "helpful"
    UNHELPFUL = "unhelpful"


class FeedbackOutcome(StrEnum):
    SAVED = "saved"
    NO_CHANGE = "no_change"
    LIMIT_REACHED = "limit_reached"
    TARGET_UNAVAILABLE = "target_unavailable"
