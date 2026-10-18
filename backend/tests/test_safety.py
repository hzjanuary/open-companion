"""SPEC-024 pure policy unit tests: thresholds, escalation, notices, views."""

from datetime import UTC, datetime
from uuid import uuid4

from app.application.safety import (
    render_review_item_view,
    signal_counts_view,
    thresholds_from_settings,
)
from app.core.config import Settings
from app.domain.safety import (
    AggregatedSignals,
    ProtectionAction,
    ReviewItemStatus,
    SafetyLevel,
    SafetySignalType,
    SignalThresholds,
    evaluate_protection,
    interaction_escalation,
    protection_notice,
)


def _signals(
    counts: dict[SafetySignalType, int],
    *,
    participant_id=None,
    affected_target=None,
) -> AggregatedSignals:
    return AggregatedSignals(
        conversation_id=uuid4(),
        participant_id=participant_id,
        affected_target_participant_id=affected_target,
        since=datetime(2026, 1, 1, tzinfo=UTC),
        counts=counts,
    )


def _thresholds(**overrides) -> SignalThresholds:
    values = dict(
        participant_refusals=5,
        mention_frequency=12,
        teasing_frequency=4,
        rate_limit_violations=6,
        memory_extraction=2,
        dangerous_instruction=2,
        prompt_injection=3,
        manipulation=3,
    )
    values.update(overrides)
    return SignalThresholds(**values)


def test_protection_notice_is_content_free_and_language_aware() -> None:
    english = protection_notice("en")
    vietnamese = protection_notice("vi")
    assert english and vietnamese
    assert english != vietnamese
    assert "I will limit further interaction" in english
    for language in (None, "auto", "de", "fr"):
        assert protection_notice(language) == english
    assert protection_notice("vi-VN") == vietnamese


def test_evaluate_protection_requires_threshold_exceeded() -> None:
    quiet = _signals(
        {
            SafetySignalType.MENTION_FREQUENCY: 3,
            SafetySignalType.TEASING_FREQUENCY: 1,
        }
    )
    assert evaluate_protection(quiet, _thresholds()) is None
    triggered = _signals(
        {
            SafetySignalType.MENTION_FREQUENCY: 12,
            SafetySignalType.TEASING_FREQUENCY: 1,
        }
    )
    assert (
        evaluate_protection(triggered, _thresholds()) == ProtectionAction.STOP_TARGETING
    )


def test_evaluate_protection_treats_every_signal_as_protective() -> None:
    for signal_type, threshold in (
        (SafetySignalType.DANGEROUS_INSTRUCTION_REQUEST, 2),
        (SafetySignalType.MEMORY_EXTRACTION_ATTEMPT, 2),
        (SafetySignalType.MANIPULATION_ATTEMPT, 3),
        (SafetySignalType.RATE_LIMIT_VIOLATION, 6),
    ):
        signals = _signals({signal_type: threshold})
        assert evaluate_protection(signals, _thresholds()) is not None, signal_type


def test_protective_action_signal_has_no_direct_threshold() -> None:
    thresholds = _thresholds()
    assert thresholds.for_signal(SafetySignalType.PROTECTIVE_ACTION) is None
    assert (
        evaluate_protection(
            _signals({SafetySignalType.PROTECTIVE_ACTION: 999}), thresholds
        )
        is None
    )


def test_interaction_escalation_ladder_is_deterministic() -> None:
    assert (
        interaction_escalation(0, pause_after_actions=2)
        == ProtectionAction.STOP_TARGETING
    )
    assert (
        interaction_escalation(1, pause_after_actions=2)
        == ProtectionAction.REDUCE_INTERACTION
    )
    assert (
        interaction_escalation(2, pause_after_actions=2)
        == ProtectionAction.PAUSE_INTERACTION
    )
    assert (
        interaction_escalation(5, pause_after_actions=2)
        == ProtectionAction.PAUSE_INTERACTION
    )
    assert (
        interaction_escalation(0, pause_after_actions=4)
        == ProtectionAction.STOP_TARGETING
    )
    assert (
        interaction_escalation(2, pause_after_actions=4)
        == ProtectionAction.REDUCE_INTERACTION
    )
    assert (
        interaction_escalation(4, pause_after_actions=4)
        == ProtectionAction.PAUSE_INTERACTION
    )


def test_thresholds_from_settings_scale_by_safety_level() -> None:
    settings = Settings(
        _env_file=None,
        safety_threshold_mention_frequency=10,
        safety_threshold_teasing_frequency=4,
    )
    strict = thresholds_from_settings(settings, SafetyLevel.STRICT)
    standard = thresholds_from_settings(settings, SafetyLevel.STANDARD)
    relaxed = thresholds_from_settings(settings, SafetyLevel.RELAXED)
    assert strict.mention_frequency == 5
    assert standard.mention_frequency == 10
    assert relaxed.mention_frequency == 15
    assert strict.teasing_frequency == 2
    assert relaxed.teasing_frequency == 6
    for thresholds in (strict, standard, relaxed):
        for signal_type in SafetySignalType:
            value = thresholds.for_signal(signal_type)
            if value is not None:
                assert value >= 1


def test_signal_counts_view_is_content_free() -> None:
    participant_id = uuid4()
    signals = _signals(
        {SafetySignalType.MENTION_FREQUENCY: 2, SafetySignalType.TEASING_FREQUENCY: 1},
        participant_id=participant_id,
    )
    view = signal_counts_view(signals)
    payload = f"{view}".lower()
    assert set(view) == {"conversation", "since", "counts"}
    assert "mention_frequency" in view["counts"]
    assert str(participant_id) not in payload
    for signal_type, count in view["counts"].items():
        assert isinstance(signal_type, str)
        assert isinstance(count, int)


def test_review_item_view_renders_opaque_identifiers_only() -> None:
    item_id = uuid4()
    view = render_review_item_view(
        item_id=item_id,
        category=SafetySignalType.TEASING_FREQUENCY,
        stage="pre_delivery",
        status=ReviewItemStatus.OPEN,
        outcome_counts={"teasing_frequency": 5},
        protection_state={"action": "stop_targeting"},
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert view["id"] == str(item_id)
    assert view["category"] == "teasing_frequency"
    assert view["status"] == "open"
    assert view["outcome_counts"] == {"teasing_frequency": 5}
