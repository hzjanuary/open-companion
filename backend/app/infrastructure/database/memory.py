"""Authoritative scoped explicit-memory and personal-context persistence."""

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from secrets import token_urlsafe
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.memory import (
    ExplicitMemoryDraft,
    PersonalContextDraft,
    normalize_explicit_memory,
    normalize_personal_context,
)
from app.domain.persistence import (
    ConversationType,
    MemoryDeletionReason,
    MemoryKind,
    MemoryScope,
    MemoryStatus,
    MemoryVisibility,
    PersonalContextKey,
    SemanticMemoryIndexOperation,
)
from app.domain.summary import ConversationSummaryStatus, SummaryInvalidationReason
from app.infrastructure.database.governance import invalidate_export_packages
from app.infrastructure.database.models import (
    ConversationModel,
    ConversationSummaryModel,
    MemoryControlOperationModel,
    MemoryEventModel,
    MemoryItemModel,
    MemoryRecallPolicyModel,
    ParticipantModel,
    PlatformConnectionModel,
    TelegramCommandJobModel,
)
from app.infrastructure.database.semantic_memory import (
    SqlAlchemySemanticMemoryRepository,
)

semantic_memory_jobs = SqlAlchemySemanticMemoryRepository


@dataclass(frozen=True, slots=True)
class MemoryListEntry:
    item: MemoryItemModel
    creator_label: str


@dataclass(frozen=True, slots=True)
class MemoryStatusSummary:
    recall_enabled: bool
    recall_revision: int
    owned_explicit: int
    shared_explicit: int
    personal_context: int


@dataclass(frozen=True, slots=True)
class MemoryMutationResult:
    outcome: str
    public_id: str | None = None
    revision: int | None = None
    affected_count: int = 0
    recall_enabled: bool | None = None


class SqlAlchemyMemoryRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        embedding_version: str | None = None,
        control_batch_size: int = 100,
    ) -> None:
        self._session_factory = session_factory
        self._embedding_version = embedding_version
        self._control_batch_size = control_batch_size

    @property
    def embedding_version(self) -> str | None:
        return self._embedding_version

    async def create(
        self,
        *,
        assistant_id: UUID,
        platform_connection_id: UUID,
        conversation_id: UUID,
        creator_participant_id: UUID,
        source_message_id: UUID,
        source_command_job_id: UUID,
        draft: ExplicitMemoryDraft,
    ) -> MemoryItemModel:
        async with self._session_factory() as session:
            async with session.begin():
                await _lock_command(
                    session,
                    source_command_job_id,
                    participant_id=creator_participant_id,
                    conversation_id=conversation_id,
                    assistant_id=assistant_id,
                    platform_connection_id=platform_connection_id,
                    source_message_id=source_message_id,
                )
                existing = await session.scalar(
                    select(MemoryItemModel).where(
                        MemoryItemModel.source_command_job_id == source_command_job_id
                    )
                )
                if existing is not None:
                    return existing
                conversation, _ = await _lock_scope(
                    session,
                    assistant_id=assistant_id,
                    platform_connection_id=platform_connection_id,
                    conversation_id=conversation_id,
                    participant_id=creator_participant_id,
                )
                item = _new_item(
                    assistant_id=assistant_id,
                    platform_connection_id=platform_connection_id,
                    conversation_id=conversation_id,
                    creator_participant_id=creator_participant_id,
                    source_message_id=source_message_id,
                    source_command_job_id=source_command_job_id,
                    content=draft.content,
                    kind=draft.kind,
                    scope=draft.scope,
                    visibility=draft.visibility,
                )
                session.add(item)
                await session.flush()
                session.add(
                    MemoryEventModel(
                        memory_id=item.id,
                        command_job_id=source_command_job_id,
                        actor_participant_id=creator_participant_id,
                        action_code="created",
                    )
                )
                session.add(
                    _operation(
                        source_command_job_id,
                        creator_participant_id,
                        conversation_id,
                        operation="remember",
                        outcome="created",
                        memory_id=item.id,
                        revision=1,
                    )
                )
                if self._embedding_version is not None:
                    await SqlAlchemySemanticMemoryRepository.schedule(
                        session,
                        item.id,
                        SemanticMemoryIndexOperation.UPSERT,
                        self._embedding_version,
                    )
                await _invalidate_memory_exports(
                    session,
                    participant_id=creator_participant_id,
                    conversation_id=conversation_id,
                    group=draft.scope.value == "group_conversation",
                    now=datetime.now(UTC),
                )
                conversation.memory_privacy_revision += 1
                return item

    async def create_personal_context(
        self,
        *,
        assistant_id: UUID,
        platform_connection_id: UUID,
        conversation_id: UUID,
        creator_participant_id: UUID,
        source_message_id: UUID,
        source_command_job_id: UUID,
        draft: PersonalContextDraft,
    ) -> MemoryMutationResult:
        async with self._session_factory() as session:
            async with session.begin():
                await _lock_command(
                    session,
                    source_command_job_id,
                    participant_id=creator_participant_id,
                    conversation_id=conversation_id,
                    assistant_id=assistant_id,
                    platform_connection_id=platform_connection_id,
                    source_message_id=source_message_id,
                )
                prior = await _existing_operation(session, source_command_job_id)
                if prior is not None:
                    return await _operation_result(session, prior)
                conversation, _ = await _lock_scope(
                    session,
                    assistant_id=assistant_id,
                    platform_connection_id=platform_connection_id,
                    conversation_id=conversation_id,
                    participant_id=creator_participant_id,
                )
                if conversation.conversation_type != ConversationType.PRIVATE:
                    session.add(
                        _operation(
                            source_command_job_id,
                            creator_participant_id,
                            conversation_id,
                            operation="context_create",
                            outcome="scope_denied",
                        )
                    )
                    return MemoryMutationResult("scope_denied")
                existing = await session.scalar(
                    select(MemoryItemModel).where(
                        MemoryItemModel.creator_participant_id
                        == creator_participant_id,
                        MemoryItemModel.conversation_id == conversation_id,
                        MemoryItemModel.kind == MemoryKind.PERSONAL_CONTEXT,
                        MemoryItemModel.context_key == draft.context_key,
                        MemoryItemModel.status == MemoryStatus.ACTIVE,
                    )
                )
                if existing is not None:
                    session.add(
                        _operation(
                            source_command_job_id,
                            creator_participant_id,
                            conversation_id,
                            operation="context_create",
                            outcome="conflict",
                            memory_id=existing.id,
                            revision=existing.revision,
                        )
                    )
                    return MemoryMutationResult(
                        "conflict", existing.public_id, existing.revision
                    )
                item = _new_item(
                    assistant_id=assistant_id,
                    platform_connection_id=platform_connection_id,
                    conversation_id=conversation_id,
                    creator_participant_id=creator_participant_id,
                    source_message_id=source_message_id,
                    source_command_job_id=source_command_job_id,
                    content=draft.content,
                    kind=draft.kind,
                    scope=draft.scope,
                    visibility=draft.visibility,
                    context_key=draft.context_key,
                )
                session.add(item)
                await session.flush()
                session.add(
                    MemoryEventModel(
                        memory_id=item.id,
                        command_job_id=source_command_job_id,
                        actor_participant_id=creator_participant_id,
                        action_code="personal_context_created",
                    )
                )
                session.add(
                    _operation(
                        source_command_job_id,
                        creator_participant_id,
                        conversation_id,
                        operation="context_create",
                        outcome="created",
                        memory_id=item.id,
                        revision=1,
                    )
                )
                await _invalidate_memory_exports(
                    session,
                    participant_id=creator_participant_id,
                    conversation_id=conversation_id,
                    group=False,
                    now=datetime.now(UTC),
                )
                conversation.memory_privacy_revision += 1
                return MemoryMutationResult("created", item.public_id, 1)

    async def active_for_conversation(
        self,
        *,
        assistant_id: UUID,
        platform_connection_id: UUID,
        conversation_id: UUID,
        viewer_participant_id: UUID | None = None,
        limit: int = 10,
    ) -> list[MemoryListEntry]:
        now = datetime.now(UTC)
        visibility = [MemoryItemModel.visibility == MemoryVisibility.SAME_CONVERSATION]
        if viewer_participant_id is not None:
            visibility.append(
                (MemoryItemModel.visibility == MemoryVisibility.CREATOR_ONLY)
                & (MemoryItemModel.creator_participant_id == viewer_participant_id)
            )
        async with self._session_factory() as session:
            if viewer_participant_id is not None:
                conversation, _ = await _validate_scope(
                    session,
                    assistant_id=assistant_id,
                    platform_connection_id=platform_connection_id,
                    conversation_id=conversation_id,
                    participant_id=viewer_participant_id,
                )
                if conversation.conversation_type != ConversationType.PRIVATE:
                    visibility = visibility[:1]
            rows = await session.execute(
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
                    ParticipantModel.id == MemoryItemModel.creator_participant_id,
                )
                .where(
                    MemoryItemModel.assistant_id == assistant_id,
                    MemoryItemModel.platform_connection_id == platform_connection_id,
                    MemoryItemModel.conversation_id == conversation_id,
                    MemoryItemModel.status == MemoryStatus.ACTIVE,
                    or_(*visibility),
                    MemoryItemModel.platform_connection_id
                    == ConversationModel.platform_connection_id,
                    MemoryItemModel.assistant_id
                    == PlatformConnectionModel.assistant_id,
                    or_(
                        MemoryItemModel.expires_at.is_(None),
                        MemoryItemModel.expires_at > now,
                    ),
                )
                .order_by(
                    MemoryItemModel.updated_at.desc(),
                    MemoryItemModel.revision.desc(),
                    MemoryItemModel.id.desc(),
                )
                .limit(limit)
            )
            return [
                MemoryListEntry(
                    item=item,
                    creator_label=(
                        "Deleted user"
                        if participant is None
                        or participant.privacy_deleted_at is not None
                        else participant.display_name
                    ),
                )
                for item, participant in rows
            ]

    async def status_for_participant(
        self,
        *,
        assistant_id: UUID,
        platform_connection_id: UUID,
        conversation_id: UUID,
        participant_id: UUID,
    ) -> MemoryStatusSummary:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            await _validate_scope(
                session,
                assistant_id=assistant_id,
                platform_connection_id=platform_connection_id,
                conversation_id=conversation_id,
                participant_id=participant_id,
            )
            policy = await session.scalar(
                select(MemoryRecallPolicyModel).where(
                    MemoryRecallPolicyModel.participant_id == participant_id,
                    MemoryRecallPolicyModel.conversation_id == conversation_id,
                )
            )
            base = (
                MemoryItemModel.assistant_id == assistant_id,
                MemoryItemModel.platform_connection_id == platform_connection_id,
                MemoryItemModel.conversation_id == conversation_id,
                MemoryItemModel.status == MemoryStatus.ACTIVE,
                or_(
                    MemoryItemModel.expires_at.is_(None),
                    MemoryItemModel.expires_at > now,
                ),
            )
            owned = await session.scalar(
                select(func.count(MemoryItemModel.id)).where(
                    *base,
                    MemoryItemModel.kind == MemoryKind.EXPLICIT_FACT,
                    MemoryItemModel.creator_participant_id == participant_id,
                )
            )
            shared = await session.scalar(
                select(func.count(MemoryItemModel.id)).where(
                    *base,
                    MemoryItemModel.kind == MemoryKind.EXPLICIT_FACT,
                    MemoryItemModel.visibility == MemoryVisibility.SAME_CONVERSATION,
                )
            )
            personal = await session.scalar(
                select(func.count(MemoryItemModel.id)).where(
                    *base,
                    MemoryItemModel.kind == MemoryKind.PERSONAL_CONTEXT,
                    MemoryItemModel.creator_participant_id == participant_id,
                )
            )
            return MemoryStatusSummary(
                recall_enabled=True if policy is None else policy.enabled,
                recall_revision=0 if policy is None else policy.revision,
                owned_explicit=int(owned or 0),
                shared_explicit=int(shared or 0),
                personal_context=int(personal or 0),
            )

    async def count_active(
        self,
        *,
        assistant_id: UUID,
        platform_connection_id: UUID,
        conversation_id: UUID,
    ) -> int:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            value = await session.scalar(
                select(func.count(MemoryItemModel.id)).where(
                    MemoryItemModel.assistant_id == assistant_id,
                    MemoryItemModel.platform_connection_id == platform_connection_id,
                    MemoryItemModel.conversation_id == conversation_id,
                    MemoryItemModel.status == MemoryStatus.ACTIVE,
                    MemoryItemModel.kind == MemoryKind.EXPLICIT_FACT,
                    MemoryItemModel.visibility == MemoryVisibility.SAME_CONVERSATION,
                    or_(
                        MemoryItemModel.expires_at.is_(None),
                        MemoryItemModel.expires_at > now,
                    ),
                )
            )
            return int(value or 0)

    async def resolve_active(
        self,
        *,
        assistant_id: UUID,
        platform_connection_id: UUID,
        conversation_id: UUID,
        public_id: str,
    ) -> MemoryItemModel | None:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            value = await session.scalar(
                select(MemoryItemModel).where(
                    MemoryItemModel.assistant_id == assistant_id,
                    MemoryItemModel.platform_connection_id == platform_connection_id,
                    MemoryItemModel.conversation_id == conversation_id,
                    MemoryItemModel.public_id == public_id,
                    MemoryItemModel.status == MemoryStatus.ACTIVE,
                    MemoryItemModel.kind == MemoryKind.EXPLICIT_FACT,
                    MemoryItemModel.visibility == MemoryVisibility.SAME_CONVERSATION,
                    or_(
                        MemoryItemModel.expires_at.is_(None),
                        MemoryItemModel.expires_at > now,
                    ),
                )
            )
            return value if isinstance(value, MemoryItemModel) else None

    async def update_owned(
        self,
        *,
        assistant_id: UUID,
        platform_connection_id: UUID,
        conversation_id: UUID,
        actor_id: UUID,
        command_job_id: UUID,
        public_id: str,
        expected_revision: int,
        content: str,
    ) -> MemoryMutationResult:
        async with self._session_factory() as session:
            async with session.begin():
                await _lock_command(
                    session,
                    command_job_id,
                    participant_id=actor_id,
                    conversation_id=conversation_id,
                    assistant_id=assistant_id,
                    platform_connection_id=platform_connection_id,
                )
                prior = await _existing_operation(session, command_job_id)
                if prior is not None:
                    return await _operation_result(session, prior)
                conversation, _ = await _lock_scope(
                    session,
                    assistant_id=assistant_id,
                    platform_connection_id=platform_connection_id,
                    conversation_id=conversation_id,
                    participant_id=actor_id,
                )
                item = await _lock_memory(
                    session,
                    conversation_id,
                    public_id,
                    assistant_id=assistant_id,
                    platform_connection_id=platform_connection_id,
                )
                if item is None or item.status != MemoryStatus.ACTIVE:
                    result = MemoryMutationResult("missing")
                elif item.creator_participant_id != actor_id:
                    result = MemoryMutationResult("denied")
                elif item.revision != expected_revision:
                    result = MemoryMutationResult(
                        "conflict", item.public_id, item.revision
                    )
                else:
                    if item.kind == MemoryKind.PERSONAL_CONTEXT:
                        assert item.context_key is not None
                        normalized = normalize_personal_context(
                            item.context_key.value, content
                        ).content
                    else:
                        normalized = normalize_explicit_memory(
                            content, item.scope
                        ).content
                    item.content = normalized
                    item.normalized_content_hash = sha256(
                        normalized.encode()
                    ).hexdigest()
                    item.revision += 1
                    session.add(
                        MemoryEventModel(
                            memory_id=item.id,
                            command_job_id=command_job_id,
                            actor_participant_id=actor_id,
                            action_code="updated",
                        )
                    )
                    if item.kind == MemoryKind.EXPLICIT_FACT:
                        await semantic_memory_jobs.schedule_upserts_for_memory(
                            session,
                            item.id,
                            self._embedding_version,
                        )
                    await _invalidate_memory_exports(
                        session,
                        participant_id=actor_id,
                        conversation_id=conversation_id,
                        group=item.scope.value == "group_conversation",
                        now=datetime.now(UTC),
                    )
                    conversation.memory_privacy_revision += 1
                    result = MemoryMutationResult(
                        "updated", item.public_id, item.revision
                    )
                session.add(
                    _operation(
                        command_job_id,
                        actor_id,
                        conversation_id,
                        operation="update",
                        outcome=result.outcome,
                        memory_id=item.id if item is not None else None,
                        revision=result.revision,
                    )
                )
                return result

    async def delete_owned(
        self,
        *,
        assistant_id: UUID,
        platform_connection_id: UUID,
        conversation_id: UUID,
        actor_id: UUID,
        command_job_id: UUID,
        public_id: str,
        expected_revision: int,
    ) -> MemoryMutationResult:
        return await self._delete_internal(
            assistant_id=assistant_id,
            platform_connection_id=platform_connection_id,
            conversation_id=conversation_id,
            actor_id=actor_id,
            command_job_id=command_job_id,
            public_id=public_id,
            expected_revision=expected_revision,
            require_owner=True,
            explicit_only=False,
            reason=MemoryDeletionReason.CREATOR_REQUEST,
        )

    async def delete(
        self,
        *,
        assistant_id: UUID,
        platform_connection_id: UUID,
        conversation_id: UUID,
        public_id: str,
        actor_id: UUID,
        reason: MemoryDeletionReason,
        command_job_id: UUID | None = None,
    ) -> bool:
        result = await self._delete_internal(
            assistant_id=assistant_id,
            platform_connection_id=platform_connection_id,
            conversation_id=conversation_id,
            actor_id=actor_id,
            command_job_id=command_job_id,
            public_id=public_id,
            expected_revision=None,
            require_owner=reason == MemoryDeletionReason.CREATOR_REQUEST,
            explicit_only=True,
            reason=reason,
        )
        return result.outcome == "deleted"

    async def _delete_internal(
        self,
        *,
        assistant_id: UUID,
        platform_connection_id: UUID,
        conversation_id: UUID,
        actor_id: UUID,
        command_job_id: UUID | None,
        public_id: str,
        expected_revision: int | None,
        require_owner: bool,
        explicit_only: bool,
        reason: MemoryDeletionReason,
    ) -> MemoryMutationResult:
        async with self._session_factory() as session:
            async with session.begin():
                if command_job_id is not None:
                    await _lock_command(
                        session,
                        command_job_id,
                        participant_id=actor_id,
                        conversation_id=conversation_id,
                        assistant_id=assistant_id,
                        platform_connection_id=platform_connection_id,
                    )
                    prior = await _existing_operation(session, command_job_id)
                    if prior is not None:
                        return await _operation_result(session, prior)
                conversation, _ = await _lock_scope(
                    session,
                    assistant_id=assistant_id,
                    platform_connection_id=platform_connection_id,
                    conversation_id=conversation_id,
                    participant_id=actor_id,
                )
                item = await _lock_memory(
                    session,
                    conversation_id,
                    public_id,
                    assistant_id=assistant_id,
                    platform_connection_id=platform_connection_id,
                )
                if item is None or item.status != MemoryStatus.ACTIVE:
                    result = MemoryMutationResult("missing")
                elif explicit_only and item.kind != MemoryKind.EXPLICIT_FACT:
                    result = MemoryMutationResult("denied")
                elif require_owner and item.creator_participant_id != actor_id:
                    result = MemoryMutationResult("denied")
                elif (
                    expected_revision is not None and item.revision != expected_revision
                ):
                    result = MemoryMutationResult(
                        "conflict", item.public_id, item.revision
                    )
                else:
                    _redact_item(item, datetime.now(UTC), reason)
                    session.add(
                        MemoryEventModel(
                            memory_id=item.id,
                            command_job_id=command_job_id,
                            actor_participant_id=actor_id,
                            action_code="deleted",
                            deletion_reason=reason.value,
                        )
                    )
                    if item.kind == MemoryKind.EXPLICIT_FACT:
                        await semantic_memory_jobs.schedule_deletes_for_memory(
                            session, item.id, self._embedding_version
                        )
                    await _invalidate_memory_exports(
                        session,
                        participant_id=item.creator_participant_id,
                        conversation_id=conversation_id,
                        group=item.scope.value == "group_conversation",
                        now=datetime.now(UTC),
                    )
                    conversation.memory_privacy_revision += 1
                    result = MemoryMutationResult(
                        "deleted", item.public_id, item.revision
                    )
                if command_job_id is not None:
                    session.add(
                        _operation(
                            command_job_id,
                            actor_id,
                            conversation_id,
                            operation="delete",
                            outcome=result.outcome,
                            memory_id=item.id if item is not None else None,
                            revision=result.revision,
                        )
                    )
                return result

    async def clear_owned(
        self,
        *,
        assistant_id: UUID,
        platform_connection_id: UUID,
        conversation_id: UUID,
        actor_id: UUID,
        command_job_id: UUID,
    ) -> MemoryMutationResult:
        """Clear in bounded committed batches; replay resumes one operation."""

        while True:
            async with self._session_factory() as session:
                async with session.begin():
                    await _lock_command(
                        session,
                        command_job_id,
                        participant_id=actor_id,
                        conversation_id=conversation_id,
                        assistant_id=assistant_id,
                        platform_connection_id=platform_connection_id,
                    )
                    operation = await _existing_operation(
                        session, command_job_id, lock=True
                    )
                    if operation is not None and operation.status == "complete":
                        return await _operation_result(session, operation)
                    conversation, _ = await _lock_scope(
                        session,
                        assistant_id=assistant_id,
                        platform_connection_id=platform_connection_id,
                        conversation_id=conversation_id,
                        participant_id=actor_id,
                    )
                    if operation is None:
                        operation = _operation(
                            command_job_id,
                            actor_id,
                            conversation_id,
                            operation="clear",
                            outcome="cleared",
                            status="in_progress",
                        )
                        session.add(operation)
                        await session.flush()
                    rows = list(
                        await session.scalars(
                            select(MemoryItemModel)
                            .where(
                                MemoryItemModel.assistant_id == assistant_id,
                                MemoryItemModel.platform_connection_id
                                == platform_connection_id,
                                MemoryItemModel.conversation_id == conversation_id,
                                MemoryItemModel.creator_participant_id == actor_id,
                                MemoryItemModel.status == MemoryStatus.ACTIVE,
                            )
                            .order_by(MemoryItemModel.created_at, MemoryItemModel.id)
                            .limit(self._control_batch_size)
                            .with_for_update()
                        )
                    )
                    if not rows:
                        operation.status = "complete"
                        return await _operation_result(session, operation)
                    current = datetime.now(UTC)
                    for item in rows:
                        _redact_item(
                            item, current, MemoryDeletionReason.CREATOR_REQUEST
                        )
                        if item.kind == MemoryKind.EXPLICIT_FACT:
                            await semantic_memory_jobs.schedule_deletes_for_memory(
                                session, item.id, self._embedding_version
                            )
                    operation.affected_count += len(rows)
                    session.add(
                        MemoryEventModel(
                            command_job_id=command_job_id,
                            actor_participant_id=actor_id,
                            action_code="cleared_owned_batch",
                            deletion_reason=MemoryDeletionReason.CREATOR_REQUEST.value,
                            affected_count=len(rows),
                        )
                    )
                    await _invalidate_memory_exports(
                        session,
                        participant_id=actor_id,
                        conversation_id=conversation_id,
                        group=any(
                            item.scope.value == "group_conversation" for item in rows
                        ),
                        now=current,
                    )
                    conversation.memory_privacy_revision += 1

    async def recall_status(
        self,
        *,
        assistant_id: UUID,
        platform_connection_id: UUID,
        conversation_id: UUID,
        participant_id: UUID,
    ) -> MemoryMutationResult:
        async with self._session_factory() as session:
            await _validate_scope(
                session,
                assistant_id=assistant_id,
                platform_connection_id=platform_connection_id,
                conversation_id=conversation_id,
                participant_id=participant_id,
            )
            row = await session.scalar(
                select(MemoryRecallPolicyModel).where(
                    MemoryRecallPolicyModel.participant_id == participant_id,
                    MemoryRecallPolicyModel.conversation_id == conversation_id,
                )
            )
            return MemoryMutationResult(
                "unchanged",
                revision=0 if row is None else row.revision,
                recall_enabled=True if row is None else row.enabled,
            )

    async def set_recall(
        self,
        *,
        assistant_id: UUID,
        platform_connection_id: UUID,
        conversation_id: UUID,
        participant_id: UUID,
        command_job_id: UUID,
        enabled: bool,
    ) -> MemoryMutationResult:
        async with self._session_factory() as session:
            async with session.begin():
                await _lock_command(
                    session,
                    command_job_id,
                    participant_id=participant_id,
                    conversation_id=conversation_id,
                    assistant_id=assistant_id,
                    platform_connection_id=platform_connection_id,
                )
                prior = await _existing_operation(session, command_job_id)
                if prior is not None:
                    return await _operation_result(session, prior)
                conversation, _ = await _lock_scope(
                    session,
                    assistant_id=assistant_id,
                    platform_connection_id=platform_connection_id,
                    conversation_id=conversation_id,
                    participant_id=participant_id,
                )
                row = await session.scalar(
                    select(MemoryRecallPolicyModel)
                    .where(
                        MemoryRecallPolicyModel.participant_id == participant_id,
                        MemoryRecallPolicyModel.conversation_id == conversation_id,
                    )
                    .with_for_update()
                )
                changed = (row is None and not enabled) or (
                    row is not None and row.enabled != enabled
                )
                if row is None and not enabled:
                    row = MemoryRecallPolicyModel(
                        assistant_id=assistant_id,
                        platform_connection_id=platform_connection_id,
                        conversation_id=conversation_id,
                        participant_id=participant_id,
                        enabled=enabled,
                        revision=1,
                        source_command_job_id=command_job_id,
                    )
                    session.add(row)
                    revision = 1
                elif row is None:
                    revision = 0
                elif changed:
                    row.enabled = enabled
                    row.revision += 1
                    row.source_command_job_id = command_job_id
                    revision = row.revision
                else:
                    revision = row.revision
                outcome = (
                    "enabled"
                    if enabled and changed
                    else "disabled"
                    if changed
                    else "unchanged"
                )
                session.add(
                    MemoryEventModel(
                        command_job_id=command_job_id,
                        actor_participant_id=participant_id,
                        action_code="recall_enabled" if enabled else "recall_disabled",
                    )
                )
                session.add(
                    _operation(
                        command_job_id,
                        participant_id,
                        conversation_id,
                        operation="recall_enable" if enabled else "recall_disable",
                        outcome=outcome,
                        revision=revision or None,
                        recall_enabled=enabled,
                    )
                )
                if changed:
                    await _invalidate_memory_exports(
                        session,
                        participant_id=participant_id,
                        conversation_id=conversation_id,
                        group=False,
                        now=datetime.now(UTC),
                    )
                    conversation.memory_privacy_revision += 1
                return MemoryMutationResult(
                    outcome, revision=revision, recall_enabled=enabled
                )

    async def reset_group(
        self,
        *,
        assistant_id: UUID,
        platform_connection_id: UUID,
        conversation_id: UUID,
        actor_id: UUID,
        command_job_id: UUID,
    ) -> int:
        """Redact shared group facts; never touch creator-private context."""

        now = datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                await _lock_command(
                    session,
                    command_job_id,
                    participant_id=actor_id,
                    conversation_id=conversation_id,
                    assistant_id=assistant_id,
                    platform_connection_id=platform_connection_id,
                )
                conversation, _ = await _lock_scope(
                    session,
                    assistant_id=assistant_id,
                    platform_connection_id=platform_connection_id,
                    conversation_id=conversation_id,
                    participant_id=actor_id,
                )
                await invalidate_export_packages(
                    session,
                    scope="group",
                    conversation_id=conversation_id,
                    reason="group_reset",
                    now=now,
                )
                rows = list(
                    await session.scalars(
                        select(MemoryItemModel)
                        .where(
                            MemoryItemModel.assistant_id == assistant_id,
                            MemoryItemModel.platform_connection_id
                            == platform_connection_id,
                            MemoryItemModel.conversation_id == conversation_id,
                            MemoryItemModel.kind == MemoryKind.EXPLICIT_FACT,
                            MemoryItemModel.visibility
                            == MemoryVisibility.SAME_CONVERSATION,
                            MemoryItemModel.status == MemoryStatus.ACTIVE,
                        )
                        .with_for_update()
                    )
                )
                creators = {item.creator_participant_id for item in rows}
                for item in rows:
                    _redact_item(item, now, MemoryDeletionReason.ADMINISTRATOR_RESET)
                    await semantic_memory_jobs.schedule_deletes_for_memory(
                        session, item.id, self._embedding_version
                    )
                for creator_id in creators:
                    await invalidate_export_packages(
                        session,
                        scope="subject",
                        participant_ids=[creator_id],
                        reason="group_reset",
                        now=now,
                    )
                count = len(rows)
                existing_event = await session.scalar(
                    select(MemoryEventModel.id).where(
                        MemoryEventModel.command_job_id == command_job_id,
                        MemoryEventModel.action_code == "group_reset",
                    )
                )
                if existing_event is None:
                    session.add(
                        MemoryEventModel(
                            command_job_id=command_job_id,
                            actor_participant_id=actor_id,
                            action_code="group_reset",
                            deletion_reason=(
                                MemoryDeletionReason.ADMINISTRATOR_RESET.value
                            ),
                            affected_count=count,
                        )
                    )
                await session.execute(
                    update(ConversationSummaryModel)
                    .where(
                        ConversationSummaryModel.conversation_id == conversation_id,
                        ConversationSummaryModel.status
                        == ConversationSummaryStatus.COMPLETED,
                    )
                    .values(
                        summary_text=None,
                        status=ConversationSummaryStatus.INVALIDATED,
                        invalidated_at=now,
                        invalidation_reason=SummaryInvalidationReason.GROUP_RESET,
                    )
                )
                if count:
                    conversation.memory_privacy_revision += 1
                return count


