"""PostgreSQL reader that converts persisted messages into context values."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, exists, false, func, or_, select, true
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from app.application.context import (
    ContextMemory,
    ContextMessage,
    ContextPersonalContext,
    ContextReply,
    ContextSummary,
    ConversationContext,
    build_context,
)
from app.application.conversation import CharacterTokenEstimator
from app.application.knowledge import ContextKnowledge
from app.application.ports.telemetry import MetricsRecorder, NoOpMetricsRecorder
from app.core.config import Settings
from app.domain.outbound import OutboundActionStatus
from app.domain.persistence import (
    AssistantStatus,
    ConversationStatus,
    ConversationType,
    MemoryKind,
    MemoryScope,
    MemoryStatus,
    MemoryVisibility,
    MessageDirection,
    PlatformConnectionStatus,
    TenantStatus,
)
from app.domain.summary import ConversationSummaryStatus
from app.infrastructure.database.models import (
    ConversationModel,
    ConversationSummaryModel,
    MemoryItemModel,
    MemoryRecallPolicyModel,
    MessageMediaModel,
    MessageModel,
    OutboundActionModel,
    ParticipantModel,
    PlatformConnectionModel,
    ResponsePlanModel,
    TelegramCommandJobModel,
)
from app.infrastructure.knowledge import KnowledgeRetriever
from app.infrastructure.semantic_memory import SemanticMemoryRetriever


class SqlAlchemyConversationContextReader:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        telemetry: MetricsRecorder | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._telemetry = telemetry or NoOpMetricsRecorder()

    async def build_for_message(
        self,
        message_id: UUID,
        now: datetime | None = None,
        planning_job_id: UUID | None = None,
        include_semantic: bool = True,
        before_external_io: Callable[[], Awaitable[bool]] | None = None,
        excluded_message_ids: tuple[UUID, ...] = (),
    ) -> ConversationContext | None:
        current_time = now or datetime.now(UTC)
        semantic_scope: MemoryScope | None = None
        assistant_id: UUID | None = None
        tenant_id: UUID | None = None
        platform_connection_id: UUID | None = None
        recall_enabled = False
        async with self._session_factory() as session:
            current = await self._load_message(session, message_id)
            if current is None:
                return None
            cutoff = current_time - timedelta(
                days=self._settings.context_max_history_age_days
            )
            rows = await session.execute(
                select(MessageModel, ParticipantModel, MessageMediaModel)
                .outerjoin(
                    ParticipantModel, MessageModel.participant_id == ParticipantModel.id
                )
                .outerjoin(
                    MessageMediaModel, MessageMediaModel.message_id == MessageModel.id
                )
                .where(
                    MessageModel.conversation_id == current.conversation_id,
                    MessageModel.platform_sent_at >= cutoff,
                    ~exists(
                        select(TelegramCommandJobModel.id).where(
                            TelegramCommandJobModel.message_id == MessageModel.id,
                            TelegramCommandJobModel.command_name == "feedback",
                        )
                    ),
                    ~exists(
                        select(OutboundActionModel.id)
                        .join(
                            ResponsePlanModel,
                            ResponsePlanModel.id
                            == OutboundActionModel.response_plan_id,
                        )
                        .join(
                            TelegramCommandJobModel,
                            TelegramCommandJobModel.id
                            == ResponsePlanModel.command_job_id,
                        )
                        .where(
                            OutboundActionModel.id == MessageModel.outbound_action_id,
                            TelegramCommandJobModel.command_name == "feedback",
                        )
                    ),
                    MessageModel.id.not_in(excluded_message_ids)
                    if excluded_message_ids
                    else true(),
                )
                .order_by(MessageModel.platform_sent_at.desc(), MessageModel.id.desc())
                .limit(
                    self._settings.context_recent_message_limit
                    + self._settings.context_reply_chain_depth
                    + 10
                )
            )
            candidates = tuple(
                self._to_context(message, participant, media)
                for message, participant, media in rows
            )
            conversation = await session.get(ConversationModel, current.conversation_id)
            connection = (
                await session.get(
                    PlatformConnectionModel, conversation.platform_connection_id
                )
                if conversation is not None
                else None
            )
            if conversation is not None and connection is not None:
                assistant_id = connection.assistant_id
                tenant_id = connection.tenant_id
                platform_connection_id = conversation.platform_connection_id
                semantic_scope = (
                    MemoryScope.PRIVATE_CONVERSATION
                    if conversation.conversation_type == ConversationType.PRIVATE
                    else MemoryScope.GROUP_CONVERSATION
                )
            try:
                async with session.begin_nested():
                    if current.participant_id is not None:
                        policy = await session.scalar(
                            select(MemoryRecallPolicyModel.enabled).where(
                                MemoryRecallPolicyModel.participant_id
                                == current.participant_id,
                                MemoryRecallPolicyModel.conversation_id
                                == current.conversation_id,
                            )
                        )
                        recall_enabled = policy is not False

                    owner_policy = aliased(MemoryRecallPolicyModel)
                    memory_rows = await session.execute(
                        select(MemoryItemModel, ParticipantModel)
                        .join(
                            ConversationModel,
                            ConversationModel.id == MemoryItemModel.conversation_id,
                        )
                        .join(
                            PlatformConnectionModel,
                            PlatformConnectionModel.id
                            == ConversationModel.platform_connection_id,
                        )
                        .outerjoin(
                            ParticipantModel,
                            ParticipantModel.id
                            == MemoryItemModel.creator_participant_id,
                        )
                        .outerjoin(
                            owner_policy,
                            and_(
                                owner_policy.participant_id
                                == MemoryItemModel.creator_participant_id,
                                owner_policy.conversation_id
                                == MemoryItemModel.conversation_id,
                            ),
                        )
                        .where(
                            true() if recall_enabled else false(),
                            MemoryItemModel.conversation_id == current.conversation_id,
                            MemoryItemModel.platform_connection_id
                            == ConversationModel.platform_connection_id,
                            MemoryItemModel.assistant_id
                            == PlatformConnectionModel.assistant_id,
                            MemoryItemModel.status == MemoryStatus.ACTIVE,
                            MemoryItemModel.kind == MemoryKind.EXPLICIT_FACT,
                            MemoryItemModel.visibility
                            == MemoryVisibility.SAME_CONVERSATION,
                            or_(
                                owner_policy.id.is_(None),
                                owner_policy.enabled.is_(True),
                            ),
                            or_(
                                MemoryItemModel.expires_at.is_(None),
                                MemoryItemModel.expires_at > current_time,
                            ),
                        )
                        .order_by(
                            MemoryItemModel.updated_at.desc(),
                            MemoryItemModel.revision.desc(),
                            MemoryItemModel.id.desc(),
                        )
                        .limit(self._settings.memory_context_limit)
                    )
                    memories = tuple(
                        self._to_memory(memory, participant)
                        for memory, participant in memory_rows
                    )
                    personal_context: tuple[ContextPersonalContext, ...] = ()
                    if (
                        recall_enabled
                        and current.participant_id is not None
                        and conversation is not None
                        and connection is not None
                        and conversation.conversation_type == ConversationType.PRIVATE
                    ):
                        personal_rows = await session.scalars(
                            select(MemoryItemModel)
                            .where(
                                MemoryItemModel.conversation_id
                                == current.conversation_id,
                                MemoryItemModel.assistant_id == connection.assistant_id,
                                MemoryItemModel.platform_connection_id
                                == conversation.platform_connection_id,
                                MemoryItemModel.scope
                                == MemoryScope.PRIVATE_CONVERSATION,
                                MemoryItemModel.creator_participant_id
                                == current.participant_id,
                                MemoryItemModel.kind == MemoryKind.PERSONAL_CONTEXT,
                                MemoryItemModel.visibility
                                == MemoryVisibility.CREATOR_ONLY,
                                MemoryItemModel.status == MemoryStatus.ACTIVE,
                                MemoryItemModel.content.is_not(None),
                                or_(
                                    MemoryItemModel.expires_at.is_(None),
                                    MemoryItemModel.expires_at > current_time,
                                ),
                            )
                            .order_by(
                                MemoryItemModel.updated_at.desc(),
                                MemoryItemModel.id.desc(),
                            )
                            .limit(self._settings.personal_context_limit)
                        )
                        personal_context = tuple(
                            self._to_personal_context(item) for item in personal_rows
                        )
            except SQLAlchemyError:
                # Roll back only the memory lookup savepoint. Never treat a
                # failed authority lookup as default-enabled recall.
                recall_enabled = False
                memories = ()
                personal_context = ()
            summary = await self._active_summary(session, current, current_time)
        reply_reference = await SqlAlchemyReplyContextResolver(
            self._session_factory,
            max_age_days=self._settings.context_max_history_age_days,
        ).resolve(message_id, now=current_time)
        semantic_memories: tuple[ContextMemory, ...] = ()
        if (
            include_semantic
            and recall_enabled
            and self._settings.semantic_memory_enabled
            and current.text
            and assistant_id is not None
            and platform_connection_id is not None
            and semantic_scope is not None
        ):
            semantic_memories = await SemanticMemoryRetriever(
                self._settings, self._session_factory, self._telemetry
            ).retrieve(
                current.text,
                assistant_id=assistant_id,
                platform_connection_id=platform_connection_id,
                conversation_id=current.conversation_id,
                scope=semantic_scope,
                planning_job_id=planning_job_id,
                before_io=before_external_io,
            )
        knowledge: tuple[ContextKnowledge, ...] = ()
        if (
            self._settings.knowledge_rag_enabled
            and current.text
            and tenant_id is not None
            and assistant_id is not None
        ):
            knowledge = await KnowledgeRetriever(
                self._settings, self._session_factory, self._telemetry
            ).retrieve(
                current.text,
                tenant_id=tenant_id,
                assistant_id=assistant_id,
                planning_job_id=planning_job_id,
                before_io=before_external_io,
            )
        return build_context(
            current=current,
            candidates=candidates,
            now=current_time,
            recent_limit=self._settings.context_recent_message_limit,
            reply_chain_depth=self._settings.context_reply_chain_depth,
            token_budget=self._settings.context_token_budget,
            character_limit=self._settings.context_message_character_limit,
            max_age_days=self._settings.context_max_history_age_days,
            estimator=CharacterTokenEstimator(),
            explicit_memories=_merge_memories(
                semantic_memories[: self._settings.semantic_memory_context_limit],
                memories,
            )[: self._settings.memory_context_limit],
            memory_character_budget=(
                min(
                    self._settings.memory_context_character_budget,
                    self._settings.semantic_memory_character_budget,
                )
                if self._settings.semantic_memory_enabled
                else self._settings.memory_context_character_budget
            ),
            personal_context=personal_context,
            personal_context_limit=self._settings.personal_context_limit,
            personal_context_character_budget=(
                self._settings.personal_context_character_budget
            ),
            historical_summary=summary,
            knowledge=knowledge,
            reply_reference=reply_reference,
        )

    async def _active_summary(
        self, session: AsyncSession, current: ContextMessage, now: datetime
    ) -> ContextSummary | None:
        if not self._settings.conversation_summaries_enabled:
            return None
        summary = await session.scalar(
            select(ConversationSummaryModel)
            .where(
                ConversationSummaryModel.conversation_id == current.conversation_id,
                ConversationSummaryModel.platform_thread_id.is_not_distinct_from(
                    current.platform_thread_id
                ),
                ConversationSummaryModel.status == ConversationSummaryStatus.COMPLETED,
                ConversationSummaryModel.invalidated_at.is_(None),
                ConversationSummaryModel.expires_at > now,
                ConversationSummaryModel.summary_text.is_not(None),
                ConversationSummaryModel.source_ended_at < current.sent_at,
            )
            .order_by(
                ConversationSummaryModel.source_ended_at.desc(),
                ConversationSummaryModel.id.desc(),
            )
            .limit(1)
        )
        if summary is None or not summary.summary_text:
            return None
        return ContextSummary(
            summary=summary.summary_text,
            schema_version=summary.schema_version,
            prompt_version=summary.prompt_version,
            source_ended_at=summary.source_ended_at,
        )

    async def _load_message(
        self, session: AsyncSession, message_id: UUID
    ) -> ContextMessage | None:
        row = await session.execute(
            select(MessageModel, ParticipantModel, MessageMediaModel)
            .outerjoin(
                ParticipantModel, MessageModel.participant_id == ParticipantModel.id
            )
            .outerjoin(
                MessageMediaModel, MessageMediaModel.message_id == MessageModel.id
            )
            .where(MessageModel.id == message_id)
        )
        result = row.first()
        return self._to_context(*result) if result is not None else None

    @staticmethod
    def _to_context(
        message: MessageModel,
        participant: ParticipantModel | None,
        media: MessageMediaModel | None = None,
    ) -> ContextMessage:
        return ContextMessage(
            id=message.id,
            conversation_id=message.conversation_id,
            participant_id=message.participant_id,
            platform_thread_id=message.platform_thread_id,
            text=message.text,
            sent_at=message.platform_sent_at or message.created_at,
            reply_to_message_id=message.reply_to_message_id,
            sender_display_name=participant.display_name if participant else "Unknown",
            mention_allowed=participant.mention_allowed if participant else False,
            teasing_allowed=participant.teasing_allowed if participant else False,
            privacy_deleted=participant.privacy_deleted_at is not None
            if participant
            else False,
            protected=participant.protected_at is not None if participant else False,
            content_provenance=(
                str(message.metadata_["content_provenance"])
                if message.metadata_.get("content_provenance")
                in ("media_caption", "voice_transcript", "audio_transcript")
                else None
            ),
            media_caption=(
                media.caption
                if media is not None
                and message.metadata_.get("content_provenance")
                in ("voice_transcript", "audio_transcript")
                else None
            ),
        )

    @staticmethod
    def _to_memory(
        memory: MemoryItemModel, participant: ParticipantModel | None
    ) -> ContextMemory:
        return ContextMemory(
            public_id=memory.public_id,
            content=memory.content or "",
            created_at=memory.created_at,
            creator_label=(
                "Deleted user"
                if participant is None or participant.privacy_deleted_at is not None
                else participant.display_name
            ),
        )

    @staticmethod
    def _to_personal_context(memory: MemoryItemModel) -> ContextPersonalContext:
        if memory.context_key is None:
            raise ValueError("personal context row is missing its key")
        return ContextPersonalContext(
            public_id=memory.public_id,
            key=memory.context_key.value,
            content=memory.content or "",
            revision=memory.revision,
            updated_at=memory.updated_at,
        )


def _merge_memories(
    semantic: tuple[ContextMemory, ...], fallback: tuple[ContextMemory, ...]
) -> tuple[ContextMemory, ...]:
    """Keep semantic ranking first, then deterministic canonical fallback."""
    seen = {item.public_id for item in semantic}
    return semantic + tuple(item for item in fallback if item.public_id not in seen)


class SqlAlchemyReplyContextResolver:
    """Resolve one Telegram reply hint through canonical PostgreSQL authority."""

    MAX_CHARACTERS = 1200

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        max_age_days: int,
    ) -> None:
        self._session_factory = session_factory
        self._max_age_days = max_age_days

    async def resolve(
        self, current_message_id: UUID, *, now: datetime
    ) -> ContextReply | None:
        cutoff = now - timedelta(days=self._max_age_days)
        async with self._session_factory() as session:
            current = await session.get(MessageModel, current_message_id)
            if current is None or (
                current.reply_to_message_id is None
                and current.reply_to_platform_message_id is None
            ):
                return None
            row = (
                await session.execute(
                    select(
                        ConversationModel,
                        PlatformConnectionModel,
                    )
                    .join(
                        PlatformConnectionModel,
                        PlatformConnectionModel.id
                        == ConversationModel.platform_connection_id,
                    )
                    .where(
                        ConversationModel.id == current.conversation_id,
                        ConversationModel.status == ConversationStatus.ACTIVE,
                        PlatformConnectionModel.status
                        == PlatformConnectionStatus.ACTIVE,
                    )
                )
            ).one_or_none()
            if row is None:
                return None
            conversation, connection = row
            from app.infrastructure.database.models import (
                AssistantModel,
                ControlTenantModel,
            )

            authority = (
                await session.execute(
                    select(AssistantModel.id)
                    .join(
                        ControlTenantModel,
                        ControlTenantModel.id == AssistantModel.tenant_id,
                    )
                    .where(
                        AssistantModel.id == connection.assistant_id,
                        AssistantModel.tenant_id == connection.tenant_id,
                        AssistantModel.status == AssistantStatus.ACTIVE,
                        ControlTenantModel.status == TenantStatus.ACTIVE,
                    )
                )
            ).scalar_one_or_none()
            if authority is None:
                return None

            target_query = select(MessageModel, ParticipantModel).outerjoin(
                ParticipantModel, MessageModel.participant_id == ParticipantModel.id
            )
            if current.reply_to_message_id is not None:
                target_query = target_query.where(
                    MessageModel.id == current.reply_to_message_id
                )
            else:
                target_query = target_query.where(
                    MessageModel.platform_message_id
                    == current.reply_to_platform_message_id
                )
            target_row = (
                await session.execute(
                    target_query.where(
                        MessageModel.conversation_id == conversation.id,
                        MessageModel.content_redacted_at.is_(None),
                        MessageModel.text.is_not(None),
                        func.coalesce(
                            MessageModel.platform_sent_at,
                            MessageModel.created_at,
                        )
                        >= cutoff,
                    ).limit(1)
                )
            ).one_or_none()
            if target_row is None:
                return None
            target, participant = target_row
            feedback_command = await session.scalar(
                select(TelegramCommandJobModel.id).where(
                    TelegramCommandJobModel.message_id == target.id,
                    TelegramCommandJobModel.command_name == "feedback",
                )
            )
            if feedback_command is not None:
                return None
            if participant is not None and participant.privacy_deleted_at is not None:
                return None

            text = target.text or ""
            plan_id: UUID | None = None
            related_ids: tuple[UUID, ...] = ()
            if target.outbound_action_id is not None:
                action = await session.get(
                    OutboundActionModel, target.outbound_action_id
                )
                plan = (
                    await session.get(ResponsePlanModel, action.response_plan_id)
                    if action is not None
                    and action.conversation_id == conversation.id
                    and action.status == OutboundActionStatus.DELIVERED
                    and action.payload_redacted_at is None
                    else None
                )
                if plan is not None and plan.command_job_id is not None:
                    plan_command_name = await session.scalar(
                        select(TelegramCommandJobModel.command_name).where(
                            TelegramCommandJobModel.id == plan.command_job_id
                        )
                    )
                    if plan_command_name == "feedback":
                        return None
                if (
                    plan is None
                    or plan.content_redacted_at is not None
                    or not plan.text
                ):
                    return None
                text = plan.text
                plan_id = plan.id
                related_ids = tuple(
                    await session.scalars(
                        select(MessageModel.id)
                        .join(
                            OutboundActionModel,
                            MessageModel.outbound_action_id == OutboundActionModel.id,
                        )
                        .where(
                            OutboundActionModel.response_plan_id == plan.id,
                            OutboundActionModel.conversation_id == conversation.id,
                            OutboundActionModel.status
                            == OutboundActionStatus.DELIVERED,
                            MessageModel.content_redacted_at.is_(None),
                        )
                        .order_by(OutboundActionModel.sequence_number)
                    )
                )
            if not text:
                return None
            bounded = text[: self.MAX_CHARACTERS]
            return ContextReply(
                target_message_id=target.id,
                participant_id=target.participant_id,
                sender_role=(
                    "assistant"
                    if target.direction == MessageDirection.OUTGOING
                    else "user"
                ),
                sender_display_name=(
                    participant.display_name if participant is not None else "Assistant"
                ),
                text=bounded,
                sent_at=target.platform_sent_at or target.created_at,
                related_message_ids=related_ids,
                response_plan_id=plan_id,
                truncated=len(bounded) < len(text),
                content_provenance=(
                    str(target.metadata_["content_provenance"])
                    if target.metadata_.get("content_provenance")
                    in ("media_caption", "voice_transcript", "audio_transcript")
                    else None
                ),
            )
