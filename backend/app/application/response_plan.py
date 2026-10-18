"""Strict local response-plan schema and deterministic post-generation policy."""

from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.application.context import ConversationContext
from app.application.telegram_text import utf16_length
from app.domain.planning import PlanReasonCode, StickerIntent
from app.domain.safety import InteractionKind, SensitiveTopicCategory, safe_fallback


class InteractionMetadata(BaseModel):
    """Bounded structural classification supplied by response-plan-v2 models."""

    model_config = ConfigDict(extra="forbid", strict=True)

    kind: InteractionKind = InteractionKind.NEUTRAL
    teasing_target_participant_ids: list[UUID] = Field(
        default_factory=list, max_length=10
    )
    sensitive_topic_categories: list[SensitiveTopicCategory] = Field(
        default_factory=list, max_length=9
    )

    @model_validator(mode="after")
    def validate_shape(self) -> "InteractionMetadata":
        targets = self.teasing_target_participant_ids
        if len(set(targets)) != len(targets):
            raise ValueError("teasing targets must be unique")
        if self.kind == InteractionKind.TEASING and not targets:
            raise ValueError("teasing requires at least one target")
        if self.kind != InteractionKind.TEASING and targets:
            raise ValueError("only teasing can include teasing targets")
        if len(set(self.sensitive_topic_categories)) != len(
            self.sensitive_topic_categories
        ):
            raise ValueError("sensitive topic categories must be unique")
        return self


class ResponsePlanCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    should_respond: bool
    reason_code: PlanReasonCode
    text: str | None = None
    reply_to_message_id: UUID | None = None
    mentions: list[UUID] = Field(default_factory=list, max_length=20)
    sticker_intent: StickerIntent | None = None
    confidence: float = Field(ge=0, le=1)
    language: str | None = Field(default=None, min_length=2, max_length=16)
    interaction: InteractionMetadata = Field(default_factory=InteractionMetadata)

    @model_validator(mode="after")
    def validate_action_shape(self) -> "ResponsePlanCandidate":
        if self.text is not None and not self.text.strip():
            raise ValueError("text must be nonblank when present")
        has_action = self.text is not None or self.sticker_intent is not None
        if self.should_respond and not has_action:
            raise ValueError("a response requires text or sticker intent")
        if not self.should_respond and (
            has_action
            or self.reply_to_message_id is not None
            or self.mentions
            or self.interaction.kind != InteractionKind.NEUTRAL
        ):
            raise ValueError("silence cannot contain action fields")
        return self


@dataclass(frozen=True, slots=True)
class ResponsePlanPolicy:
    text_limit: int
    supported_stickers: frozenset[StickerIntent]
    teasing_permitted: bool = True
    reply_to_current: bool = True

    def apply(
        self, candidate: ResponsePlanCandidate, context: ConversationContext
    ) -> ResponsePlanCandidate:
        allowed_messages = {
            item.id
            for item in (context.current, *context.reply_chain, *context.recent_history)
        }
        allowed_participants = {
            item.participant_id: item
            for item in (context.current, *context.reply_chain, *context.recent_history)
            if item.participant_id is not None
        }
        if (
            candidate.reply_to_message_id is not None
            and candidate.reply_to_message_id not in allowed_messages
        ):
            raise ValueError("reply target is outside context")
        mentions = tuple(dict.fromkeys(candidate.mentions))
        if any(identifier not in allowed_participants for identifier in mentions):
            raise ValueError("mention target is outside context")
        mentions = tuple(
            identifier
            for identifier in mentions
            if allowed_participants[identifier].mention_allowed
            and not allowed_participants[identifier].privacy_deleted
            and not allowed_participants[identifier].protected
        )
        text = candidate.text
        if text is not None and utf16_length(text) > self.text_limit:
            raise ValueError("response text exceeds logical delivery limit")
        sticker = candidate.sticker_intent
        if sticker is not None and sticker not in self.supported_stickers:
            sticker = None
        if candidate.should_respond and text is None and sticker is None:
            return ResponsePlanCandidate(
                should_respond=False,
                reason_code=PlanReasonCode.SILENCE,
                confidence=candidate.confidence,
                language=candidate.language,
            )
        interaction = candidate.interaction
        teasing_targets = tuple(
            dict.fromkeys(interaction.teasing_target_participant_ids)
        )
        if interaction.kind == InteractionKind.TEASING and any(
            identifier not in allowed_participants for identifier in teasing_targets
        ):
            raise ValueError("teasing target is outside context")
        teasing_allowed = (
            interaction.kind == InteractionKind.TEASING
            and self.teasing_permitted
            and not interaction.sensitive_topic_categories
            and all(
                identifier in allowed_participants
                and allowed_participants[identifier].teasing_allowed
                and not allowed_participants[identifier].privacy_deleted
                and not allowed_participants[identifier].protected
                for identifier in teasing_targets
            )
        )
        if interaction.kind == InteractionKind.TEASING and not teasing_allowed:
            interaction = InteractionMetadata(kind=InteractionKind.NEUTRAL)
            sticker = None
            text = safe_fallback(candidate.language)
        if interaction.kind == InteractionKind.TEASING and not teasing_targets:
            raise ValueError("teasing target is outside context")
        return ResponsePlanCandidate(
            should_respond=candidate.should_respond,
            reason_code=candidate.reason_code,
            text=text,
            reply_to_message_id=(
                context.current.id
                if candidate.should_respond and self.reply_to_current
                else None
            ),
            mentions=list(mentions),
            sticker_intent=sticker,
            confidence=candidate.confidence,
            language=candidate.language,
            interaction=interaction,
        )


def response_plan_json_schema() -> dict[str, object]:
    """Stable strict schema sent to providers and checked locally again."""

    return ResponsePlanCandidate.model_json_schema()
