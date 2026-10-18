"""Lease and deterministic response persistence for Telegram command jobs."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.outbound import compile_outbound_actions
from app.application.response_plan import ResponsePlanCandidate
from app.domain.persistence import (
    CommandAuthorizationOutcome,
    CommandJobStatus,
    ResponseMode,
)
from app.infrastructure.database.group_configuration import ConfigurationChange
from app.infrastructure.database.models import (
    AssistantModel,
    ConversationConfigurationRevisionModel,
    ConversationModel,
    MessageModel,
    OutboundActionModel,
    ParticipantModel,
    ParticipantPreferenceEventModel,
    ResponsePlanModel,
    TelegramCommandJobModel,
)
from app.infrastructure.database.personality import ensure_conversation_configuration


class SqlAlchemyCommandRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def claim(
        self, owner: str, limit: int, lease_seconds: int
    ) -> list[TelegramCommandJobModel]:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                jobs = list(
                    await session.scalars(
                        select(TelegramCommandJobModel)
                        .where(
                            or_(
                                (
                                    TelegramCommandJobModel.status
                                    == CommandJobStatus.PENDING
                                )
                                & (TelegramCommandJobModel.available_at <= now),
                                (
                                    TelegramCommandJobModel.status
                                    == CommandJobStatus.LEASED
                                )
                                & (TelegramCommandJobModel.lease_expires_at < now),
                            )
                        )
                        .order_by(
                            TelegramCommandJobModel.available_at,
                            TelegramCommandJobModel.created_at,
                            TelegramCommandJobModel.id,
                        )
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                )
                for job in jobs:
                    job.status = CommandJobStatus.LEASED
                    job.lease_owner = owner
                    job.lease_expires_at = now + timedelta(seconds=lease_seconds)
                    job.attempt_count += 1
                return jobs

    async def complete(
        self,
        job_id: UUID,
        owner: str,
        candidate: ResponsePlanCandidate,
        result_code: str,
        authorization: CommandAuthorizationOutcome | None = None,
        preference: tuple[bool | None, bool | None] | None = None,
        unchanged_candidate: ResponsePlanCandidate | None = None,
        governance_export_request_id: UUID | None = None,
    ) -> bool:
        """Atomically finalize a lease, optional preference change, and handoff."""

        async with self._session_factory() as session:
            async with session.begin():
                job = await session.get(
                    TelegramCommandJobModel, job_id, with_for_update=True
                )
                if (
                    job is None
                    or job.status != CommandJobStatus.LEASED
                    or job.lease_owner != owner
                ):
                    return False
                if preference is not None:
                    participant = await session.get(
                        ParticipantModel, job.participant_id
                    )
                    if participant is None:
                        return False
                    mention, teasing = preference
                    new_mention = (
                        participant.mention_allowed if mention is None else mention
                    )
                    new_teasing = (
                        participant.teasing_allowed if teasing is None else teasing
                    )
                    if (new_mention, new_teasing) != (
                        participant.mention_allowed,
                        participant.teasing_allowed,
                    ):
                        session.add(
                            ParticipantPreferenceEventModel(
                                participant_id=participant.id,
                                command_job_id=job.id,
                                previous_mention_allowed=participant.mention_allowed,
                                mention_allowed=new_mention,
                                previous_teasing_allowed=participant.teasing_allowed,
                                teasing_allowed=new_teasing,
                                source="telegram_command",
                            )
                        )
                        participant.mention_allowed = new_mention
                        participant.teasing_allowed = new_teasing
                    elif unchanged_candidate is not None:
                        candidate = unchanged_candidate
                        result_code = "unchanged"
                plan = ResponsePlanModel(
                    command_job_id=job.id,
                    should_respond=candidate.should_respond,
                    reason_code=candidate.reason_code,
                    text=candidate.text,
                    reply_to_message_id=candidate.reply_to_message_id,
                    mention_participant_ids=[],
                    sticker_intent=None,
                    confidence=candidate.confidence,
                    language=candidate.language,
                    prompt_version="telegram-command-v1",
                    schema_version="response-plan-v1",
                )
                session.add(plan)
                await session.flush()
                source_message = await session.get(MessageModel, job.message_id)
                for action in compile_outbound_actions(plan.id, candidate):
                    session.add(
                        OutboundActionModel(
                            response_plan_id=plan.id,
                            conversation_id=job.conversation_id,
                            sequence_number=action.sequence_number,
                            sequence_count=action.sequence_count,
                            idempotency_key=action.idempotency_key,
                            kind=action.kind,
                            reply_to_message_id=action.reply_to_message_id,
                            message_thread_id=(
                                source_message.platform_thread_id
                                if source_message is not None
                                else None
                            ),
                            mention_participant_ids=[],
                            text=action.text,
                            sticker_intent=None,
                            governance_export_request_id=governance_export_request_id,
                        )
                    )
                job.status = CommandJobStatus.COMPLETED
                job.result_code = result_code
                job.authorization_outcome = authorization
                job.completed_at = datetime.now(UTC)
                job.lease_owner = None
                job.lease_expires_at = None
                return True

    async def retry(self, job_id: UUID, owner: str, delay_seconds: float) -> bool:
        async with self._session_factory() as session:
            async with session.begin():
                job = await session.get(
                    TelegramCommandJobModel, job_id, with_for_update=True
                )
                if (
                    job is None
                    or job.status != CommandJobStatus.LEASED
                    or job.lease_owner != owner
                ):
                    return False
                job.status = CommandJobStatus.PENDING
                job.available_at = datetime.now(UTC) + timedelta(seconds=delay_seconds)
                job.authorization_outcome = (
                    CommandAuthorizationOutcome.RETRYABLE_FAILURE
                )
                job.lease_owner = None
                job.lease_expires_at = None
                return True

    async def complete_configuration(
        self,
        job_id: UUID,
        owner: str,
        assistant_id: UUID,
        change: ConfigurationChange,
        success_candidate: ResponsePlanCandidate,
        authorization: CommandAuthorizationOutcome | None,
        *,
        expected_revision: int | None,
        unchanged_candidate: ResponsePlanCandidate,
        conflict_candidate: ResponsePlanCandidate,
        resume: bool = False,
    ) -> bool:
        """Finalize a change against the pre-authorization revision safely."""

        async with self._session_factory() as session:
            async with session.begin():
                job = await session.get(
                    TelegramCommandJobModel, job_id, with_for_update=True
                )
                if (
                    job is None
                    or job.status != CommandJobStatus.LEASED
                    or job.lease_owner != owner
                ):
                    return False
                conversation = await session.get(
                    ConversationModel, job.conversation_id, with_for_update=True
                )
                assistant = await session.get(AssistantModel, assistant_id)
                if conversation is None or assistant is None:
                    return False
                current = await ensure_conversation_configuration(
                    session, assistant, conversation
                )
                response_mode = change.response_mode or current.response_mode
                if resume:
                    previous = await session.scalar(
                        select(ConversationConfigurationRevisionModel.response_mode)
                        .where(
                            ConversationConfigurationRevisionModel.conversation_id
                            == conversation.id,
                            ConversationConfigurationRevisionModel.response_mode
                            != ResponseMode.PAUSED,
                        )
                        .order_by(
                            ConversationConfigurationRevisionModel.revision_number.desc()
                        )
                        .limit(1)
                    )
                    response_mode = previous or ResponseMode.MENTION_ONLY
                stickers_enabled = (
                    current.stickers_enabled
                    if change.stickers_enabled is None
                    else change.stickers_enabled
                )
                profile_version_id = (
                    change.profile_version_id or current.personality_profile_version_id
                )
                same = (
                    response_mode == current.response_mode
                    and stickers_enabled == current.stickers_enabled
                    and (change.ambient_frequency or current.ambient_frequency)
                    == current.ambient_frequency
                    and profile_version_id == current.personality_profile_version_id
                )
                if same:
                    return await self.complete_in_session(
                        session,
                        job,
                        unchanged_candidate,
                        "unchanged",
                        authorization,
                    )
                if (
                    expected_revision is not None
                    and expected_revision != current.revision_number
                ):
                    return await self.complete_in_session(
                        session,
                        job,
                        conflict_candidate,
                        "conflict",
                        authorization,
                    )
                revision = ConversationConfigurationRevisionModel(
                    conversation_id=conversation.id,
                    revision_number=current.revision_number + 1,
                    personality_profile_version_id=profile_version_id,
                    response_mode=response_mode,
                    stickers_enabled=stickers_enabled,
                    ambient_frequency=change.ambient_frequency
                    or current.ambient_frequency,
                    default_length=current.default_length,
                    formality=current.formality,
                    humor_level=current.humor_level,
                    teasing_level=current.teasing_level,
                    emoji_frequency=current.emoji_frequency,
                    sticker_frequency=current.sticker_frequency,
                    use_member_names=current.use_member_names,
                    ask_follow_up_questions=current.ask_follow_up_questions,
                    change_source=change.source,
                    reason_code=change.reason_code,
                    actor_participant_id=change.actor_participant_id,
                )
                session.add(revision)
                await session.flush()
                conversation.current_configuration_revision_id = revision.id
                conversation.response_mode = response_mode
                return await self.complete_in_session(
                    session, job, success_candidate, "success", authorization
                )

    async def complete_in_session(
        self,
        session: AsyncSession,
        job: TelegramCommandJobModel,
        candidate: ResponsePlanCandidate,
        result_code: str,
        authorization: CommandAuthorizationOutcome | None,
    ) -> bool:
        """Persist the sole command response plan while the lease is locked."""
        plan = ResponsePlanModel(
            command_job_id=job.id,
            should_respond=candidate.should_respond,
            reason_code=candidate.reason_code,
            text=candidate.text,
            reply_to_message_id=candidate.reply_to_message_id,
            mention_participant_ids=[],
            sticker_intent=None,
            confidence=candidate.confidence,
            language=candidate.language,
            prompt_version="telegram-command-v1",
            schema_version="response-plan-v1",
        )
        session.add(plan)
        await session.flush()
        source_message = await session.get(MessageModel, job.message_id)
        for action in compile_outbound_actions(plan.id, candidate):
            session.add(
                OutboundActionModel(
                    response_plan_id=plan.id,
                    conversation_id=job.conversation_id,
                    sequence_number=action.sequence_number,
                    sequence_count=action.sequence_count,
                    idempotency_key=action.idempotency_key,
                    kind=action.kind,
                    reply_to_message_id=action.reply_to_message_id,
                    message_thread_id=source_message.platform_thread_id
                    if source_message
                    else None,
                    mention_participant_ids=[],
                    text=action.text,
                    sticker_intent=None,
                )
            )
        job.status = CommandJobStatus.COMPLETED
        job.result_code = result_code
        job.authorization_outcome = authorization
        job.completed_at = datetime.now(UTC)
        job.lease_owner = None
        job.lease_expires_at = None
        return True
