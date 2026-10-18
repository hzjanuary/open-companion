"""Durable, bounded summary source selection, leases, and finalization."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Select, and_, exists, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.summary import (
    SummarySourceMessage,
    SummarySourceWindow,
    build_source_window,
)
from app.domain.persistence import MessageDirection, MessageType
from app.domain.planning import ProviderErrorCategory, ProviderId
from app.domain.summary import (
    SUMMARY_PROMPT_VERSION,
    SUMMARY_SCHEMA_VERSION,
    ConversationSummaryStatus,
)
from app.infrastructure.database.models import (
    ConversationModel,
    ConversationSummaryJobModel,
    ConversationSummaryModel,
    MessageModel,
    ParticipantModel,
    TelegramCommandJobModel,
)


class SqlAlchemySummaryRepository:
    """Use raw retained incoming text once; summaries are never source material."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def schedule_available(
        self, *, retention_days: int, minimum: int, maximum: int
    ) -> int:
        """Create idempotent jobs for the next unsummarized window of each scope."""
        scheduled = 0
        async with self._session_factory() as session:
            scopes = list(
                (
                    await session.execute(
                        select(ConversationModel.id, MessageModel.platform_thread_id)
                        .join(
                            MessageModel,
                            MessageModel.conversation_id == ConversationModel.id,
                        )
                        .where(
                            MessageModel.direction == MessageDirection.INCOMING,
                            MessageModel.message_type == MessageType.TEXT,
                            MessageModel.text.is_not(None),
                            MessageModel.content_redacted_at.is_(None),
                            ~exists(
                                select(TelegramCommandJobModel.id).where(
                                    TelegramCommandJobModel.message_id
                                    == MessageModel.id,
                                    TelegramCommandJobModel.command_name == "feedback",
                                )
                            ),
                        )
                        .distinct()
                    )
                ).all()
            )
            for conversation_id, thread_id in scopes:
                window = await self._next_window(
                    session, conversation_id, thread_id, retention_days, maximum
                )
                if window is None or window.source_count < minimum:
                    continue
                result = await session.execute(
                    insert(ConversationSummaryJobModel)
                    .values(
                        conversation_id=conversation_id,
                        platform_thread_id=thread_id,
                        schema_version=SUMMARY_SCHEMA_VERSION,
                        prompt_version=SUMMARY_PROMPT_VERSION,
                        source_first_message_id=window.first_message_id,
                        source_last_message_id=window.last_message_id,
                        source_started_at=window.started_at,
                        source_ended_at=window.ended_at,
                        source_count=window.source_count,
                        source_window_hash=window.source_window_hash,
                        expires_at=window.expires_at,
                        status=ConversationSummaryStatus.PENDING,
                    )
                    .on_conflict_do_nothing(
                        index_elements=(
                            "conversation_id",
                            "source_window_hash",
                            "schema_version",
                        )
                    )
                    .returning(ConversationSummaryJobModel.id)
                )
                if result.scalar_one_or_none() is not None:
                    scheduled += 1
            await session.commit()
        return scheduled

    async def claim(
        self, owner: str, limit: int, lease_seconds: int
    ) -> list[ConversationSummaryJobModel]:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                jobs = list(
                    await session.scalars(
                        select(ConversationSummaryJobModel)
                        .where(
                            or_(
                                and_(
                                    ConversationSummaryJobModel.status
                                    == ConversationSummaryStatus.PENDING,
                                    ConversationSummaryJobModel.available_at <= now,
                                ),
                                and_(
                                    ConversationSummaryJobModel.status
                                    == ConversationSummaryStatus.LEASED,
                                    ConversationSummaryJobModel.lease_expires_at < now,
                                ),
                            )
                        )
                        .order_by(
                            ConversationSummaryJobModel.available_at,
                            ConversationSummaryJobModel.created_at,
                            ConversationSummaryJobModel.id,
                        )
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                )
                for job in jobs:
                    job.status = ConversationSummaryStatus.LEASED
                    job.lease_owner = owner
                    job.lease_expires_at = now + timedelta(seconds=lease_seconds)
                    job.attempt_count += 1
                return jobs

    async def source_for_job(
        self, job: ConversationSummaryJobModel, retention_days: int
    ) -> SummarySourceWindow | None:
        async with self._session_factory() as session:
            window = await self._window_for_range(
                session,
                job.conversation_id,
                job.platform_thread_id,
                job.source_started_at,
                job.source_ended_at,
                retention_days,
            )
        if window is None or (
            window.source_window_hash != job.source_window_hash
            or window.source_count != job.source_count
            or window.first_message_id != job.source_first_message_id
            or window.last_message_id != job.source_last_message_id
            or window.expires_at <= datetime.now(UTC)
        ):
            return None
        return window

    async def complete(
        self,
        job_id: UUID,
        owner: str,
        summary: str | None,
        provider: ProviderId | None,
        model: str | None,
        error: ProviderErrorCategory | None = None,
    ) -> bool:
        async with self._session_factory() as session:
            async with session.begin():
                job = await session.get(
                    ConversationSummaryJobModel, job_id, with_for_update=True
                )
                if (
                    job is None
                    or job.status != ConversationSummaryStatus.LEASED
                    or job.lease_owner != owner
                ):
                    return False
                now = datetime.now(UTC)
                job.lease_owner = None
                job.lease_expires_at = None
                job.completed_at = now
                job.last_error_category = error
                if summary is None or job.expires_at <= now:
                    job.status = (
                        ConversationSummaryStatus.FAILED
                        if error
                        else ConversationSummaryStatus.EXPIRED
                    )
                    return True
                await session.execute(
                    insert(ConversationSummaryModel)
                    .values(
                        conversation_id=job.conversation_id,
                        platform_thread_id=job.platform_thread_id,
                        schema_version=job.schema_version,
                        prompt_version=job.prompt_version,
                        provider=provider,
                        model=model,
                        source_first_message_id=job.source_first_message_id,
                        source_last_message_id=job.source_last_message_id,
                        source_started_at=job.source_started_at,
                        source_ended_at=job.source_ended_at,
                        source_count=job.source_count,
                        source_window_hash=job.source_window_hash,
                        summary_text=summary,
                        status=ConversationSummaryStatus.COMPLETED,
                        expires_at=job.expires_at,
                    )
                    .on_conflict_do_nothing(
                        index_elements=(
                            "conversation_id",
                            "source_window_hash",
                            "schema_version",
                        )
                    )
                )
                job.status = ConversationSummaryStatus.COMPLETED
                return True

    async def release(
        self,
        job_id: UUID,
        owner: str,
        error: ProviderErrorCategory | None,
        retry_seconds: int = 5,
        max_attempts: int | None = None,
    ) -> bool:
        async with self._session_factory() as session:
            async with session.begin():
                job = await session.get(
                    ConversationSummaryJobModel, job_id, with_for_update=True
                )
                if (
                    job is None
                    or job.status != ConversationSummaryStatus.LEASED
                    or job.lease_owner != owner
                ):
                    return False
                job.status = (
                    ConversationSummaryStatus.FAILED
                    if max_attempts is not None and job.attempt_count >= max_attempts
                    else ConversationSummaryStatus.PENDING
                )
                job.available_at = datetime.now(UTC) + timedelta(seconds=retry_seconds)
                job.lease_owner = None
                job.lease_expires_at = None
                job.last_error_category = error
                return True

    async def _next_window(
        self,
        session: AsyncSession,
        conversation_id: UUID,
        thread_id: str | None,
        retention_days: int,
        maximum: int,
    ) -> SummarySourceWindow | None:
        previous_end = await session.scalar(
            select(ConversationSummaryModel.source_ended_at)
            .where(
                ConversationSummaryModel.conversation_id == conversation_id,
                ConversationSummaryModel.platform_thread_id.is_not_distinct_from(
                    thread_id
                ),
                ConversationSummaryModel.status == ConversationSummaryStatus.COMPLETED,
            )
            .order_by(ConversationSummaryModel.source_ended_at.desc())
            .limit(1)
        )
        statement = self._source_statement(conversation_id, thread_id)
        if previous_end is not None:
            statement = statement.where(MessageModel.platform_sent_at > previous_end)
        messages = tuple(
            await session.scalars(
                statement.order_by(
                    MessageModel.platform_sent_at, MessageModel.id
                ).limit(maximum)
            )
        )
        return self._build(conversation_id, messages, retention_days)

    async def _window_for_range(
        self,
        session: AsyncSession,
        conversation_id: UUID,
        thread_id: str | None,
        start: datetime,
        end: datetime,
        retention_days: int,
    ) -> SummarySourceWindow | None:
        messages = tuple(
            await session.scalars(
                self._source_statement(conversation_id, thread_id)
                .where(
                    MessageModel.platform_sent_at >= start,
                    MessageModel.platform_sent_at <= end,
                )
                .order_by(MessageModel.platform_sent_at, MessageModel.id)
            )
        )
        return self._build(conversation_id, messages, retention_days)

    @staticmethod
    def _source_statement(
        conversation_id: UUID, thread_id: str | None
    ) -> Select[tuple[MessageModel]]:
        return (
            select(MessageModel)
            .join(ParticipantModel, MessageModel.participant_id == ParticipantModel.id)
            .where(
                MessageModel.conversation_id == conversation_id,
                MessageModel.platform_thread_id.is_not_distinct_from(thread_id),
                MessageModel.direction == MessageDirection.INCOMING,
                MessageModel.message_type == MessageType.TEXT,
                MessageModel.text.is_not(None),
                MessageModel.content_redacted_at.is_(None),
                ParticipantModel.privacy_deleted_at.is_(None),
                ~exists(
                    select(TelegramCommandJobModel.id).where(
                        TelegramCommandJobModel.message_id == MessageModel.id,
                        TelegramCommandJobModel.command_name == "feedback",
                    )
                ),
            )
        )

    @staticmethod
    def _build(
        conversation_id: UUID, messages: tuple[MessageModel, ...], retention_days: int
    ) -> SummarySourceWindow | None:
        if not messages:
            return None
        source = tuple(
            SummarySourceMessage(item.id, item.platform_sent_at, item.text)
            for item in messages
            if item.platform_sent_at is not None and item.text is not None
        )
        return (
            build_source_window(conversation_id, source, retention_days)
            if source
            else None
        )
