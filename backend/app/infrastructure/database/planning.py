"""PostgreSQL lease and finalization repository for response planning."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.outbound import compile_outbound_actions, split_telegram_text
from app.application.regeneration import (
    EditTargetFacts,
    RegenerationPresentation,
    choose_regeneration_presentation,
)
from app.application.response_plan import ResponsePlanCandidate
from app.domain.ambient import ParticipationTrigger
from app.domain.knowledge import (
    KnowledgeBaseStatus,
    KnowledgeDocumentStatus,
    KnowledgeIndexState,
)
from app.domain.media import MediaFailureReason, MediaKind, MediaStatus
from app.domain.outbound import OutboundActionKind, OutboundActionStatus
from app.domain.persistence import (
    AssistantStatus,
    ConversationStatus,
    MessageDirection,
    MessageType,
    PlatformConnectionStatus,
    TenantStatus,
)
from app.domain.planning import (
    GenerationAttemptKind,
    GenerationAttemptStatus,
    PlanningJobStatus,
    ProviderErrorCategory,
    ProviderId,
)
from app.domain.recovery import RecoveryKind
from app.infrastructure.database.models import (
    AssistantModel,
    ControlTenantModel,
    ConversationModel,
    KnowledgeBaseModel,
    KnowledgeChunkModel,
    KnowledgeDocumentModel,
    KnowledgeDocumentRevisionModel,
    MessageMediaModel,
    MessageModel,
    ModelGenerationAttemptModel,
    OperationalRecoveryItemModel,
    OutboundActionModel,
    ParticipantModel,
    PlatformConnectionModel,
    ResponsePlanModel,
    ResponsePlanningJobModel,
)


class SqlAlchemyPlanningRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def claim(
        self, owner: str, limit: int, lease_seconds: int
    ) -> list[ResponsePlanningJobModel]:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                jobs = list(
                    await session.scalars(
                        select(ResponsePlanningJobModel)
                        .where(
                            or_(
                                (
                                    ResponsePlanningJobModel.status
                                    == PlanningJobStatus.PENDING
                                )
                                & (ResponsePlanningJobModel.available_at <= now),
                                (
                                    ResponsePlanningJobModel.status
                                    == PlanningJobStatus.LEASED
                                )
                                & (ResponsePlanningJobModel.lease_expires_at < now),
                            )
                        )
                        .order_by(
                            ResponsePlanningJobModel.available_at,
                            ResponsePlanningJobModel.created_at,
                            ResponsePlanningJobModel.id,
                        )
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                )
                for job in jobs:
                    job.status = PlanningJobStatus.LEASED
                    job.lease_owner = owner
                    job.lease_expires_at = now + timedelta(seconds=lease_seconds)
                    job.attempt_count += 1
                return jobs

    async def presence_authorized(
        self, job_id: UUID, owner: str, expected_attempt: int
    ) -> bool:
        """Cheap exact-lease and lifecycle fence for transient presence I/O."""

        now = datetime.now(UTC)
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(
                        ResponsePlanningJobModel.id,
                        ConversationModel.status,
                        ControlTenantModel.status,
                        AssistantModel.status,
                        PlatformConnectionModel.status,
                    )
                    .join(
                        ConversationModel,
                        ConversationModel.id
                        == ResponsePlanningJobModel.conversation_id,
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
                        ResponsePlanningJobModel.id == job_id,
                        ResponsePlanningJobModel.status == PlanningJobStatus.LEASED,
                        ResponsePlanningJobModel.lease_owner == owner,
                        ResponsePlanningJobModel.attempt_count == expected_attempt,
                        ResponsePlanningJobModel.lease_expires_at.is_not(None),
                        ResponsePlanningJobModel.lease_expires_at > now,
                        ~exists(
                            select(OperationalRecoveryItemModel.id).where(
                                OperationalRecoveryItemModel.work_kind
                                == RecoveryKind.PLANNING,
                                OperationalRecoveryItemModel.work_id == job_id,
                            )
                        ),
                    )
                )
            ).one_or_none()
        return row is not None and (
            row[1] == ConversationStatus.ACTIVE
            and row[2] == TenantStatus.ACTIVE
            and row[3] == AssistantStatus.ACTIVE
            and row[4] == PlatformConnectionStatus.ACTIVE
        )

    async def record_attempt(
        self,
        job_id: UUID,
        provider: ProviderId,
        model: str,
        kind: GenerationAttemptKind,
        status: GenerationAttemptStatus,
        error: ProviderErrorCategory | None = None,
    ) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                previous = await session.scalar(
                    select(func.max(ModelGenerationAttemptModel.attempt_number)).where(
                        ModelGenerationAttemptModel.planning_job_id == job_id
                    )
                )
                number = (previous or 0) + 1
                session.add(
                    ModelGenerationAttemptModel(
                        planning_job_id=job_id,
                        attempt_number=number,
                        provider=provider,
                        model=model,
                        attempt_kind=kind,
                        status=status,
                        error_category=error,
                        retryable=error
                        in {
                            ProviderErrorCategory.RATE_LIMITED,
                            ProviderErrorCategory.TIMEOUT,
                            ProviderErrorCategory.TRANSPORT,
                            ProviderErrorCategory.PROVIDER_UNAVAILABLE,
                        }
                        if error
                        else None,
                    )
                )

    async def release_for_context_change(self, job_id: UUID, owner: str) -> bool:
        """Release a lease when privacy/memory changed before provider I/O."""

        async with self._session_factory() as session:
            async with session.begin():
                job = await session.get(
                    ResponsePlanningJobModel, job_id, with_for_update=True
                )
                if (
                    job is None
                    or job.status != PlanningJobStatus.LEASED
                    or job.lease_owner != owner
                ):
                    return False
                job.status = PlanningJobStatus.PENDING
                job.available_at = datetime.now(UTC)
                job.lease_owner = None
                job.lease_expires_at = None
                return True

    async def store_knowledge_provenance(
        self, job_id: UUID, owner: str, provenance: list[dict[str, str]]
    ) -> bool:
        """Persist bounded ID-only provenance under the active planning lease."""

        if len(provenance) > 6 or any(
            set(item) != {"knowledge_base_id", "document_id", "revision_id", "chunk_id"}
            for item in provenance
        ):
            raise ValueError("knowledge provenance is invalid")
        async with self._session_factory() as session:
            async with session.begin():
                job = await session.get(
                    ResponsePlanningJobModel, job_id, with_for_update=True
                )
                if (
                    job is None
                    or job.status != PlanningJobStatus.LEASED
                    or job.lease_owner != owner
                ):
                    return False
                job.knowledge_provenance = provenance
                return True

    async def knowledge_provenance_valid(
        self, job_id: UUID, provenance: list[dict[str, str]]
    ) -> bool:
        """Revalidate selected chunks immediately before model-provider I/O."""

        if not provenance:
            return True
        try:
            chunk_ids = tuple(UUID(item["chunk_id"]) for item in provenance)
            expected = {
                (
                    UUID(item["knowledge_base_id"]),
                    UUID(item["document_id"]),
                    UUID(item["revision_id"]),
                    UUID(item["chunk_id"]),
                )
                for item in provenance
            }
        except (KeyError, ValueError):
            return False
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        KnowledgeChunkModel.knowledge_base_id,
                        KnowledgeChunkModel.document_id,
                        KnowledgeChunkModel.revision_id,
                        KnowledgeChunkModel.id,
                    )
                    .join(
                        KnowledgeDocumentModel,
                        KnowledgeDocumentModel.id == KnowledgeChunkModel.document_id,
                    )
                    .join(
                        KnowledgeDocumentRevisionModel,
                        KnowledgeDocumentRevisionModel.id
                        == KnowledgeChunkModel.revision_id,
                    )
                    .join(
                        KnowledgeBaseModel,
                        KnowledgeBaseModel.id == KnowledgeChunkModel.knowledge_base_id,
                    )
                    .join(
                        AssistantModel,
                        AssistantModel.id == KnowledgeChunkModel.assistant_id,
                    )
                    .join(
                        ControlTenantModel,
                        ControlTenantModel.id == KnowledgeChunkModel.tenant_id,
                    )
                    .join(
                        ResponsePlanningJobModel,
                        ResponsePlanningJobModel.id == job_id,
                    )
                    .join(
                        ConversationModel,
                        ConversationModel.id
                        == ResponsePlanningJobModel.conversation_id,
                    )
                    .join(
                        PlatformConnectionModel,
                        PlatformConnectionModel.id
                        == ConversationModel.platform_connection_id,
                    )
                    .where(
                        KnowledgeChunkModel.id.in_(chunk_ids),
                        KnowledgeChunkModel.tenant_id
                        == PlatformConnectionModel.tenant_id,
                        KnowledgeChunkModel.assistant_id
                        == PlatformConnectionModel.assistant_id,
                        KnowledgeChunkModel.deleted_at.is_(None),
                        KnowledgeChunkModel.content.is_not(None),
                        KnowledgeDocumentModel.status == KnowledgeDocumentStatus.ACTIVE,
                        KnowledgeDocumentModel.current_revision_id
                        == KnowledgeChunkModel.revision_id,
                        KnowledgeDocumentRevisionModel.index_state
                        == KnowledgeIndexState.READY,
                        KnowledgeDocumentRevisionModel.deleted_at.is_(None),
                        KnowledgeBaseModel.status == KnowledgeBaseStatus.ACTIVE,
                        AssistantModel.status == AssistantStatus.ACTIVE,
                        AssistantModel.knowledge_enabled.is_(True),
                        ControlTenantModel.status == TenantStatus.ACTIVE,
                    )
                )
            ).all()
            return set(rows) == expected and len(rows) == len(expected) == len(
                chunk_ids
            )

    async def release_for_rate_limit(
        self, job_id: UUID, owner: str, retry_after_seconds: int
    ) -> bool:
        """Release before external I/O and retain a bounded retryable state."""

        async with self._session_factory() as session:
            async with session.begin():
                job = await session.get(
                    ResponsePlanningJobModel, job_id, with_for_update=True
                )
                if (
                    job is None
                    or job.status != PlanningJobStatus.LEASED
                    or job.lease_owner != owner
                ):
                    return False
                job.status = PlanningJobStatus.PENDING
                job.available_at = datetime.now(UTC) + timedelta(
                    seconds=retry_after_seconds
                )
                job.lease_owner = None
                job.lease_expires_at = None
                job.last_error_category = ProviderErrorCategory.RATE_LIMITED
                return True

    async def complete(
        self,
        job_id: UUID,
        owner: str,
        candidate: ResponsePlanCandidate | None,
        provider: ProviderId | None,
        model: str | None,
        error: ProviderErrorCategory | None,
        prompt_version: str,
        schema_version: str,
        ambient_reason: str | None = None,
        *,
        expected_attempt: int | None = None,
        expected_privacy_revision: int | None = None,
        expected_media_token: UUID | None = None,
        media_retention_days: int = 30,
    ) -> UUID | None:
        async with self._session_factory() as session:
            async with session.begin():
                job = await session.get(
                    ResponsePlanningJobModel, job_id, with_for_update=True
                )
                if (
                    job is None
                    or job.status != PlanningJobStatus.LEASED
                    or job.lease_owner != owner
                    or (
                        expected_attempt is not None
                        and (
                            job.attempt_count != expected_attempt
                            or job.lease_expires_at is None
                            or job.lease_expires_at <= datetime.now(UTC)
                        )
                    )
                ):
                    return None
                now = datetime.now(UTC)
                media = await session.scalar(
                    select(MessageMediaModel)
                    .where(
                        MessageMediaModel.message_id == job.message_id,
                        MessageMediaModel.conversation_id == job.conversation_id,
                    )
                    .with_for_update()
                )
                if media is not None:
                    source = await session.get(
                        MessageModel, job.message_id, with_for_update=True
                    )
                    conversation = await session.get(
                        ConversationModel, job.conversation_id, with_for_update=True
                    )
                    participant = (
                        await session.get(
                            ParticipantModel,
                            source.participant_id,
                            with_for_update=True,
                        )
                        if source is not None and source.participant_id is not None
                        else None
                    )
                    if (
                        source is None
                        or conversation is None
                        or participant is None
                        or source.content_redacted_at is not None
                        or source.edited_at is not None
                        or source.platform_sent_at is None
                        or source.platform_sent_at
                        <= now - timedelta(days=media_retention_days)
                        or participant.privacy_deleted_at is not None
                        or media.status == MediaStatus.REDACTED
                    ):
                        job.status = PlanningJobStatus.NO_RESPONSE
                        job.completed_at = now
                        job.lease_owner = None
                        job.lease_expires_at = None
                        return None
                    if (
                        expected_privacy_revision is not None
                        and conversation.memory_privacy_revision
                        != expected_privacy_revision
                    ):
                        return None
                    if media.status == MediaStatus.PREPARING:
                        if (
                            media.planning_attempt != job.attempt_count
                            or (
                                media.kind == MediaKind.PHOTO
                                and (
                                    expected_media_token is None
                                    or media.lease_token != expected_media_token
                                )
                            )
                            or media.privacy_revision
                            != conversation.memory_privacy_revision
                            or media.lease_expires_at is None
                            or media.lease_expires_at <= now
                        ):
                            return None
                        if media.kind == MediaKind.PHOTO and candidate is not None:
                            media.status = MediaStatus.COMPLETE
                            media.failure_reason = None
                        else:
                            media.status = MediaStatus.FAILED
                            media.failure_reason = MediaFailureReason.UNAVAILABLE
                        media.lease_token = None
                        media.lease_expires_at = None
                        media.completed_at = now
                job.selected_provider = provider
                job.selected_model = model
                job.last_error_category = error
                job.ambient_reason = ambient_reason
                job.completed_at = now
                job.lease_owner = None
                job.lease_expires_at = None
                if candidate is None:
                    job.status = (
                        PlanningJobStatus.NO_RESPONSE
                        if error
                        in {
                            ProviderErrorCategory.SAFETY_REFUSAL,
                            ProviderErrorCategory.BUDGET_EXHAUSTED,
                            ProviderErrorCategory.GOVERNANCE_UNAVAILABLE,
                            ProviderErrorCategory.NO_ELIGIBLE_ROUTE,
                        }
                        else PlanningJobStatus.FAILED
                    )
                    return None
                plan = ResponsePlanModel(
                    planning_job_id=job.id,
                    should_respond=candidate.should_respond,
                    reason_code=candidate.reason_code,
                    text=candidate.text,
                    reply_to_message_id=candidate.reply_to_message_id,
                    mention_participant_ids=[
                        str(value) for value in candidate.mentions
                    ],
                    sticker_intent=candidate.sticker_intent,
                    confidence=candidate.confidence,
                    language=candidate.language,
                    prompt_version=prompt_version,
                    schema_version=schema_version,
                    interaction_kind=candidate.interaction.kind,
                    teasing_target_participant_ids=[
                        str(value)
                        for value in (
                            candidate.interaction.teasing_target_participant_ids
                        )
                    ],
                )
                session.add(plan)
                await session.flush()
                edit_target = None
                if job.source_command_job_id is not None:
                    edit_target = await _regeneration_edit_target(
                        session, job, candidate
                    )
                if edit_target is not None:
                    source_message = await session.get(MessageModel, job.message_id)
                    edit_id = uuid4()
                    fallback_id = uuid4()
                    chunk = split_telegram_text(candidate.text or "")[0]
                    session.add(
                        OutboundActionModel(
                            id=edit_id,
                            response_plan_id=plan.id,
                            conversation_id=job.conversation_id,
                            sequence_number=1,
                            sequence_count=2,
                            idempotency_key=sha256(
                                f"{plan.id}:1:edit_text".encode()
                            ).hexdigest(),
                            kind=OutboundActionKind.EDIT_TEXT,
                            reply_to_message_id=None,
                            edit_target_message_id=edit_target.id,
                            edit_target_platform_message_id=(
                                edit_target.platform_message_id
                            ),
                            message_thread_id=edit_target.platform_thread_id,
                            mention_participant_ids=[
                                str(value) for value in candidate.mentions
                            ],
                            text=chunk,
                            sticker_intent=None,
                            origin=job.trigger,
                        )
                    )
                    await session.flush()
                    session.add(
                        OutboundActionModel(
                            id=fallback_id,
                            response_plan_id=plan.id,
                            conversation_id=job.conversation_id,
                            sequence_number=2,
                            sequence_count=2,
                            idempotency_key=sha256(
                                f"{plan.id}:2:text:fallback".encode()
                            ).hexdigest(),
                            kind=OutboundActionKind.TEXT,
                            status=OutboundActionStatus.FALLBACK_BLOCKED,
                            fallback_for_action_id=edit_id,
                            reply_to_message_id=candidate.reply_to_message_id,
                            message_thread_id=(
                                source_message.platform_thread_id
                                if source_message is not None
                                else None
                            ),
                            mention_participant_ids=[
                                str(value) for value in candidate.mentions
                            ],
                            text=chunk,
                            sticker_intent=None,
                            origin=job.trigger,
                        )
                    )
                    job.status = PlanningJobStatus.COMPLETED
                    return plan.id
                for action in compile_outbound_actions(plan.id, candidate):
                    source_message = await session.get(MessageModel, job.message_id)
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
                            if source_message is not None
                            else None,
                            mention_participant_ids=[
                                str(value) for value in action.mention_participant_ids
                            ],
                            text=action.text,
                            sticker_intent=action.sticker_intent,
                            origin=job.trigger,
                        )
                    )
                job.status = (
                    PlanningJobStatus.COMPLETED
                    if candidate.should_respond
                    else PlanningJobStatus.NO_RESPONSE
                )
                return plan.id

    async def latest_confirmed_ambient_response(
        self, conversation_id: UUID
    ) -> datetime | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(func.max(OutboundActionModel.completed_at)).where(
                    OutboundActionModel.conversation_id == conversation_id,
                    OutboundActionModel.origin == ParticipationTrigger.AMBIENT,
                    OutboundActionModel.status == OutboundActionStatus.DELIVERED,
                )
            )


async def _regeneration_edit_target(
    session: AsyncSession,
    job: ResponsePlanningJobModel,
    candidate: ResponsePlanCandidate,
) -> MessageModel | None:
    """Resolve authoritative parent presentation and apply the pure edit policy."""

    if job.parent_response_plan_id is None:
        return None
    delivered = list(
        await session.scalars(
            select(OutboundActionModel)
            .where(
                OutboundActionModel.response_plan_id == job.parent_response_plan_id,
                OutboundActionModel.status == OutboundActionStatus.DELIVERED,
            )
            .order_by(OutboundActionModel.sequence_number)
        )
    )
    action = delivered[0] if len(delivered) == 1 else None
    target_id = None
    if action is not None and action.kind == OutboundActionKind.EDIT_TEXT:
        target_id = action.edit_target_message_id
    elif action is not None and action.kind == OutboundActionKind.TEXT:
        target_id = action.delivered_message_id
    target = await session.get(MessageModel, target_id) if target_id else None
    ambiguous = (
        await session.scalar(
            select(OutboundActionModel.id).where(
                OutboundActionModel.edit_target_message_id == target_id,
                OutboundActionModel.status == OutboundActionStatus.DELIVERY_UNKNOWN,
            )
        )
        if target_id is not None
        else None
    )
    facts = EditTargetFacts(
        exactly_one_delivered_text=(
            action is not None
            and action.kind in {OutboundActionKind.TEXT, OutboundActionKind.EDIT_TEXT}
            and target is not None
            and target.message_type == MessageType.TEXT
        ),
        platform_message_id_known=bool(target and target.platform_message_id),
        same_authority=bool(
            action
            and target
            and action.conversation_id == job.conversation_id
            and target.conversation_id == job.conversation_id
        ),
        target_content_available=bool(
            target
            and target.direction == MessageDirection.OUTGOING
            and target.content_redacted_at is None
        ),
        ambiguous_prior_edit=ambiguous is not None,
        deterministically_editable=bool(target and target.outbound_action_id),
    )
    return (
        target
        if choose_regeneration_presentation(candidate, facts)
        == RegenerationPresentation.EDIT_EXISTING
        else None
    )
