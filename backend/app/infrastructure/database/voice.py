"""Durable authority and artifact lifecycle for explicit Telegram voice playback."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from typing import TypeGuard
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.text_to_speech import TextToSpeechResult
from app.domain.ambient import ParticipationTrigger
from app.domain.outbound import OutboundActionKind, OutboundActionStatus
from app.domain.persistence import (
    CommandJobStatus,
    ConversationStatus,
    MessageDirection,
    MessageType,
    Platform,
)
from app.domain.planning import PlanReasonCode
from app.domain.provider_governance import (
    ProviderAttemptOutcome,
    ProviderAttemptState,
)
from app.domain.voice import (
    VOICE_ARTIFACT_HARD_RETENTION_DAYS,
    VOICE_SOURCE_MAX_CHARACTERS,
    VoiceArtifactStatus,
    VoiceFailureReason,
    VoiceGenerationStatus,
)
from app.infrastructure.database.models import (
    ConversationModel,
    GeneratedVoiceArtifactModel,
    MessageModel,
    OutboundActionModel,
    ParticipantModel,
    ProviderUsageAttemptModel,
    ResponsePlanModel,
    ResponsePlanningJobModel,
    TelegramCommandJobModel,
    TelegramVoiceGenerationJobModel,
)
from app.infrastructure.database.tenancy import conversation_authority


class VoicePreparationOutcome(StrEnum):
    ACCEPTED = "accepted"
    TARGET_UNAVAILABLE = "target_unavailable"
    TOO_LONG = "too_long"
    GENERATION_UNCERTAIN = "generation_uncertain"
    TERMINAL = "terminal"


@dataclass(frozen=True, slots=True)
class VoicePreparation:
    outcome: VoicePreparationOutcome
    job_id: UUID | None = None
    source_text: str | None = None
    participant_id: UUID | None = None


class SqlAlchemyVoiceRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def prepare(
        self, command_job_id: UUID, owner: str, lease_seconds: int
    ) -> VoicePreparation:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                command = await session.get(
                    TelegramCommandJobModel, command_job_id, with_for_update=True
                )
                if (
                    command is None
                    or command.status != CommandJobStatus.LEASED
                    or command.lease_owner != owner
                    or command.command_name != "voice"
                ):
                    return VoicePreparation(VoicePreparationOutcome.TARGET_UNAVAILABLE)
                existing = await session.scalar(
                    select(TelegramVoiceGenerationJobModel)
                    .where(TelegramVoiceGenerationJobModel.command_job_id == command.id)
                    .with_for_update()
                )
                if existing is not None:
                    if existing.status in {
                        VoiceGenerationStatus.COMPLETED,
                        VoiceGenerationStatus.FAILED,
                        VoiceGenerationStatus.STALE,
                    }:
                        return VoicePreparation(VoicePreparationOutcome.TERMINAL)
                    attempt = (
                        await session.get(
                            ProviderUsageAttemptModel, existing.provider_attempt_id
                        )
                        if existing.provider_attempt_id is not None
                        else None
                    )
                    if existing.io_started_at is not None or (
                        attempt is not None
                        and attempt.state
                        in {
                            ProviderAttemptState.IO_STARTED,
                            ProviderAttemptState.IO_COMPLETE,
                            ProviderAttemptState.IO_POSSIBLE,
                        }
                    ):
                        existing.status = VoiceGenerationStatus.IO_POSSIBLE
                        existing.failure_reason = VoiceFailureReason.PROVIDER_UNCERTAIN
                        existing.completed_at = now
                        existing.lease_owner = None
                        existing.lease_expires_at = None
                        return VoicePreparation(
                            VoicePreparationOutcome.GENERATION_UNCERTAIN,
                            existing.id,
                        )
                    current_text = await self._current_source(
                        session, command, existing
                    )
                    if current_text is None:
                        existing.status = VoiceGenerationStatus.STALE
                        existing.failure_reason = VoiceFailureReason.STALE_AUTHORITY
                        existing.completed_at = now
                        existing.lease_owner = None
                        existing.lease_expires_at = None
                        return VoicePreparation(
                            VoicePreparationOutcome.TARGET_UNAVAILABLE
                        )
                    existing.status = VoiceGenerationStatus.LEASED
                    existing.lease_owner = owner
                    existing.lease_expires_at = now + timedelta(seconds=lease_seconds)
                    return VoicePreparation(
                        VoicePreparationOutcome.ACCEPTED,
                        existing.id,
                        current_text,
                        command.participant_id,
                    )

                target_resolution = await self._resolve_target(session, command)
                if target_resolution is None:
                    return VoicePreparation(VoicePreparationOutcome.TARGET_UNAVAILABLE)
                plan, text, conversation, tenant_id, assistant_id = target_resolution
                if len(text) > VOICE_SOURCE_MAX_CHARACTERS:
                    return VoicePreparation(VoicePreparationOutcome.TOO_LONG)
                voice_job = TelegramVoiceGenerationJobModel(
                    command_job_id=command.id,
                    tenant_id=tenant_id,
                    assistant_id=assistant_id,
                    connection_id=conversation.platform_connection_id,
                    conversation_id=conversation.id,
                    source_response_plan_id=plan.id,
                    source_sha256=sha256(text.encode("utf-8")).hexdigest(),
                    source_character_count=len(text),
                    privacy_revision=conversation.memory_privacy_revision,
                    status=VoiceGenerationStatus.LEASED,
                    lease_owner=owner,
                    lease_expires_at=now + timedelta(seconds=lease_seconds),
                    attempt_count=1,
                )
                session.add(voice_job)
                await session.flush()
                return VoicePreparation(
                    VoicePreparationOutcome.ACCEPTED,
                    voice_job.id,
                    text,
                    command.participant_id,
                )

    async def bind_provider_attempt(
        self, job_id: UUID, owner: str, attempt_id: UUID
    ) -> bool:
        async with self._session_factory() as session:
            async with session.begin():
                job = await session.get(
                    TelegramVoiceGenerationJobModel, job_id, with_for_update=True
                )
                if not _owns_job(job, owner):
                    return False
                if job.provider_attempt_id is not None:
                    return job.provider_attempt_id == attempt_id
                job.provider_attempt_id = attempt_id
                return True

    async def mark_io_started(self, job_id: UUID, owner: str) -> bool:
        async with self._session_factory() as session:
            async with session.begin():
                job = await session.get(
                    TelegramVoiceGenerationJobModel, job_id, with_for_update=True
                )
                if not _owns_job(job, owner) or job.provider_attempt_id is None:
                    return False
                attempt = await session.get(
                    ProviderUsageAttemptModel, job.provider_attempt_id
                )
                if attempt is None or attempt.state != ProviderAttemptState.IO_STARTED:
                    return False
                job.io_started_at = datetime.now(UTC)
                return True

    async def finish_failure(
        self,
        job_id: UUID,
        owner: str,
        *,
        reason: VoiceFailureReason,
        uncertain: bool = False,
    ) -> bool:
        async with self._session_factory() as session:
            async with session.begin():
                job = await session.get(
                    TelegramVoiceGenerationJobModel, job_id, with_for_update=True
                )
                if not _owns_job(job, owner):
                    return False
                job.status = (
                    VoiceGenerationStatus.IO_POSSIBLE
                    if uncertain
                    else VoiceGenerationStatus.FAILED
                )
                job.failure_reason = reason
                job.completed_at = datetime.now(UTC)
                job.lease_owner = None
                job.lease_expires_at = None
                return True

    async def activate(
        self,
        job_id: UUID,
        owner: str,
        result: TextToSpeechResult,
        *,
        language: str,
    ) -> bool:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                job = await session.get(
                    TelegramVoiceGenerationJobModel, job_id, with_for_update=True
                )
                if not _owns_job(job, owner) or job.provider_attempt_id is None:
                    return False
                command = await session.get(
                    TelegramCommandJobModel, job.command_job_id, with_for_update=True
                )
                attempt = await session.get(
                    ProviderUsageAttemptModel, job.provider_attempt_id
                )
                source = (
                    await self._current_source(session, command, job)
                    if command is not None
                    else None
                )
                if (
                    source is None
                    or command is None
                    or command.status != CommandJobStatus.LEASED
                    or command.lease_owner != owner
                    or attempt is None
                    or attempt.state != ProviderAttemptState.IO_COMPLETE
                    or attempt.provider_outcome != ProviderAttemptOutcome.SUCCESS
                ):
                    if job.status == VoiceGenerationStatus.LEASED:
                        job.status = VoiceGenerationStatus.STALE
                        job.failure_reason = VoiceFailureReason.STALE_AUTHORITY
                        job.completed_at = now
                        job.lease_owner = None
                        job.lease_expires_at = None
                    return False
                artifact = GeneratedVoiceArtifactModel(
                    generation_job_id=job.id,
                    tenant_id=job.tenant_id,
                    assistant_id=job.assistant_id,
                    connection_id=job.connection_id,
                    conversation_id=job.conversation_id,
                    source_response_plan_id=job.source_response_plan_id,
                    format=result.format,
                    mime_type=result.mime_type,
                    audio_bytes=result.audio_bytes,
                    byte_size=len(result.audio_bytes),
                    sha256=sha256(result.audio_bytes).hexdigest(),
                    status=VoiceArtifactStatus.READY,
                    expires_at=now + timedelta(days=VOICE_ARTIFACT_HARD_RETENTION_DAYS),
                )
                session.add(artifact)
                await session.flush()
                plan = ResponsePlanModel(
                    command_job_id=command.id,
                    should_respond=True,
                    reason_code=PlanReasonCode.ACKNOWLEDGEMENT,
                    text=None,
                    reply_to_message_id=command.message_id,
                    mention_participant_ids=[],
                    sticker_intent=None,
                    confidence=1,
                    language=language,
                    prompt_version="telegram-command-v1",
                    schema_version="response-plan-v1",
                )
                session.add(plan)
                await session.flush()
                command_message = await session.get(MessageModel, command.message_id)
                action_key = sha256(f"{plan.id}:1:voice".encode()).hexdigest()
                session.add(
                    OutboundActionModel(
                        response_plan_id=plan.id,
                        conversation_id=job.conversation_id,
                        sequence_number=1,
                        sequence_count=1,
                        idempotency_key=action_key,
                        kind=OutboundActionKind.VOICE,
                        origin=ParticipationTrigger.ADDRESSED,
                        reply_to_message_id=command.message_id,
                        message_thread_id=(
                            command_message.platform_thread_id
                            if command_message is not None
                            else None
                        ),
                        mention_participant_ids=[],
                        text=None,
                        sticker_intent=None,
                        generated_voice_artifact_id=artifact.id,
                    )
                )
                job.status = VoiceGenerationStatus.COMPLETED
                job.completed_at = now
                job.lease_owner = None
                job.lease_expires_at = None
                command.status = CommandJobStatus.COMPLETED
                command.result_code = "voice_accepted"
                command.completed_at = now
                command.lease_owner = None
                command.lease_expires_at = None
                return True

    async def _resolve_target(
        self, session: AsyncSession, command: TelegramCommandJobModel
    ) -> tuple[ResponsePlanModel, str, ConversationModel, UUID, UUID] | None:
        command_message = await session.get(MessageModel, command.message_id)
        authority_row = await conversation_authority(session, command.conversation_id)
        participant = await session.get(ParticipantModel, command.participant_id)
        if authority_row is None:
            return None
        conversation, authority = authority_row
        if (
            command_message is None
            or command_message.conversation_id != conversation.id
            or command_message.reply_to_message_id is None
            or command_message.content_redacted_at is not None
            or participant is None
            or participant.conversation_id != conversation.id
            or participant.privacy_deleted_at is not None
            or not authority.permits_external_io
            or authority.connection.platform != Platform.TELEGRAM
            or conversation.status != ConversationStatus.ACTIVE
        ):
            return None
        target = await session.get(MessageModel, command_message.reply_to_message_id)
        if (
            target is None
            or target.conversation_id != conversation.id
            or target.direction != MessageDirection.OUTGOING
            or target.message_type != MessageType.TEXT
            or target.content_redacted_at is not None
        ):
            return None
        action = await self._canonical_action(session, target)
        if action is None or action.conversation_id != conversation.id:
            return None
        plan = await session.get(ResponsePlanModel, action.response_plan_id)
        planning_job = (
            await session.get(ResponsePlanningJobModel, plan.planning_job_id)
            if plan is not None and plan.planning_job_id is not None
            else None
        )
        if (
            plan is None
            or planning_job is None
            or planning_job.conversation_id != conversation.id
            or not plan.should_respond
            or plan.content_redacted_at is not None
            or plan.text is None
            or not plan.text
        ):
            return None
        uncertain = await session.scalar(
            select(OutboundActionModel.id).where(
                OutboundActionModel.response_plan_id == plan.id,
                OutboundActionModel.status == OutboundActionStatus.DELIVERY_UNKNOWN,
            )
        )
        if uncertain is not None:
            return None
        return (
            plan,
            plan.text,
            conversation,
            authority.tenant.id,
            authority.assistant.id,
        )

    async def _current_source(
        self,
        session: AsyncSession,
        command: TelegramCommandJobModel,
        job: TelegramVoiceGenerationJobModel,
    ) -> str | None:
        if (
            command.id != job.command_job_id
            or command.conversation_id != job.conversation_id
        ):
            return None
        resolved = await self._resolve_target(session, command)
        if resolved is None:
            return None
        plan, text, conversation, tenant_id, assistant_id = resolved
        if (
            plan.id != job.source_response_plan_id
            or tenant_id != job.tenant_id
            or assistant_id != job.assistant_id
            or conversation.platform_connection_id != job.connection_id
            or conversation.memory_privacy_revision != job.privacy_revision
            or len(text) != job.source_character_count
            or sha256(text.encode("utf-8")).hexdigest() != job.source_sha256
        ):
            return None
        return text

    async def _canonical_action(
        self, session: AsyncSession, target: MessageModel
    ) -> OutboundActionModel | None:
        ambiguous = await session.scalar(
            select(OutboundActionModel.id).where(
                OutboundActionModel.edit_target_message_id == target.id,
                OutboundActionModel.status == OutboundActionStatus.DELIVERY_UNKNOWN,
            )
        )
        if ambiguous is not None:
            return None
        action = await session.scalar(
            select(OutboundActionModel)
            .where(
                OutboundActionModel.edit_target_message_id == target.id,
                OutboundActionModel.kind == OutboundActionKind.EDIT_TEXT,
                OutboundActionModel.status == OutboundActionStatus.DELIVERED,
            )
            .order_by(
                OutboundActionModel.created_at.desc(), OutboundActionModel.id.desc()
            )
            .limit(1)
        )
        if action is None and target.outbound_action_id is not None:
            action = await session.get(OutboundActionModel, target.outbound_action_id)
        if (
            action is None
            or action.status != OutboundActionStatus.DELIVERED
            or action.kind
            not in {OutboundActionKind.TEXT, OutboundActionKind.EDIT_TEXT}
            or action.payload_redacted_at is not None
        ):
            return None
        return action


def _owns_job(job: object, owner: str) -> TypeGuard[TelegramVoiceGenerationJobModel]:
    return bool(
        isinstance(job, TelegramVoiceGenerationJobModel)
        and job.status == VoiceGenerationStatus.LEASED
        and job.lease_owner == owner
        and job.lease_expires_at is not None
        and job.lease_expires_at > datetime.now(UTC)
    )
