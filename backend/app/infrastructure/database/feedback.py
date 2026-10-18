"""Atomic authority resolution and mutation for explicit conversation feedback."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.response_plan import ResponsePlanCandidate
from app.domain.feedback import MAX_FEEDBACK_REVISIONS, FeedbackOutcome, FeedbackValue
from app.domain.outbound import OutboundActionKind, OutboundActionStatus
from app.domain.persistence import (
    CommandJobStatus,
    ConversationStatus,
    MessageDirection,
    MessageType,
    Platform,
)
from app.infrastructure.database.commands import SqlAlchemyCommandRepository
from app.infrastructure.database.models import (
    ConversationFeedbackEventModel,
    ConversationFeedbackModel,
    GeneratedVoiceArtifactModel,
    MessageModel,
    OutboundActionModel,
    ParticipantModel,
    ResponsePlanModel,
    ResponsePlanningJobModel,
    TelegramCommandJobModel,
)
from app.infrastructure.database.tenancy import conversation_authority


@dataclass(frozen=True, slots=True)
class FeedbackTarget:
    tenant_id: UUID
    assistant_id: UUID
    connection_id: UUID
    conversation_id: UUID
    response_plan_id: UUID
    participant_id: UUID
    target_message_id: UUID
    target_outbound_action_id: UUID


class SqlAlchemyFeedbackRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def apply(
        self,
        command_job_id: UUID,
        owner: str,
        value: FeedbackValue,
        *,
        saved_candidate: ResponsePlanCandidate,
        no_change_candidate: ResponsePlanCandidate,
        limit_candidate: ResponsePlanCandidate,
        unavailable_candidate: ResponsePlanCandidate,
    ) -> FeedbackOutcome:
        """Resolve, serialize, mutate, and acknowledge in one transaction."""

        async with self._session_factory() as session:
            async with session.begin():
                command = await session.get(
                    TelegramCommandJobModel, command_job_id, with_for_update=True
                )
                if (
                    command is None
                    or command.status != CommandJobStatus.LEASED
                    or command.lease_owner != owner
                    or command.command_name != "feedback"
                ):
                    return FeedbackOutcome.TARGET_UNAVAILABLE
                target = await self._resolve_target(session, command)
                if target is None:
                    await self._complete(
                        session,
                        command,
                        unavailable_candidate,
                        "feedback_target_unavailable",
                    )
                    return FeedbackOutcome.TARGET_UNAVAILABLE

                lock_key = ":".join(
                    str(item)
                    for item in (
                        target.tenant_id,
                        target.assistant_id,
                        target.connection_id,
                        target.conversation_id,
                        target.response_plan_id,
                        target.participant_id,
                    )
                )
                await session.execute(
                    select(
                        func.pg_advisory_xact_lock(func.hashtextextended(lock_key, 0))
                    )
                )
                current = await session.scalar(
                    select(ConversationFeedbackModel)
                    .where(
                        ConversationFeedbackModel.tenant_id == target.tenant_id,
                        ConversationFeedbackModel.assistant_id == target.assistant_id,
                        ConversationFeedbackModel.connection_id == target.connection_id,
                        ConversationFeedbackModel.conversation_id
                        == target.conversation_id,
                        ConversationFeedbackModel.response_plan_id
                        == target.response_plan_id,
                        ConversationFeedbackModel.participant_id
                        == target.participant_id,
                    )
                    .with_for_update()
                )
                if current is not None and current.value == value:
                    await self._complete(
                        session,
                        command,
                        no_change_candidate,
                        "feedback_no_change",
                    )
                    return FeedbackOutcome.NO_CHANGE
                if current is not None and current.revision >= MAX_FEEDBACK_REVISIONS:
                    await self._complete(
                        session,
                        command,
                        limit_candidate,
                        "feedback_limit_reached",
                    )
                    return FeedbackOutcome.LIMIT_REACHED

                revision = 1 if current is None else current.revision + 1
                if current is None:
                    current = ConversationFeedbackModel(
                        **_target_values(target), value=value, revision=revision
                    )
                    session.add(current)
                    await session.flush()
                else:
                    current.value = value
                    current.revision = revision
                session.add(
                    ConversationFeedbackEventModel(
                        feedback_id=current.id,
                        **_target_values(target),
                        command_job_id=command.id,
                        value=value,
                        revision=revision,
                    )
                )
                await self._complete(
                    session, command, saved_candidate, "feedback_saved"
                )
                return FeedbackOutcome.SAVED

    async def _complete(
        self,
        session: AsyncSession,
        command: TelegramCommandJobModel,
        candidate: ResponsePlanCandidate,
        result_code: str,
    ) -> None:
        completed = await SqlAlchemyCommandRepository(
            self._session_factory
        ).complete_in_session(session, command, candidate, result_code, None)
        if not completed:
            raise RuntimeError("feedback command completion lost authority")

    async def _resolve_target(
        self, session: AsyncSession, command: TelegramCommandJobModel
    ) -> FeedbackTarget | None:
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
        target_message = await session.get(
            MessageModel, command_message.reply_to_message_id
        )
        if (
            target_message is None
            or target_message.conversation_id != conversation.id
            or target_message.direction != MessageDirection.OUTGOING
            or target_message.message_type not in {MessageType.TEXT, MessageType.VOICE}
            or target_message.content_redacted_at is not None
        ):
            return None
        action = await self._canonical_action(session, target_message)
        if (
            action is None
            or action.conversation_id != conversation.id
            or action.status != OutboundActionStatus.DELIVERED
        ):
            return None
        if action.kind == OutboundActionKind.VOICE:
            artifact = (
                await session.get(
                    GeneratedVoiceArtifactModel, action.generated_voice_artifact_id
                )
                if action.generated_voice_artifact_id is not None
                else None
            )
            if artifact is None or artifact.conversation_id != conversation.id:
                return None
            response_plan_id = artifact.source_response_plan_id
        else:
            response_plan_id = action.response_plan_id
        plan = await session.get(ResponsePlanModel, response_plan_id)
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
        return FeedbackTarget(
            tenant_id=authority.tenant.id,
            assistant_id=authority.assistant.id,
            connection_id=authority.connection.id,
            conversation_id=conversation.id,
            response_plan_id=plan.id,
            participant_id=participant.id,
            target_message_id=target_message.id,
            target_outbound_action_id=action.id,
        )

    async def _canonical_action(
        self, session: AsyncSession, target: MessageModel
    ) -> OutboundActionModel | None:
        if target.message_type == MessageType.VOICE:
            action = (
                await session.get(OutboundActionModel, target.outbound_action_id)
                if target.outbound_action_id is not None
                else None
            )
            return (
                action
                if action is not None and action.kind == OutboundActionKind.VOICE
                else None
            )
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
            or action.kind
            not in {OutboundActionKind.TEXT, OutboundActionKind.EDIT_TEXT}
            or action.payload_redacted_at is not None
        ):
            return None
        return action


def _target_values(target: FeedbackTarget) -> dict[str, UUID]:
    return {
        "tenant_id": target.tenant_id,
        "assistant_id": target.assistant_id,
        "connection_id": target.connection_id,
        "conversation_id": target.conversation_id,
        "response_plan_id": target.response_plan_id,
        "participant_id": target.participant_id,
        "target_message_id": target.target_message_id,
        "target_outbound_action_id": target.target_outbound_action_id,
    }