def _new_item(
    *,
    assistant_id: UUID,
    platform_connection_id: UUID,
    conversation_id: UUID,
    creator_participant_id: UUID,
    source_message_id: UUID,
    source_command_job_id: UUID,
    content: str,
    kind: MemoryKind,
    scope: MemoryScope,
    visibility: MemoryVisibility,
    context_key: PersonalContextKey | None = None,
) -> MemoryItemModel:
    return MemoryItemModel(
        public_id=token_urlsafe(9).replace("-", "A").replace("_", "B"),
        assistant_id=assistant_id,
        platform_connection_id=platform_connection_id,
        conversation_id=conversation_id,
        creator_participant_id=creator_participant_id,
        kind=kind,
        scope=scope,
        visibility=visibility,
        context_key=context_key,
        revision=1,
        content=content,
        normalized_content_hash=sha256(content.encode()).hexdigest(),
        confidence=1.0,
        source_message_id=source_message_id,
        source_command_job_id=source_command_job_id,
    )


def _operation(
    command_job_id: UUID,
    actor_id: UUID,
    conversation_id: UUID,
    *,
    operation: str,
    outcome: str,
    status: str = "complete",
    memory_id: UUID | None = None,
    revision: int | None = None,
    affected_count: int = 0,
    recall_enabled: bool | None = None,
) -> MemoryControlOperationModel:
    return MemoryControlOperationModel(
        command_job_id=command_job_id,
        actor_participant_id=actor_id,
        conversation_id=conversation_id,
        operation=operation,
        status=status,
        outcome=outcome,
        memory_id=memory_id,
        resulting_revision=revision,
        affected_count=affected_count,
        recall_enabled=recall_enabled,
    )


