"""Short-session authority resolution for transient Telegram reactions."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.platform import SetReactionRequest
from app.application.reactions import ReactionFacts, decide_reaction
from app.domain.conversation import MembershipStatus
from app.domain.persistence import (
    AssistantStatus,
    ConversationStatus,
    Platform,
    PlatformConnectionStatus,
    ResponseMode,
    TenantStatus,
)
from app.domain.planning import PlanningJobStatus
from app.infrastructure.database.models import (
    AssistantModel,
    ControlTenantModel,
    ConversationModel,
    MessageModel,
    ParticipantModel,
    PlatformConnectionModel,
    ResponsePlanningJobModel,
    TelegramCommandJobModel,
)


@dataclass(frozen=True, slots=True)
class ReactionTarget:
    request: SetReactionRequest


@dataclass(frozen=True, slots=True)
class ReactionScope:
    tenant_id: UUID
    assistant_id: UUID
    connection_id: UUID
    conversation_id: UUID


class SqlAlchemyReactionAuthority:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def resolve(
        self,
        planning_job_id: UUID,
        *,
        scope: ReactionScope,
        expected_attempt: int,
        safety_allowed: bool,
    ) -> ReactionTarget | None:
        """Fail closed and release the database session before returning a target."""

        command_record_id = TelegramCommandJobModel.conversation_processing_record_id
        planning_record_id = ResponsePlanningJobModel.conversation_processing_record_id
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(
                        ResponsePlanningJobModel,
                        MessageModel,
                        ParticipantModel,
                        ConversationModel,
                        PlatformConnectionModel,
                        AssistantModel,
                        ControlTenantModel,
                    )
                    .join(
                        MessageModel,
                        MessageModel.id == ResponsePlanningJobModel.message_id,
                    )
                    .join(
                        ConversationModel,
                        ConversationModel.id
                        == ResponsePlanningJobModel.conversation_id,
                    )
                    .join(
                        ParticipantModel,
                        ParticipantModel.id == MessageModel.participant_id,
                    )
                    .join(
                        PlatformConnectionModel,
                        PlatformConnectionModel.id
                        == ConversationModel.platform_connection_id,
                    )
                    .join(
                        AssistantModel,
                        (AssistantModel.id == PlatformConnectionModel.assistant_id)
                        & (
                            AssistantModel.tenant_id
                            == PlatformConnectionModel.tenant_id
                        ),
                    )
                    .join(
                        ControlTenantModel,
                        ControlTenantModel.id == AssistantModel.tenant_id,
                    )
                    .where(
                        ResponsePlanningJobModel.id == planning_job_id,
                        ResponsePlanningJobModel.conversation_id
                        == scope.conversation_id,
                        ConversationModel.id == scope.conversation_id,
                        PlatformConnectionModel.id == scope.connection_id,
                        AssistantModel.id == scope.assistant_id,
                        ControlTenantModel.id == scope.tenant_id,
                        ResponsePlanningJobModel.attempt_count == expected_attempt,
                        ResponsePlanningJobModel.status.in_(
                            {
                                PlanningJobStatus.COMPLETED,
                                PlanningJobStatus.NO_RESPONSE,
                                PlanningJobStatus.FAILED,
                            }
                        ),
                        ResponsePlanningJobModel.completed_at.is_not(None),
                        MessageModel.conversation_id
                        == ResponsePlanningJobModel.conversation_id,
                        ParticipantModel.conversation_id
                        == ResponsePlanningJobModel.conversation_id,
                        ~exists(
                            select(TelegramCommandJobModel.id).where(
                                command_record_id == planning_record_id
                            )
                        ),
                    )
                )
            ).one_or_none()
        if row is None:
            return None
        job, message, participant, conversation, connection, assistant, tenant = row
        active_authority = (
            tenant.status == TenantStatus.ACTIVE
            and assistant.status == AssistantStatus.ACTIVE
            and connection.status == PlatformConnectionStatus.ACTIVE
            and conversation.status == ConversationStatus.ACTIVE
            and conversation.response_mode != ResponseMode.PAUSED
            and conversation.assistant_membership_status
            not in {
                MembershipStatus.LEFT,
                MembershipStatus.KICKED,
                MembershipStatus.RESTRICTED,
            }
        )
        ordinary_flow = (
            job.source_command_job_id is None
            and job.root_response_plan_id is None
            and job.parent_response_plan_id is None
            and job.regeneration_ordinal is None
        )
        user_authored = (
            message.participant_id == participant.id
            and participant.privacy_deleted_at is None
            and participant.membership_status == MembershipStatus.MEMBER
            and not participant.is_bot
        )
        content_available = (
            message.content_redacted_at is None and message.edited_at is None
        )
        decision = decide_reaction(
            ReactionFacts(
                platform=connection.platform,
                trigger=job.trigger,
                direction=message.direction,
                message_type=message.message_type,
                text=message.text,
                message_eligible=message.eligible is True,
                user_authored=user_authored,
                content_available=content_available,
                ordinary_flow=ordinary_flow,
                authority_active=active_authority,
                safety_allowed=safety_allowed,
            )
        )
        chat_id = conversation.platform_conversation_id
        message_id = message.platform_message_id
        if (
            decision.kind is None
            or connection.platform != Platform.TELEGRAM
            or not chat_id
            or not chat_id.lstrip("-").isdecimal()
            or int(chat_id) == 0
            or not message_id.isdecimal()
            or int(message_id) <= 0
        ):
            return None
        return ReactionTarget(SetReactionRequest(chat_id, message_id, decision.kind))
