"""Authoritative, idempotent admission for reply-based regeneration."""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.ambient import ParticipationTrigger
from app.domain.outbound import OutboundActionKind, OutboundActionStatus
from app.domain.persistence import (
    CommandJobStatus,
    MessageDirection,
    MessageType,
)
from app.infrastructure.database.models import (
    ConversationConfigurationRevisionModel,
    ConversationModel,
    MessageModel,
    OutboundActionModel,
    ResponsePlanModel,
    ResponsePlanningJobModel,
    TelegramCommandJobModel,
)


class RegenerationAdmission(StrEnum):
    ACCEPTED = "accepted"
    TARGET_UNAVAILABLE = "target_unavailable"
    LIMIT_REACHED = "limit_reached"


class SqlAlchemyRegenerationRepository:
    MAX_REGENERATIONS = 3

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def accept(self, command_job_id: UUID, owner: str) -> RegenerationAdmission:
        """Create one governed planning job or leave the command lease untouched."""

        async with self._session_factory() as session:
            async with session.begin():
                command = await session.get(
                    TelegramCommandJobModel, command_job_id, with_for_update=True
                )
                if (
                    command is None
                    or command.status != CommandJobStatus.LEASED
                    or command.lease_owner != owner
                ):
                    return RegenerationAdmission.TARGET_UNAVAILABLE
                existing = await session.scalar(
                    select(ResponsePlanningJobModel).where(
                        ResponsePlanningJobModel.source_command_job_id == command.id
                    )
                )
                if existing is not None:
                    command.status = CommandJobStatus.COMPLETED
                    command.result_code = "regeneration_accepted"
                    command.completed_at = datetime.now(UTC)
                    command.lease_owner = None
                    command.lease_expires_at = None
                    return RegenerationAdmission.ACCEPTED

                resolved = await self._resolve_target(session, command)
                if resolved is None:
                    return RegenerationAdmission.TARGET_UNAVAILABLE
                parent_plan, parent_job = resolved
                root_id = parent_job.root_response_plan_id or parent_plan.id
                root_plan = await session.get(
                    ResponsePlanModel, root_id, with_for_update=True
                )
                if root_plan is None or root_plan.planning_job_id is None:
                    return RegenerationAdmission.TARGET_UNAVAILABLE
                root_job = await session.get(
                    ResponsePlanningJobModel, root_plan.planning_job_id
                )
                if (
                    root_job is None
                    or root_job.source_command_job_id is not None
                    or root_job.conversation_id != command.conversation_id
                ):
                    return RegenerationAdmission.TARGET_UNAVAILABLE
                source = await session.get(MessageModel, root_job.message_id)
                conversation = await session.get(
                    ConversationModel, command.conversation_id
                )
                configuration = (
                    await session.get(
                        ConversationConfigurationRevisionModel,
                        conversation.current_configuration_revision_id,
                    )
                    if conversation is not None
                    and conversation.current_configuration_revision_id is not None
                    else None
                )
                if (
                    source is None
                    or source.conversation_id != command.conversation_id
                    or source.direction != MessageDirection.INCOMING
                    or source.content_redacted_at is not None
                    or configuration is None
                    or parent_plan.content_redacted_at is not None
                ):
                    return RegenerationAdmission.TARGET_UNAVAILABLE
                current_max = await session.scalar(
                    select(
                        func.max(ResponsePlanningJobModel.regeneration_ordinal)
                    ).where(ResponsePlanningJobModel.root_response_plan_id == root_id)
                )
                ordinal = int(current_max or 0) + 1
                if ordinal > self.MAX_REGENERATIONS:
                    return RegenerationAdmission.LIMIT_REACHED
                session.add(
                    ResponsePlanningJobModel(
                        conversation_processing_record_id=(
                            command.conversation_processing_record_id
                        ),
                        conversation_id=command.conversation_id,
                        message_id=source.id,
                        source_command_job_id=command.id,
                        root_response_plan_id=root_id,
                        parent_response_plan_id=parent_plan.id,
                        regeneration_ordinal=ordinal,
                        prompt_version=root_job.prompt_version,
                        response_schema_version=root_job.response_schema_version,
                        personality_profile_version_id=(
                            configuration.personality_profile_version_id
                        ),
                        configuration_revision_id=configuration.id,
                        trigger=ParticipationTrigger.ADDRESSED,
                    )
                )
                command.status = CommandJobStatus.COMPLETED
                command.result_code = "regeneration_accepted"
                command.completed_at = datetime.now(UTC)
                command.lease_owner = None
                command.lease_expires_at = None
                await session.flush()
                return RegenerationAdmission.ACCEPTED

    async def _resolve_target(
        self, session: AsyncSession, command: TelegramCommandJobModel
    ) -> tuple[ResponsePlanModel, ResponsePlanningJobModel] | None:
        command_message = await session.get(MessageModel, command.message_id)
        if (
            command_message is None
            or command_message.conversation_id != command.conversation_id
            or command_message.reply_to_message_id is None
        ):
            return None
        target = await session.get(MessageModel, command_message.reply_to_message_id)
        if (
            target is None
            or target.conversation_id != command.conversation_id
            or target.direction != MessageDirection.OUTGOING
            or target.message_type not in {MessageType.TEXT, MessageType.STICKER}
            or target.content_redacted_at is not None
        ):
            return None
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
            or action.conversation_id != command.conversation_id
            or action.status != OutboundActionStatus.DELIVERED
        ):
            return None
        uncertain_plan_action = await session.scalar(
            select(OutboundActionModel.id).where(
                OutboundActionModel.response_plan_id == action.response_plan_id,
                OutboundActionModel.status == OutboundActionStatus.DELIVERY_UNKNOWN,
            )
        )
        if uncertain_plan_action is not None:
            return None
        plan = await session.get(ResponsePlanModel, action.response_plan_id)
        if (
            plan is None
            or plan.planning_job_id is None
            or not plan.should_respond
            or plan.content_redacted_at is not None
        ):
            return None
        planning_job = await session.get(ResponsePlanningJobModel, plan.planning_job_id)
        if (
            planning_job is None
            or planning_job.conversation_id != command.conversation_id
        ):
            return None
        return plan, planning_job
