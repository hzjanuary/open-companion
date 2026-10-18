"""Compile approved response plans into deterministic outbound action specs."""

import unicodedata
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from uuid import UUID

from app.application.response_plan import ResponsePlanCandidate
from app.application.telegram_text import (
    TELEGRAM_LOGICAL_RESPONSE_UTF16_LIMIT,
    TELEGRAM_MAX_TEXT_CHUNKS,
    TELEGRAM_TEXT_CHUNK_UTF16_LIMIT,
    utf16_length,
)
from app.domain.outbound import (
    DeliveryCertainty,
    OutboundActionKind,
    OutboundActionStatus,
)
from app.domain.planning import StickerIntent


@dataclass(frozen=True, slots=True)
class OutboundActionSpec:
    sequence_number: int
    sequence_count: int
    kind: OutboundActionKind
    idempotency_key: str
    text: str | None
    reply_to_message_id: UUID | None
    mention_participant_ids: tuple[UUID, ...]
    sticker_intent: StickerIntent | None


@dataclass(frozen=True, slots=True)
class OutboundAction:
    id: UUID
    response_plan_id: UUID
    conversation_id: UUID
    sequence_number: int
    kind: OutboundActionKind
    status: OutboundActionStatus
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class OutboundActionClaim:
    action_id: UUID
    owner: str
    attempt_number: int
    lease_expires_at: datetime


@dataclass(frozen=True, slots=True)
class DeliveryRequest:
    action_id: UUID
    conversation_id: UUID
    kind: OutboundActionKind


@dataclass(frozen=True, slots=True)
class ConfirmedDelivery:
    platform_message_id: str
    platform_thread_id: str | None


@dataclass(frozen=True, slots=True)
class DeliveryFailure:
    certainty: DeliveryCertainty
    category: str
    retryable: bool


@dataclass(frozen=True, slots=True)
class ActionCompletion:
    action_id: UUID
    status: OutboundActionStatus
    certainty: DeliveryCertainty


def compile_outbound_actions(
    response_plan_id: UUID, candidate: ResponsePlanCandidate
) -> tuple[OutboundActionSpec, ...]:
    """Create stable action records without importing platform concerns."""

    if not candidate.should_respond:
        return ()
    pending: list[tuple[OutboundActionKind, str | None, StickerIntent | None]] = []
    if candidate.text is not None:
        pending.extend(
            (OutboundActionKind.TEXT, chunk, None)
            for chunk in split_telegram_text(candidate.text)
        )
    if candidate.sticker_intent is not None:
        pending.append((OutboundActionKind.STICKER, None, candidate.sticker_intent))
    count = len(pending)
    return tuple(
        _action(
            response_plan_id,
            number,
            count,
            kind,
            candidate,
            text=text,
            sticker_intent=sticker,
        )
        for number, (kind, text, sticker) in enumerate(pending, start=1)
    )


def _action(
    response_plan_id: UUID,
    sequence_number: int,
    sequence_count: int,
    kind: OutboundActionKind,
    candidate: ResponsePlanCandidate,
    *,
    text: str | None,
    sticker_intent: StickerIntent | None,
) -> OutboundActionSpec:
    key_material = f"{response_plan_id}:{sequence_number}:{kind.value}".encode()
    return OutboundActionSpec(
        sequence_number=sequence_number,
        sequence_count=sequence_count,
        kind=kind,
        idempotency_key=sha256(key_material).hexdigest(),
        text=text,
        reply_to_message_id=(
            candidate.reply_to_message_id if sequence_number == 1 else None
        ),
        mention_participant_ids=(
            tuple(candidate.mentions) if sequence_number == 1 else ()
        ),
        sticker_intent=sticker_intent,
    )


class ResponseTooLong(ValueError):
    """The logical response cannot be represented by the bounded sequence."""


def split_telegram_text(
    text: str,
    *,
    chunk_limit: int = TELEGRAM_TEXT_CHUNK_UTF16_LIMIT,
    logical_limit: int = TELEGRAM_LOGICAL_RESPONSE_UTF16_LIMIT,
    max_chunks: int = TELEGRAM_MAX_TEXT_CHUNKS,
) -> tuple[str, ...]:
    """Split plain text deterministically without changing its content."""

    if text == "":
        return ()
    total = utf16_length(text)
    if total > logical_limit:
        raise ResponseTooLong("response exceeds logical Telegram delivery limit")
    units = _graphemes(text)
    chunks: list[str] = []
    cursor = 0
    remaining_units = total
    while cursor < len(units):
        if len(chunks) >= max_chunks:
            raise ResponseTooLong("response exceeds maximum Telegram chunk count")
        end = cursor
        used = 0
        while end < len(units):
            cost = utf16_length(units[end])
            if used + cost > chunk_limit:
                break
            used += cost
            end += 1
        if end == cursor:
            raise ResponseTooLong("one grapheme exceeds Telegram chunk limit")
        if end == len(units):
            chunks.append("".join(units[cursor:end]))
            break

        remaining_slots = max_chunks - len(chunks) - 1
        minimum_used = max(1, remaining_units - remaining_slots * chunk_limit)
        window = "".join(units[cursor:end])
        split_chars = _preferred_boundary(window, minimum_used)
        if split_chars is None:
            split_end = end
        else:
            consumed = 0
            split_end = cursor
            for index in range(cursor, end):
                consumed += len(units[index])
                split_end = index + 1
                if consumed >= split_chars:
                    break
        chunk = "".join(units[cursor:split_end])
        chunks.append(chunk)
        remaining_units -= utf16_length(chunk)
        cursor = split_end
    if "".join(chunks) != text:
        raise AssertionError("Telegram splitter changed response content")
    return tuple(chunks)


def sequence_tail_blocked(
    predecessor_statuses: tuple[OutboundActionStatus, ...],
) -> bool:
    """Only a fully delivered prefix permits the next sequence action."""

    return any(
        status != OutboundActionStatus.DELIVERED for status in predecessor_statuses
    )


def _preferred_boundary(window: str, minimum_utf16: int) -> int | None:
    def valid_positions(delimiter: str) -> list[int]:
        positions: list[int] = []
        start = 0
        while True:
            found = window.find(delimiter, start)
            if found < 0:
                break
            position = found + len(delimiter)
            if utf16_length(window[:position]) >= minimum_utf16:
                positions.append(position)
            start = found + 1
        return positions

    for delimiter in ("\n\n", "\n"):
        positions = valid_positions(delimiter)
        if positions:
            return positions[-1]
    spaces = [
        index + 1
        for index, character in enumerate(window)
        if character.isspace() and utf16_length(window[: index + 1]) >= minimum_utf16
    ]
    return spaces[-1] if spaces else None


def _graphemes(text: str) -> tuple[str, ...]:
    clusters: list[str] = []
    for character in text:
        codepoint = ord(character)
        combining = bool(unicodedata.combining(character)) or unicodedata.category(
            character
        ) in {"Mc", "Me"}
        variation = 0xFE00 <= codepoint <= 0xFE0F
        modifier = 0x1F3FB <= codepoint <= 0x1F3FF
        regional = 0x1F1E6 <= codepoint <= 0x1F1FF
        if not clusters:
            clusters.append(character)
        elif (
            combining
            or variation
            or modifier
            or character == "\u200d"
            or clusters[-1].endswith("\u200d")
            or (
                regional
                and all(0x1F1E6 <= ord(item) <= 0x1F1FF for item in clusters[-1])
                and len(clusters[-1]) % 2 == 1
            )
        ):
            clusters[-1] += character
        else:
            clusters.append(character)
    return tuple(clusters)
