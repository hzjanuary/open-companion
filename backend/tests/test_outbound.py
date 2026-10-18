import asyncio
from uuid import uuid4

import pytest

from app.application.outbound import (
    ResponseTooLong,
    compile_outbound_actions,
    split_telegram_text,
)
from app.application.ports.platform import PlatformAdapterError, PlatformErrorCategory
from app.application.response_plan import ResponsePlanCandidate
from app.application.telegram_text import utf16_length
from app.core.config import Settings
from app.domain.outbound import DeliveryCertainty
from app.domain.planning import PlanReasonCode, StickerIntent
from app.infrastructure.database.models import (
    OutboundActionModel,
    OutboundDeliveryAttemptModel,
    ResponsePlanModel,
)
from app.infrastructure.telegram.rendering import (
    MentionTarget,
    render_text_with_mentions,
)
from app.runtime.outbound_delivery_worker import _record_error


def test_compile_orders_text_then_sticker_with_stable_keys() -> None:
    plan_id = uuid4()
    candidate = ResponsePlanCandidate(
        should_respond=True,
        reason_code=PlanReasonCode.ANSWER,
        text="hi",
        sticker_intent=StickerIntent.LAUGH,
        confidence=1,
    )
    first = compile_outbound_actions(plan_id, candidate)
    second = compile_outbound_actions(plan_id, candidate)
    assert [item.kind.value for item in first] == ["text", "sticker"]
    assert [item.sequence_number for item in first] == [1, 2]
    assert [item.sequence_count for item in first] == [2, 2]
    assert [item.idempotency_key for item in first] == [
        item.idempotency_key for item in second
    ]


def test_silence_compiles_no_action() -> None:
    candidate = ResponsePlanCandidate(
        should_respond=False, reason_code=PlanReasonCode.SILENCE, confidence=1
    )
    assert compile_outbound_actions(uuid4(), candidate) == ()


def test_sticker_only_compiles_one_sticker_action() -> None:
    candidate = ResponsePlanCandidate(
        should_respond=True,
        reason_code=PlanReasonCode.SOCIAL_REPLY,
        sticker_intent=StickerIntent.LAUGH,
        confidence=1,
    )
    actions = compile_outbound_actions(uuid4(), candidate)
    assert len(actions) == 1
    assert actions[0].kind.value == "sticker"
    assert actions[0].text is None


@pytest.mark.parametrize(
    "text",
    [
        "a",
        "a" * 3400,
        "a" * 3401,
        "first paragraph\n\nsecond paragraph " * 180,
        "line one\nline two\n" * 300,
        "space separated words " * 300,
        "😀" * 2000,
        "xin chào " * 500,
        "family 👨\u200d👩\u200d👧\u200d👦 " * 300,
        "x" * 13600,
    ],
)
def test_splitter_is_deterministic_unicode_safe_and_lossless(text: str) -> None:
    first = split_telegram_text(text)
    second = split_telegram_text(text)
    assert first == second
    assert "".join(first) == text
    assert 1 <= len(first) <= 4
    assert all(utf16_length(chunk) <= 3400 for chunk in first)
    assert all(not chunk.endswith("\u200d") for chunk in first)
    assert all(not (chunk and chunk[0].startswith("\u0300")) for chunk in first)


def test_splitter_empty_and_over_maximum() -> None:
    assert split_telegram_text("") == ()
    with pytest.raises(ResponseTooLong):
        split_telegram_text("x" * 13601)


def test_current_model_metadata_carries_spec034_database_checks() -> None:
    assert {
        constraint.name for constraint in ResponsePlanModel.__table__.constraints
    } >= {"ck_response_plans_response_plan_text_size"}
    assert {
        constraint.name for constraint in OutboundActionModel.__table__.constraints
    } >= {
        "ck_outbound_actions_outbound_action_sequence_bounds",
        "ck_outbound_actions_outbound_action_text_size",
    }
    assert {
        constraint.name
        for constraint in OutboundDeliveryAttemptModel.__table__.constraints
    } >= {"ck_outbound_delivery_attempts_outbound_attempt_reply_fallback_shape"}


def test_long_compilation_preserves_order_and_only_first_reply_metadata() -> None:
    target = uuid4()
    participant = uuid4()
    candidate = ResponsePlanCandidate(
        should_respond=True,
        reason_code=PlanReasonCode.ANSWER,
        text="a" * 3401,
        reply_to_message_id=target,
        mentions=[participant],
        confidence=1,
    )
    actions = compile_outbound_actions(uuid4(), candidate)
    assert [item.sequence_number for item in actions] == [1, 2]
    assert [item.sequence_count for item in actions] == [2, 2]
    assert "".join(item.text or "" for item in actions) == candidate.text
    assert actions[0].reply_to_message_id == target
    assert actions[0].mention_participant_ids == (participant,)
    assert actions[1].reply_to_message_id is None
    assert actions[1].mention_participant_ids == ()


def test_telegram_mentions_use_utf16_offsets_and_omit_missing_usernames() -> None:
    first, second = uuid4(), uuid4()
    text, entities = render_text_with_mentions(
        "Xin chao 😀",
        (
            MentionTarget(first, "lan"),
            MentionTarget(second, None),
            MentionTarget(first, "lan"),
        ),
    )
    assert text == "Xin chao 😀\n@lan"
    assert entities[0].offset == len("Xin chao 😀\n".encode("utf-16-le")) // 2
    assert entities[0].length == 4


def test_unknown_delivery_is_terminal_and_rejection_can_retry() -> None:
    class Repository:
        def __init__(self) -> None:
            self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

        async def finalize(self, *args: object, **kwargs: object) -> bool:
            self.calls.append((args, kwargs))
            return True

    async def scenario() -> None:
        repository = Repository()
        await _record_error(  # type: ignore[arg-type]
            repository,
            uuid4(),
            "worker",
            1,
            Settings(_env_file=None),
            PlatformAdapterError(
                PlatformErrorCategory.TIMEOUT,
                "sendMessage",
                delivery_certainty=DeliveryCertainty.UNKNOWN,
            ),
        )
        assert repository.calls[0][0][2].value == "delivery_unknown"  # type: ignore[union-attr]
        await _record_error(  # type: ignore[arg-type]
            repository,
            uuid4(),
            "worker",
            1,
            Settings(_env_file=None),
            PlatformAdapterError(
                PlatformErrorCategory.RATE_LIMITED,
                "sendMessage",
                retryable=True,
                retry_after_seconds=2,
                delivery_certainty=DeliveryCertainty.REJECTED,
            ),
        )
        assert repository.calls[1][0][2].value == "pending"  # type: ignore[union-attr]

    asyncio.run(scenario())
