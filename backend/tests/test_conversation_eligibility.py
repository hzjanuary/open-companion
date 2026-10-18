from app.application.conversation import EligibilityInput, evaluate_eligibility
from app.domain.conversation import EligibilityReason
from app.domain.persistence import (
    AssistantStatus,
    ConversationStatus,
    PlatformConnectionStatus,
    ResponseMode,
    TenantStatus,
)


def value(**changes: object) -> EligibilityInput:
    base: dict[str, object] = {
        "tenant_status": TenantStatus.ACTIVE,
        "assistant_status": AssistantStatus.ACTIVE,
        "connection_status": PlatformConnectionStatus.ACTIVE,
        "conversation_status": ConversationStatus.ACTIVE,
        "conversation_type": "group",
        "response_mode": ResponseMode.MENTION_ONLY,
        "assistant_platform_user_id": "bot",
        "assistant_display_name": "Lumi",
        "sender_platform_user_id": "member",
        "sender_is_bot": False,
        "message_type": "text",
        "message_text": "hello",
        "mentions_assistant": False,
        "replies_to_assistant": False,
        "is_edit": False,
        "is_membership_event": False,
    }
    base.update(changes)
    return EligibilityInput(**base)  # type: ignore[arg-type]


def test_response_modes_and_private_messages_are_deterministic() -> None:
    assert (
        evaluate_eligibility(value(conversation_type="private")).reason
        == EligibilityReason.ELIGIBLE_PRIVATE_MESSAGE
    )
    assert (
        evaluate_eligibility(value(mentions_assistant=True)).reason
        == EligibilityReason.ELIGIBLE_ASSISTANT_MENTIONED
    )
    assert (
        evaluate_eligibility(value(replies_to_assistant=True)).reason
        == EligibilityReason.ELIGIBLE_REPLY_TO_ASSISTANT
    )
    assert (
        evaluate_eligibility(
            value(response_mode=ResponseMode.MENTION_AND_NAME, message_text="Lumi help")
        ).reason
        == EligibilityReason.ELIGIBLE_ASSISTANT_NAME
    )
    assert (
        evaluate_eligibility(value(response_mode=ResponseMode.AMBIENT_SELECTIVE)).reason
        == EligibilityReason.ELIGIBLE_AMBIENT_CANDIDATE
    )


def test_ineligible_precedence_is_stable() -> None:
    cases = [
        (
            "assistant_status",
            AssistantStatus.DISABLED,
            EligibilityReason.ASSISTANT_INACTIVE,
        ),
        (
            "connection_status",
            PlatformConnectionStatus.DISABLED,
            EligibilityReason.CONNECTION_INACTIVE,
        ),
        (
            "conversation_status",
            ConversationStatus.PAUSED,
            EligibilityReason.CONVERSATION_PAUSED,
        ),
        ("sender_platform_user_id", "bot", EligibilityReason.SENDER_IS_ASSISTANT),
        ("sender_is_bot", True, EligibilityReason.SENDER_IS_BOT),
        ("message_type", "sticker", EligibilityReason.UNSUPPORTED_MESSAGE_TYPE),
        ("is_edit", True, EligibilityReason.EDITED_MESSAGE_NO_RESPONSE),
        ("is_membership_event", True, EligibilityReason.MEMBERSHIP_EVENT_NO_RESPONSE),
    ]
    for key, changed, expected in cases:
        assert evaluate_eligibility(value(**{key: changed})).reason == expected