async def _existing_operation(
    session: AsyncSession, command_job_id: UUID, *, lock: bool = False
) -> MemoryControlOperationModel | None:
    statement = select(MemoryControlOperationModel).where(
        MemoryControlOperationModel.command_job_id == command_job_id
    )
    if lock:
        statement = statement.with_for_update()
    value = await session.scalar(statement)
    return value if isinstance(value, MemoryControlOperationModel) else None


async def _operation_result(
    session: AsyncSession, operation: MemoryControlOperationModel
) -> MemoryMutationResult:
    public_id = None
    if operation.memory_id is not None:
        public_id = await session.scalar(
            select(MemoryItemModel.public_id).where(
                MemoryItemModel.id == operation.memory_id
            )
        )
    return MemoryMutationResult(
        operation.outcome,
        public_id,
        (
            0
            if operation.resulting_revision is None
            and operation.operation in {"recall_enable", "recall_disable"}
            else operation.resulting_revision
        ),
        operation.affected_count,
        operation.recall_enabled,
    )


async def _lock_command(
    session: AsyncSession,
    command_job_id: UUID,
    *,
    participant_id: UUID,
    conversation_id: UUID,
    assistant_id: UUID,
    platform_connection_id: UUID,
    source_message_id: UUID | None = None,
) -> None:
    row = await session.scalar(
        select(TelegramCommandJobModel)
        .join(
            ConversationModel,
            ConversationModel.id == TelegramCommandJobModel.conversation_id,
        )
        .join(
            PlatformConnectionModel,
            PlatformConnectionModel.id == ConversationModel.platform_connection_id,
        )
        .where(
            TelegramCommandJobModel.id == command_job_id,
            TelegramCommandJobModel.participant_id == participant_id,
            TelegramCommandJobModel.conversation_id == conversation_id,
            ConversationModel.platform_connection_id == platform_connection_id,
            PlatformConnectionModel.assistant_id == assistant_id,
        )
        .with_for_update(of=TelegramCommandJobModel)
    )
    if row is None or (
        source_message_id is not None and row.message_id != source_message_id
    ):
        raise ValueError("memory command scope is not authorized")


