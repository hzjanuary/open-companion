"""Fenced source-scoped media state; every method closes its transaction."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.media import MediaError
from app.domain.ambient import ParticipationTrigger
from app.domain.media import MediaAttachment, MediaFailureReason, MediaKind, MediaStatus
from app.domain.persistence import (
    AssistantStatus,
    ConversationStatus,
    PlatformConnectionStatus,
    ResponseMode,
)
from app.domain.planning import PlanningJobStatus
from app.domain.provider_governance import ProviderOperation
from app.domain.summary import ConversationSummaryStatus, SummaryInvalidationReason
from app.infrastructure.database.governance import invalidate_export_packages
from app.infrastructure.database.models import (
    AssistantModel,
    ConversationModel,
    ConversationSummaryModel,
    MessageMediaModel,
    MessageModel,
    ParticipantModel,
    PlatformConnectionModel,
    ProviderUsageAttemptModel,
    ResponsePlanningJobModel,
)


@dataclass(frozen=True, slots=True)
class MediaWork:
    media_id: UUID
    message_id: UUID
    status: MediaStatus
    attachment: MediaAttachment = field(repr=False)
    caption: str | None = field(repr=False)
    lease_token: UUID | None = None
    failure_reason: MediaFailureReason | None = None


def redact_media_values(now: datetime) -> dict[str, object]:
    return {
        "status": MediaStatus.REDACTED,
        "failure_reason": MediaFailureReason.PRIVACY_CHANGED,
        "file_id": None,
        "file_unique_id": None,
        "caption": None,
        "mime_type": None,
        "file_size": None,
        "width": None,
        "height": None,
        "duration_seconds": None,
        "lease_token": None,
        "lease_expires_at": None,
        "redacted_at": now,
        "updated_at": now,
    }


class SqlAlchemyMediaRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        connection_id: UUID,
        retention_days: int,
        lease_seconds: int,
        transcript_limit: int,
    ) -> None:
        if not 1 <= retention_days <= 30 or not 1 <= transcript_limit <= 8000:
            raise ValueError("media repository bounds are invalid")
        self._sessions = session_factory
        self._connection_id = connection_id
        self._retention_days = retention_days
        self._lease_seconds = lease_seconds
        self._transcript_limit = transcript_limit

    async def claim(
        self,
        job_id: UUID,
        owner: str,
        attempt: int,
        *,
        now: datetime | None = None,
    ) -> MediaWork | None:
        current = now or datetime.now(UTC)
        async with self._sessions() as session, session.begin():
            scope = await self._scope(session, job_id, owner, attempt, current)
            if scope is None:
                return None
            job, message, conversation = scope
            media = await session.scalar(
                select(MessageMediaModel)
                .where(
                    MessageMediaModel.message_id == message.id,
                    MessageMediaModel.conversation_id == conversation.id,
                )
                .with_for_update()
            )
            if media is None or media.status == MediaStatus.REDACTED:
                return None
            if media.status in {
                MediaStatus.COMPLETE,
                MediaStatus.FAILED,
                MediaStatus.AMBIGUOUS,
            }:
                return _work(media)
            if (
                media.status == MediaStatus.PREPARING
                and media.lease_expires_at is not None
                and media.lease_expires_at > current
            ):
                return None
            possible_io = await session.scalar(
                select(ProviderUsageAttemptModel.id)
                .where(
                    ProviderUsageAttemptModel.planning_job_id == job.id,
                    ProviderUsageAttemptModel.operation
                    == ProviderOperation.MEDIA_TRANSCRIPTION,
                    ProviderUsageAttemptModel.request_count == 1,
                )
                .limit(1)
            )
            if media.kind != MediaKind.PHOTO and possible_io is not None:
                media.status = MediaStatus.AMBIGUOUS
                media.failure_reason = MediaFailureReason.AMBIGUOUS
                media.lease_token = None
                media.lease_expires_at = None
                media.completed_at = current
                return _work(media)
            media.status = MediaStatus.PREPARING
            media.failure_reason = None
            media.lease_token = uuid4()
            media.lease_expires_at = current + timedelta(seconds=self._lease_seconds)
            media.planning_attempt = attempt
            media.privacy_revision = conversation.memory_privacy_revision
            media.source_edited_at = message.edited_at
            job.lease_expires_at = media.lease_expires_at
            return _work(media)

    async def preflight(
        self,
        job_id: UUID,
        owner: str,
        attempt: int,
        token: UUID,
        *,
        now: datetime | None = None,
    ) -> bool:
        current = now or datetime.now(UTC)
        async with self._sessions() as session, session.begin():
            values = await self._fenced(session, job_id, owner, attempt, token, current)
            if values is None:
                return False
            job, _, _, media = values
            expires = current + timedelta(seconds=self._lease_seconds)
            job.lease_expires_at = expires
            media.lease_expires_at = expires
            return True

    async def finish_transcript(
        self,
        job_id: UUID,
        owner: str,
        attempt: int,
        token: UUID,
        transcript: str,
        *,
        now: datetime | None = None,
    ) -> bool:
        text = transcript.strip()
        if not text or len(text) > self._transcript_limit or "\x00" in text:
            raise MediaError(MediaFailureReason.INVALID_FORMAT)
        current = now or datetime.now(UTC)
        async with self._sessions() as session, session.begin():
            values = await self._fenced(session, job_id, owner, attempt, token, current)
            if values is None:
                return False
            _, message, conversation, media = values
            if media.kind not in {MediaKind.VOICE, MediaKind.AUDIO}:
                return False
            message.text = text
            message.metadata_ = {
                **message.metadata_,
                "content_provenance": f"{media.kind.value}_transcript",
            }
            media.status = MediaStatus.COMPLETE
            media.completed_at = current
            media.lease_token = None
            media.lease_expires_at = None
            conversation.memory_privacy_revision += 1
            assert message.participant_id is not None
            await invalidate_export_packages(
                session,
                scope="subject",
                participant_ids=[message.participant_id],
                reason="source_content_changed",
                now=current,
            )
            await session.execute(
                update(ConversationSummaryModel)
                .where(
                    ConversationSummaryModel.conversation_id == conversation.id,
                    ConversationSummaryModel.status
                    == ConversationSummaryStatus.COMPLETED,
                )
                .values(
                    status=ConversationSummaryStatus.INVALIDATED,
                    summary_text=None,
                    invalidated_at=current,
                    invalidation_reason=SummaryInvalidationReason.SOURCE_WINDOW_CHANGED.value,
                )
            )
            return True

    async def generation_preflight(
        self,
        job_id: UUID,
        owner: str,
        attempt: int,
        privacy_revision: int,
        *,
        media_token: UUID | None = None,
        now: datetime | None = None,
    ) -> bool:
        current = now or datetime.now(UTC)
        async with self._sessions() as session, session.begin():
            scope = await self._scope(session, job_id, owner, attempt, current)
            if scope is None:
                return False
            job, message, conversation = scope
            if conversation.memory_privacy_revision != privacy_revision:
                return False
            media = await session.scalar(
                select(MessageMediaModel)
                .where(
                    MessageMediaModel.message_id == message.id,
                    MessageMediaModel.conversation_id == conversation.id,
                )
                .with_for_update()
            )
            if media is None:
                return False
            if media.kind == MediaKind.PHOTO:
                if (
                    media.status != MediaStatus.PREPARING
                    or media_token is None
                    or media.lease_token != media_token
                    or media.planning_attempt != attempt
                    or media.lease_expires_at is None
                    or media.lease_expires_at <= current
                    or media.privacy_revision != privacy_revision
                ):
                    return False
                media.lease_expires_at = current + timedelta(
                    seconds=self._lease_seconds
                )
            elif media.status != MediaStatus.COMPLETE:
                return False
            job.lease_expires_at = current + timedelta(seconds=self._lease_seconds)
            return True

    async def fail(
        self,
        job_id: UUID,
        owner: str,
        attempt: int,
        token: UUID,
        reason: MediaFailureReason,
        *,
        now: datetime | None = None,
    ) -> bool:
        current = now or datetime.now(UTC)
        async with self._sessions() as session, session.begin():
            values = await self._fenced(session, job_id, owner, attempt, token, current)
            if values is None:
                return False
            media = values[3]
            media.status = (
                MediaStatus.AMBIGUOUS
                if reason == MediaFailureReason.AMBIGUOUS
                else MediaStatus.FAILED
            )
            media.failure_reason = reason
            media.completed_at = current
            media.lease_token = None
            media.lease_expires_at = None
            return True

    async def _scope(
        self,
        session: AsyncSession,
        job_id: UUID,
        owner: str,
        attempt: int,
        now: datetime,
    ) -> tuple[ResponsePlanningJobModel, MessageModel, ConversationModel] | None:
        job = await session.get(ResponsePlanningJobModel, job_id, with_for_update=True)
        if (
            job is None
            or job.status != PlanningJobStatus.LEASED
            or job.lease_owner != owner
            or job.attempt_count != attempt
            or job.lease_expires_at is None
            or job.lease_expires_at <= now
        ):
            return None
        row = (
            await session.execute(
                select(
                    MessageModel,
                    ConversationModel,
                    ParticipantModel,
                    PlatformConnectionModel,
                    AssistantModel,
                )
                .join(
                    ConversationModel,
                    MessageModel.conversation_id == ConversationModel.id,
                )
                .join(
                    ParticipantModel, MessageModel.participant_id == ParticipantModel.id
                )
                .join(
                    PlatformConnectionModel,
                    ConversationModel.platform_connection_id
                    == PlatformConnectionModel.id,
                )
                .join(
                    AssistantModel,
                    PlatformConnectionModel.assistant_id == AssistantModel.id,
                )
                .where(MessageModel.id == job.message_id)
                .with_for_update(of=[MessageModel, ConversationModel, ParticipantModel])
            )
        ).one_or_none()
        if row is None:
            return None
        message, conversation, participant, connection, assistant = row
        if (
            conversation.id != job.conversation_id
            or participant.conversation_id != conversation.id
            or connection.id != self._connection_id
            or conversation.status != ConversationStatus.ACTIVE
            or conversation.response_mode == ResponseMode.PAUSED
            or connection.status != PlatformConnectionStatus.ACTIVE
            or assistant.status != AssistantStatus.ACTIVE
            or participant.privacy_deleted_at is not None
            or message.content_redacted_at is not None
            or message.eligible is not True
            or job.trigger != ParticipationTrigger.ADDRESSED
            or message.platform_sent_at is None
            or message.platform_sent_at <= now - timedelta(days=self._retention_days)
            or message.edited_at is not None
        ):
            return None
        return job, message, conversation

    async def _fenced(
        self,
        session: AsyncSession,
        job_id: UUID,
        owner: str,
        attempt: int,
        token: UUID,
        now: datetime,
    ) -> (
        tuple[
            ResponsePlanningJobModel, MessageModel, ConversationModel, MessageMediaModel
        ]
        | None
    ):
        scope = await self._scope(session, job_id, owner, attempt, now)
        if scope is None:
            return None
        job, message, conversation = scope
        media = await session.scalar(
            select(MessageMediaModel)
            .where(
                MessageMediaModel.message_id == message.id,
                MessageMediaModel.conversation_id == conversation.id,
            )
            .with_for_update()
        )
        if (
            media is None
            or media.status != MediaStatus.PREPARING
            or media.lease_token != token
            or media.planning_attempt != attempt
            or media.lease_expires_at is None
            or media.lease_expires_at <= now
            or media.privacy_revision != conversation.memory_privacy_revision
            or media.source_edited_at != message.edited_at
        ):
            return None
        return job, message, conversation, media


def _work(media: MessageMediaModel) -> MediaWork:
    if media.file_id is None or media.file_unique_id is None or media.mime_type is None:
        raise MediaError(MediaFailureReason.UNAVAILABLE)
    return MediaWork(
        media.id,
        media.message_id,
        media.status,
        MediaAttachment(
            media.kind,
            media.file_id,
            media.file_unique_id,
            media.mime_type,
            media.file_size,
            media.width,
            media.height,
            media.duration_seconds,
        ),
        media.caption,
        media.lease_token,
        media.failure_reason,
    )