async def _validate_scope(
    session: AsyncSession,
    *,
    assistant_id: UUID,
    platform_connection_id: UUID,
    conversation_id: UUID,
    participant_id: UUID,
) -> tuple[ConversationModel, ParticipantModel]:
    row = (
        await session.execute(
            select(ConversationModel, ParticipantModel)
            .join(
                PlatformConnectionModel,
                PlatformConnectionModel.id == ConversationModel.platform_connection_id,
            )
            .join(
                ParticipantModel,
                ParticipantModel.conversation_id == ConversationModel.id,
            )
            .where(
                ConversationModel.id == conversation_id,
                ConversationModel.platform_connection_id == platform_connection_id,
                PlatformConnectionModel.assistant_id == assistant_id,
                ParticipantModel.id == participant_id,
                ParticipantModel.privacy_deleted_at.is_(None),
            )
        )
    ).first()
    if row is None:
        raise ValueError("memory scope is not authorized")
    return row[0], row[1]


async def _lock_scope(
    session: AsyncSession,
    *,
    assistant_id: UUID,
    platform_connection_id: UUID,
    conversation_id: UUID,
    participant_id: UUID,
) -> tuple[ConversationModel, ParticipantModel]:
    row = (
        await session.execute(
            select(ConversationModel, ParticipantModel)
            .join(
                PlatformConnectionModel,
                PlatformConnectionModel.id == ConversationModel.platform_connection_id,
            )
            .join(
                ParticipantModel,
                ParticipantModel.conversation_id == ConversationModel.id,
            )
            .where(
                ConversationModel.id == conversation_id,
                ConversationModel.platform_connection_id == platform_connection_id,
                PlatformConnectionModel.assistant_id == assistant_id,
                ParticipantModel.id == participant_id,
                ParticipantModel.privacy_deleted_at.is_(None),
            )
            .with_for_update()
        )
    ).first()
    if row is None:
        raise ValueError("memory scope is not authorized")
    return row[0], row[1]


async def _lock_memory(
    session: AsyncSession,
    conversation_id: UUID,
    public_id: str,
    *,
    assistant_id: UUID,
    platform_connection_id: UUID,
) -> MemoryItemModel | None:
    value = await session.scalar(
        select(MemoryItemModel)
        .where(
            MemoryItemModel.conversation_id == conversation_id,
            MemoryItemModel.public_id == public_id,
            MemoryItemModel.assistant_id == assistant_id,
            MemoryItemModel.platform_connection_id == platform_connection_id,
            or_(
                MemoryItemModel.expires_at.is_(None),
                MemoryItemModel.expires_at > datetime.now(UTC),
            ),
        )
        .with_for_update()
    )
    return value if isinstance(value, MemoryItemModel) else None


def _redact_item(
    item: MemoryItemModel, now: datetime, reason: MemoryDeletionReason
) -> None:
    item.status = MemoryStatus.DELETED
    item.content = None
    item.normalized_content_hash = None
    item.deleted_at = now
    item.deletion_reason = reason


async def _invalidate_memory_exports(
    session: AsyncSession,
    *,
    participant_id: UUID,
    conversation_id: UUID,
    group: bool,
    now: datetime,
) -> None:
    await invalidate_export_packages(
        session,
        scope="subject",
        participant_ids=[participant_id],
        reason="memory_changed",
        now=now,
    )
    if group:
        await invalidate_export_packages(
            session,
            scope="group",
            conversation_id=conversation_id,
            reason="memory_changed",
            now=now,
        )
