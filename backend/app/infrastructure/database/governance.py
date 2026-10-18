"""Content-safe persistence for SPEC-025 governance surfaces.

Export and erasure request lifecycles, the temporary single-use export
package, and the content-free governance audit trail.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.governance import (
    ErasureRequestStatus,
    ExportRequestStatus,
    GovernanceAuditEventType,
)
from app.infrastructure.database.models import (
    ControlAuditEventModel,
    GovernanceAuditEventModel,
    GovernanceErasureRequestModel,
    GovernanceExportPackageModel,
    GovernanceExportRequestModel,
)


@dataclass(frozen=True, slots=True)
class GovernanceExportRecord:
    id: UUID
    scope: str
    conversation_id: UUID | None
    participant_id: UUID | None
    tenant_id: UUID | None
    status: str
    categories: tuple[str, ...]
    single_use_token_hash: str | None
    source_command_job_id: UUID | None
    source_control_identity_id: UUID | None
    source_control_request_id: str | None
    available_at: datetime
    attempt_count: int
    expires_at: datetime | None
    completed_at: datetime | None
    delivered_at: datetime | None
    retrieved_at: datetime | None
    failure_reason: str | None
    created: bool = False


@dataclass(frozen=True, slots=True)
class GovernanceExportPackageRecord:
    request_id: UUID
    schema_version: str
    manifest: dict[str, object]
    package: dict[str, object]
    expires_at: datetime
    retrieved_at: datetime | None


@dataclass(frozen=True, slots=True)
class GovernanceErasureRecord:
    id: UUID
    scope: str
    conversation_id: UUID
    participant_id: UUID | None
    status: str
    partial_reason: str | None
    retryable: bool
    requested_via: str
    completed_at: datetime | None
    source_command_job_id: UUID | None
    lease_owner: str | None
    lease_expires_at: datetime | None
    created: bool = False


@dataclass(frozen=True, slots=True)
class SubjectGovernanceSummary:
    export_state: str
    erasure_state: str


@dataclass(frozen=True, slots=True)
class GovernanceStateCounts:
    export_pending: int
    export_retrieved: int
    export_failed: int
    erasure_complete: int
    erasure_partial: int
    erasure_failed: int
    packages_cleared: int
    audit_events: int


class SqlAlchemyGovernanceRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_export_request(
        self,
        *,
        scope: str,
        conversation_id: UUID | None,
        participant_id: UUID | None,
        tenant_id: UUID | None,
        token_hash: str | None,
        categories: tuple[str, ...],
        ttl_days: int,
        source_command_job_id: UUID | None = None,
        source_control_identity_id: UUID | None = None,
        source_control_request_id: str | None = None,
        now: datetime | None = None,
    ) -> GovernanceExportRecord:
        if (source_control_identity_id is None) != (source_control_request_id is None):
            raise ValueError("control export identity and request id must be paired")
        if source_command_job_id is not None and source_control_identity_id is not None:
            raise ValueError("export request must have one durable source identity")
        current = now or datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                created = True
                row: GovernanceExportRequestModel
                if source_command_job_id is None and source_control_identity_id is None:
                    row = GovernanceExportRequestModel(
                        scope=scope,
                        conversation_id=conversation_id,
                        participant_id=participant_id,
                        tenant_id=tenant_id,
                        status=ExportRequestStatus.REQUESTED,
                        categories=list(categories),
                        single_use_token_hash=token_hash,
                        source_command_job_id=None,
                        source_control_identity_id=None,
                        source_control_request_id=None,
                        available_at=current,
                        expires_at=current + timedelta(days=ttl_days),
                    )
                    session.add(row)
                    await session.flush()
                elif source_command_job_id is not None:
                    candidate_id = uuid4()
                    inserted = await session.scalar(
                        insert(GovernanceExportRequestModel)
                        .values(
                            id=candidate_id,
                            scope=scope,
                            conversation_id=conversation_id,
                            participant_id=participant_id,
                            tenant_id=tenant_id,
                            status=ExportRequestStatus.REQUESTED,
                            categories=list(categories),
                            single_use_token_hash=token_hash,
                            source_command_job_id=source_command_job_id,
                            available_at=current,
                            expires_at=current + timedelta(days=ttl_days),
                        )
                        .on_conflict_do_nothing(
                            index_elements=["source_command_job_id"]
                        )
                        .returning(GovernanceExportRequestModel.id)
                    )
                    created = inserted is not None
                    existing = await session.scalar(
                        select(GovernanceExportRequestModel).where(
                            GovernanceExportRequestModel.source_command_job_id
                            == source_command_job_id
                        )
                    )
                    if existing is None:
                        raise RuntimeError("export idempotency lookup failed")
                    row = existing
                else:
                    assert source_control_identity_id is not None
                    assert source_control_request_id is not None
                    candidate_id = uuid4()
                    inserted = await session.scalar(
                        insert(GovernanceExportRequestModel)
                        .values(
                            id=candidate_id,
                            scope=scope,
                            conversation_id=conversation_id,
                            participant_id=participant_id,
                            tenant_id=tenant_id,
                            status=ExportRequestStatus.REQUESTED,
                            categories=list(categories),
                            single_use_token_hash=token_hash,
                            source_control_identity_id=source_control_identity_id,
                            source_control_request_id=source_control_request_id,
                            available_at=current,
                            expires_at=current + timedelta(days=ttl_days),
                        )
                        .on_conflict_do_nothing(
                            index_elements=[
                                "source_control_identity_id",
                                "source_control_request_id",
                            ]
                        )
                        .returning(GovernanceExportRequestModel.id)
                    )
                    created = inserted is not None
                    existing = await session.scalar(
                        select(GovernanceExportRequestModel).where(
                            GovernanceExportRequestModel.source_control_identity_id
                            == source_control_identity_id,
                            GovernanceExportRequestModel.source_control_request_id
                            == source_control_request_id,
                        )
                    )
                    if existing is None:
                        raise RuntimeError("control export idempotency lookup failed")
                    row = existing
                if created:
                    await _record_audit_event_in_session(
                        session,
                        event_type=GovernanceAuditEventType.EXPORT_REQUEST,
                        scope=scope,
                        request_id=str(row.id),
                        conversation_id=conversation_id,
                        participant_id=participant_id,
                        tenant_id=tenant_id,
                        outcome="requested",
                    )
                    if source_control_identity_id is not None:
                        assert source_control_request_id is not None
                        session.add(
                            ControlAuditEventModel(
                                tenant_id=None,
                                actor_identity_id=source_control_identity_id,
                                action="governance.deployment_export",
                                outcome="authorized",
                                resource_type="deployment_export",
                                resource_id=str(row.id),
                                request_id=source_control_request_id,
                                metadata_={"schema_version": "spec-025-v1"},
                            )
                        )
            return _export_record(row, created=created)

    async def issue_export_token(
        self,
        request_id: UUID,
        token_hash: str,
        now: datetime | None = None,
        *,
        control_actor_identity_id: UUID | None = None,
        control_request_id: str | None = None,
    ) -> bool:
        """Persist only a new one-way token hash immediately before delivery."""

        if (control_actor_identity_id is None) != (control_request_id is None):
            raise ValueError("control audit identity and request id must be paired")

        current = now or datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                updated = list(
                    await session.scalars(
                        update(GovernanceExportRequestModel)
                        .where(
                            GovernanceExportRequestModel.id == request_id,
                            GovernanceExportRequestModel.status.in_(
                                [
                                    ExportRequestStatus.REQUESTED,
                                    ExportRequestStatus.IN_PROGRESS,
                                    ExportRequestStatus.COMPLETE,
                                    ExportRequestStatus.DELIVERED,
                                ]
                            ),
                            GovernanceExportRequestModel.expires_at > current,
                            GovernanceExportRequestModel.single_use_token_hash.is_(
                                None
                            ),
                        )
                        .values(single_use_token_hash=token_hash)
                        .returning(GovernanceExportRequestModel.id)
                    )
                )
                if updated and control_actor_identity_id is not None:
                    session.add(
                        ControlAuditEventModel(
                            tenant_id=None,
                            actor_identity_id=control_actor_identity_id,
                            action="governance.deployment_export.credential_issued",
                            outcome="authorized",
                            resource_type="deployment_export",
                            resource_id=str(request_id),
                            request_id=control_request_id,
                            metadata_={"schema_version": "spec-025-v1"},
                        )
                    )
                return bool(updated)

    async def get_export_request(
        self, request_id: UUID
    ) -> GovernanceExportRecord | None:
        async with self._session_factory() as session:
            row = await session.get(GovernanceExportRequestModel, request_id)
            return _export_record(row) if row is not None else None

    async def find_claimable_export_requests(
        self,
        *,
        limit: int,
        max_attempts: int,
        now: datetime | None = None,
    ) -> list[UUID]:
        """Return pending export request ids eligible for async materialization."""

        current = now or datetime.now(UTC)
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(GovernanceExportRequestModel.id)
                .where(
                    or_(
                        GovernanceExportRequestModel.status
                        == ExportRequestStatus.REQUESTED,
                        (
                            GovernanceExportRequestModel.status
                            == ExportRequestStatus.IN_PROGRESS
                        )
                        & (GovernanceExportRequestModel.lease_expires_at <= current),
                    ),
                    GovernanceExportRequestModel.attempt_count < max_attempts,
                    or_(
                        GovernanceExportRequestModel.expires_at.is_(None),
                        GovernanceExportRequestModel.expires_at > current,
                    ),
                    or_(
                        GovernanceExportRequestModel.lease_expires_at.is_(None),
                        GovernanceExportRequestModel.lease_expires_at <= current,
                    ),
                )
                .order_by(
                    GovernanceExportRequestModel.available_at,
                    GovernanceExportRequestModel.id,
                )
                .limit(limit)
            )
            return list(rows)

    async def claim_export_request(
        self,
        *,
        request_id: UUID,
        lease_owner: str,
        lease_seconds: int,
        max_attempts: int,
        now: datetime | None = None,
    ) -> bool:
        """Lease a claimable export request (CAS) for async materialization."""

        current = now or datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                claimed = list(
                    await session.scalars(
                        update(GovernanceExportRequestModel)
                        .where(
                            GovernanceExportRequestModel.id == request_id,
                            or_(
                                GovernanceExportRequestModel.status
                                == ExportRequestStatus.REQUESTED,
                                (
                                    GovernanceExportRequestModel.status
                                    == ExportRequestStatus.IN_PROGRESS
                                )
                                & (
                                    GovernanceExportRequestModel.lease_expires_at
                                    <= current
                                ),
                            ),
                            or_(
                                GovernanceExportRequestModel.lease_expires_at.is_(None),
                                GovernanceExportRequestModel.lease_expires_at
                                <= current,
                            ),
                            GovernanceExportRequestModel.attempt_count < max_attempts,
                            or_(
                                GovernanceExportRequestModel.expires_at.is_(None),
                                GovernanceExportRequestModel.expires_at > current,
                            ),
                        )
                        .values(
                            status=ExportRequestStatus.IN_PROGRESS,
                            lease_owner=lease_owner,
                            lease_expires_at=current + timedelta(seconds=lease_seconds),
                            attempt_count=(
                                GovernanceExportRequestModel.attempt_count + 1
                            ),
                        )
                        .returning(GovernanceExportRequestModel.id)
                    )
                )
                return bool(claimed)

    async def complete_export(
        self,
        *,
        request_id: UUID,
        schema_version: str,
        manifest: dict[str, object],
        package: dict[str, object],
        expires_at: datetime,
        lease_owner: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        current = now or datetime.now(UTC)
        conditions = [
            GovernanceExportRequestModel.id == request_id,
            GovernanceExportRequestModel.status == ExportRequestStatus.IN_PROGRESS,
        ]
        if lease_owner is not None:
            conditions.append(GovernanceExportRequestModel.lease_owner == lease_owner)
        async with self._session_factory() as session:
            async with session.begin():
                updated = list(
                    await session.scalars(
                        update(GovernanceExportRequestModel)
                        .where(*conditions)
                        .values(
                            status=ExportRequestStatus.COMPLETE,
                            completed_at=current,
                            lease_owner=None,
                            lease_expires_at=None,
                        )
                        .returning(GovernanceExportRequestModel.id)
                    )
                )
                if not updated:
                    return False
                session.add(
                    GovernanceExportPackageModel(
                        export_request_id=request_id,
                        schema_version=schema_version,
                        manifest=manifest,
                        package=package,
                        expires_at=expires_at,
                    )
                )
                row = await session.get(GovernanceExportRequestModel, request_id)
                if row is not None:
                    await _record_audit_event_in_session(
                        session,
                        event_type=GovernanceAuditEventType.EXPORT_COMPLETE,
                        scope=row.scope,
                        request_id=str(row.id),
                        conversation_id=row.conversation_id,
                        participant_id=row.participant_id,
                        tenant_id=row.tenant_id,
                        outcome="complete",
                    )
                return True

    async def record_export_delivered(
        self, request_id: UUID, now: datetime | None = None
    ) -> bool:
        current = now or datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                updated = list(
                    await session.scalars(
                        update(GovernanceExportRequestModel)
                        .where(
                            GovernanceExportRequestModel.id == request_id,
                            GovernanceExportRequestModel.status
                            == ExportRequestStatus.COMPLETE,
                        )
                        .values(
                            status=ExportRequestStatus.DELIVERED,
                            delivered_at=current,
                        )
                        .returning(GovernanceExportRequestModel.id)
                    )
                )
                return bool(updated)

    async def record_export_failed(
        self,
        *,
        request_id: UUID,
        reason: str,
        max_attempts: int,
        lease_owner: str | None = None,
    ) -> bool:
        async with self._session_factory() as session:
            async with session.begin():
                row = await session.get(
                    GovernanceExportRequestModel, request_id, with_for_update=True
                )
                if row is None:
                    return False
                if lease_owner is not None and row.lease_owner != lease_owner:
                    return False
                row.lease_owner = None
                row.lease_expires_at = None
                row.failure_reason = reason
                if row.attempt_count >= max_attempts:
                    row.status = ExportRequestStatus.FAILED
                else:
                    row.status = ExportRequestStatus.REQUESTED
                await _record_audit_event_in_session(
                    session,
                    event_type=GovernanceAuditEventType.EXPORT_FAILED,
                    scope=row.scope,
                    request_id=str(row.id),
                    conversation_id=row.conversation_id,
                    participant_id=row.participant_id,
                    tenant_id=row.tenant_id,
                    outcome="failed",
                    detail=reason,
                )
                return True

    async def retrieve_export_by_token(
        self, token_hash: str, now: datetime | None = None
    ) -> GovernanceExportPackageRecord | None:
        """Single-use retrieval resolved by token hash (FR-02/FR-03 delivery)."""

        current = now or datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                row = await session.scalar(
                    select(GovernanceExportRequestModel)
                    .where(
                        GovernanceExportRequestModel.single_use_token_hash == token_hash
                    )
                    .with_for_update()
                )
                if row is None:
                    return None
                if row.status not in {
                    ExportRequestStatus.COMPLETE,
                    ExportRequestStatus.DELIVERED,
                }:
                    return None
                if row.expires_at is not None and row.expires_at <= current:
                    return None
                package = await session.scalar(
                    select(GovernanceExportPackageModel).where(
                        GovernanceExportPackageModel.export_request_id == row.id
                    )
                )
                if package is None:
                    return None
                if package.retrieved_at is not None or package.cleared_at is not None:
                    return None
                record = _package_record(package)
                package.retrieved_at = current
                package.cleared_at = current
                package.package = {}
                row.status = ExportRequestStatus.RETRIEVED
                row.retrieved_at = current
                row.single_use_token_hash = None
                await _record_audit_event_in_session(
                    session,
                    event_type=GovernanceAuditEventType.EXPORT_RETRIEVED,
                    scope=row.scope,
                    request_id=str(row.id),
                    conversation_id=row.conversation_id,
                    participant_id=row.participant_id,
                    tenant_id=row.tenant_id,
                    outcome="retrieved",
                )
                return record

    async def expire_stale_exports(
        self, *, limit: int, now: datetime | None = None
    ) -> int:
        """Clear undelivered packages past their TTL and mark requests expired."""

        current = now or datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                stale = (
                    select(GovernanceExportRequestModel)
                    .where(
                        GovernanceExportRequestModel.status.in_(
                            [
                                ExportRequestStatus.REQUESTED,
                                ExportRequestStatus.IN_PROGRESS,
                                ExportRequestStatus.COMPLETE,
                                ExportRequestStatus.DELIVERED,
                            ]
                        ),
                        GovernanceExportRequestModel.expires_at.is_not(None),
                        GovernanceExportRequestModel.expires_at <= current,
                    )
                    .order_by(
                        GovernanceExportRequestModel.expires_at,
                        GovernanceExportRequestModel.id,
                    )
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
                rows = list(await session.scalars(stale))
                if not rows:
                    return 0
                ids = [row.id for row in rows]
                await session.execute(
                    update(GovernanceExportRequestModel)
                    .where(GovernanceExportRequestModel.id.in_(ids))
                    .values(
                        status=ExportRequestStatus.EXPIRED,
                        single_use_token_hash=None,
                        lease_owner=None,
                        lease_expires_at=None,
                    )
                )
                for row in rows:
                    await _record_audit_event_in_session(
                        session,
                        event_type=GovernanceAuditEventType.EXPORT_EXPIRED,
                        scope=row.scope,
                        request_id=str(row.id),
                        conversation_id=row.conversation_id,
                        participant_id=row.participant_id,
                        tenant_id=row.tenant_id,
                        outcome="expired",
                        detail="ttl_expired",
                    )
                cleared = list(
                    await session.scalars(
                        update(GovernanceExportPackageModel)
                        .where(
                            GovernanceExportPackageModel.export_request_id.in_(ids),
                            GovernanceExportPackageModel.cleared_at.is_(None),
                        )
                        .values(
                            package={},
                            cleared_at=current,
                        )
                        .returning(GovernanceExportPackageModel.id)
                    )
                )
                return len(cleared)

    async def create_erasure_request(
        self,
        *,
        scope: str,
        conversation_id: UUID,
        participant_id: UUID | None,
        requested_via: str,
        source_command_job_id: UUID | None = None,
        now: datetime | None = None,
    ) -> GovernanceErasureRecord:
        async with self._session_factory() as session:
            async with session.begin():
                created = True
                row: GovernanceErasureRequestModel
                if source_command_job_id is None:
                    row = GovernanceErasureRequestModel(
                        scope=scope,
                        conversation_id=conversation_id,
                        participant_id=participant_id,
                        status=ErasureRequestStatus.REQUESTED,
                        requested_via=requested_via,
                    )
                    session.add(row)
                    await session.flush()
                else:
                    candidate_id = uuid4()
                    inserted = await session.scalar(
                        insert(GovernanceErasureRequestModel)
                        .values(
                            id=candidate_id,
                            scope=scope,
                            conversation_id=conversation_id,
                            participant_id=participant_id,
                            status=ErasureRequestStatus.REQUESTED,
                            requested_via=requested_via,
                            source_command_job_id=source_command_job_id,
                        )
                        .on_conflict_do_nothing(
                            index_elements=["source_command_job_id"]
                        )
                        .returning(GovernanceErasureRequestModel.id)
                    )
                    created = inserted is not None
                    existing = await session.scalar(
                        select(GovernanceErasureRequestModel).where(
                            GovernanceErasureRequestModel.source_command_job_id
                            == source_command_job_id
                        )
                    )
                    if existing is None:
                        raise RuntimeError("erasure idempotency lookup failed")
                    row = existing
                if created:
                    await _record_audit_event_in_session(
                        session,
                        event_type=GovernanceAuditEventType.ERASURE_REQUEST,
                        scope=scope,
                        request_id=str(row.id),
                        conversation_id=conversation_id,
                        participant_id=participant_id,
                        tenant_id=None,
                        outcome="requested",
                    )
                return _erasure_record(row, created=created)

    async def mark_erasure_in_progress(
        self,
        request_id: UUID,
        *,
        lease_owner: str,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> bool:
        current = now or datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                updated = list(
                    await session.scalars(
                        update(GovernanceErasureRequestModel)
                        .where(
                            GovernanceErasureRequestModel.id == request_id,
                            GovernanceErasureRequestModel.status.in_(
                                [
                                    ErasureRequestStatus.REQUESTED,
                                    ErasureRequestStatus.PARTIAL,
                                    ErasureRequestStatus.FAILED,
                                    ErasureRequestStatus.IN_PROGRESS,
                                ]
                            ),
                            or_(
                                GovernanceErasureRequestModel.status
                                != ErasureRequestStatus.IN_PROGRESS,
                                GovernanceErasureRequestModel.lease_expires_at
                                <= current,
                                GovernanceErasureRequestModel.lease_owner
                                == lease_owner,
                            ),
                        )
                        .values(
                            status=ErasureRequestStatus.IN_PROGRESS,
                            lease_owner=lease_owner,
                            lease_expires_at=current + timedelta(seconds=lease_seconds),
                        )
                        .returning(GovernanceErasureRequestModel.id)
                    )
                )
                if updated:
                    row = await session.get(GovernanceErasureRequestModel, request_id)
                    if row is not None:
                        await _record_audit_event_in_session(
                            session,
                            event_type=GovernanceAuditEventType.ERASURE_IN_PROGRESS,
                            scope=row.scope,
                            request_id=str(row.id),
                            conversation_id=row.conversation_id,
                            participant_id=row.participant_id,
                            tenant_id=None,
                            outcome="in_progress",
                        )
                return bool(updated)

    async def fail_stale_erasure_requests(self, *, limit: int) -> list[str]:
        """Close crash-stranded in-progress erasures for safe command replay."""

        current = datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                rows = list(
                    await session.scalars(
                        select(GovernanceErasureRequestModel)
                        .where(
                            GovernanceErasureRequestModel.status
                            == ErasureRequestStatus.IN_PROGRESS,
                            GovernanceErasureRequestModel.retryable.is_(True),
                            GovernanceErasureRequestModel.lease_expires_at.is_not(None),
                            GovernanceErasureRequestModel.lease_expires_at <= current,
                        )
                        .order_by(
                            GovernanceErasureRequestModel.lease_expires_at,
                            GovernanceErasureRequestModel.id,
                        )
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                )
                for row in rows:
                    row.status = ErasureRequestStatus.FAILED
                    row.partial_reason = "worker_restart"
                    row.lease_owner = None
                    row.lease_expires_at = None
                    await _record_audit_event_in_session(
                        session,
                        event_type=GovernanceAuditEventType.ERASURE_FAILED,
                        scope=row.scope,
                        request_id=str(row.id),
                        conversation_id=row.conversation_id,
                        participant_id=row.participant_id,
                        tenant_id=None,
                        outcome="failed",
                        detail="worker_restart",
                    )
                return [row.scope for row in rows]

    async def get_erasure_request(
        self, request_id: UUID
    ) -> GovernanceErasureRecord | None:
        async with self._session_factory() as session:
            row = await session.get(GovernanceErasureRequestModel, request_id)
            return _erasure_record(row) if row is not None else None

    async def complete_erasure_request(
        self,
        request_id: UUID,
        *,
        partial: bool = False,
        partial_reason: str | None = None,
        retryable: bool = True,
        lease_owner: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        current = now or datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                row = await session.get(
                    GovernanceErasureRequestModel, request_id, with_for_update=True
                )
                if row is None:
                    return False
                if lease_owner is not None and row.lease_owner != lease_owner:
                    return False
                if partial:
                    row.status = ErasureRequestStatus.PARTIAL
                    row.partial_reason = partial_reason
                    row.retryable = retryable
                    event_type = GovernanceAuditEventType.ERASURE_PARTIAL
                    outcome = "partial"
                    detail = partial_reason
                else:
                    row.status = ErasureRequestStatus.COMPLETE
                    row.completed_at = current
                    event_type = GovernanceAuditEventType.ERASURE_COMPLETE
                    outcome = "complete"
                    detail = None
                row.lease_owner = None
                row.lease_expires_at = None
                await _record_audit_event_in_session(
                    session,
                    event_type=event_type,
                    scope=row.scope,
                    request_id=str(row.id),
                    conversation_id=row.conversation_id,
                    participant_id=row.participant_id,
                    tenant_id=None,
                    outcome=outcome,
                    detail=detail,
                )
                return True

    async def record_erasure_failed(
        self,
        request_id: UUID,
        *,
        retryable: bool = True,
        lease_owner: str | None = None,
    ) -> bool:
        async with self._session_factory() as session:
            async with session.begin():
                row = await session.get(
                    GovernanceErasureRequestModel, request_id, with_for_update=True
                )
                if row is None:
                    return False
                if lease_owner is not None and row.lease_owner != lease_owner:
                    return False
                row.status = ErasureRequestStatus.FAILED
                row.retryable = retryable
                row.lease_owner = None
                row.lease_expires_at = None
                await _record_audit_event_in_session(
                    session,
                    event_type=GovernanceAuditEventType.ERASURE_FAILED,
                    scope=row.scope,
                    request_id=str(row.id),
                    conversation_id=row.conversation_id,
                    participant_id=row.participant_id,
                    tenant_id=None,
                    outcome="failed",
                )
                return True

    async def subject_summary(
        self, *, conversation_id: UUID, participant_id: UUID
    ) -> SubjectGovernanceSummary:
        async with self._session_factory() as session:
            export_state = await session.scalar(
                select(GovernanceExportRequestModel.status)
                .where(
                    GovernanceExportRequestModel.conversation_id == conversation_id,
                    GovernanceExportRequestModel.participant_id == participant_id,
                    GovernanceExportRequestModel.scope == "subject",
                )
                .order_by(GovernanceExportRequestModel.created_at.desc())
                .limit(1)
            )
            erasure_state = await session.scalar(
                select(GovernanceErasureRequestModel.status)
                .where(
                    GovernanceErasureRequestModel.conversation_id == conversation_id,
                    GovernanceErasureRequestModel.participant_id == participant_id,
                    GovernanceErasureRequestModel.scope == "subject",
                )
                .order_by(GovernanceErasureRequestModel.created_at.desc())
                .limit(1)
            )
            return SubjectGovernanceSummary(
                export_state=str(export_state or "none"),
                erasure_state=str(erasure_state or "none"),
            )

    async def purge_audit_events(self, before: datetime, *, limit: int) -> int:
        from sqlalchemy import delete

        async with self._session_factory() as session:
            async with session.begin():
                purged = list(
                    await session.scalars(
                        delete(GovernanceAuditEventModel)
                        .where(
                            GovernanceAuditEventModel.id.in_(
                                select(GovernanceAuditEventModel.id)
                                .where(GovernanceAuditEventModel.created_at < before)
                                .order_by(
                                    GovernanceAuditEventModel.created_at,
                                    GovernanceAuditEventModel.id,
                                )
                                .limit(limit)
                            )
                        )
                        .returning(GovernanceAuditEventModel.id)
                    )
                )
                return len(purged)

    async def governance_state_counts(self) -> GovernanceStateCounts:
        async with self._session_factory() as session:
            async with session.begin():
                export_pending = await session.scalar(
                    select(func.count())
                    .select_from(GovernanceExportRequestModel)
                    .where(
                        GovernanceExportRequestModel.status.in_(
                            [
                                ExportRequestStatus.REQUESTED,
                                ExportRequestStatus.IN_PROGRESS,
                                ExportRequestStatus.COMPLETE,
                                ExportRequestStatus.DELIVERED,
                            ]
                        )
                    )
                )
                export_retrieved = await session.scalar(
                    select(func.count())
                    .select_from(GovernanceExportRequestModel)
                    .where(
                        GovernanceExportRequestModel.status
                        == ExportRequestStatus.RETRIEVED
                    )
                )
                export_failed = await session.scalar(
                    select(func.count())
                    .select_from(GovernanceExportRequestModel)
                    .where(
                        GovernanceExportRequestModel.status
                        == ExportRequestStatus.FAILED
                    )
                )
                erasure_complete = await session.scalar(
                    select(func.count())
                    .select_from(GovernanceErasureRequestModel)
                    .where(
                        GovernanceErasureRequestModel.status
                        == ErasureRequestStatus.COMPLETE
                    )
                )
                erasure_partial = await session.scalar(
                    select(func.count())
                    .select_from(GovernanceErasureRequestModel)
                    .where(
                        GovernanceErasureRequestModel.status
                        == ErasureRequestStatus.PARTIAL
                    )
                )
                erasure_failed = await session.scalar(
                    select(func.count())
                    .select_from(GovernanceErasureRequestModel)
                    .where(
                        GovernanceErasureRequestModel.status
                        == ErasureRequestStatus.FAILED
                    )
                )
                packages_cleared = await session.scalar(
                    select(func.count())
                    .select_from(GovernanceExportPackageModel)
                    .where(GovernanceExportPackageModel.cleared_at.is_not(None))
                )
                audit_events = await session.scalar(
                    select(func.count()).select_from(GovernanceAuditEventModel)
                )
                return GovernanceStateCounts(
                    export_pending=int(export_pending or 0),
                    export_retrieved=int(export_retrieved or 0),
                    export_failed=int(export_failed or 0),
                    erasure_complete=int(erasure_complete or 0),
                    erasure_partial=int(erasure_partial or 0),
                    erasure_failed=int(erasure_failed or 0),
                    packages_cleared=int(packages_cleared or 0),
                    audit_events=int(audit_events or 0),
                )


def _export_record(
    row: GovernanceExportRequestModel, *, created: bool = False
) -> GovernanceExportRecord:
    return GovernanceExportRecord(
        id=row.id,
        scope=row.scope,
        conversation_id=row.conversation_id,
        participant_id=row.participant_id,
        tenant_id=row.tenant_id,
        status=row.status,
        categories=tuple(row.categories),
        single_use_token_hash=row.single_use_token_hash,
        source_command_job_id=row.source_command_job_id,
        source_control_identity_id=row.source_control_identity_id,
        source_control_request_id=row.source_control_request_id,
        available_at=row.available_at,
        attempt_count=row.attempt_count,
        expires_at=row.expires_at,
        completed_at=row.completed_at,
        delivered_at=row.delivered_at,
        retrieved_at=row.retrieved_at,
        failure_reason=row.failure_reason,
        created=created,
    )


def _erasure_record(
    row: GovernanceErasureRequestModel, *, created: bool = False
) -> GovernanceErasureRecord:
    return GovernanceErasureRecord(
        id=row.id,
        scope=row.scope,
        conversation_id=row.conversation_id,
        participant_id=row.participant_id,
        status=row.status,
        partial_reason=row.partial_reason,
        retryable=row.retryable,
        requested_via=row.requested_via,
        completed_at=row.completed_at,
        source_command_job_id=row.source_command_job_id,
        lease_owner=row.lease_owner,
        lease_expires_at=row.lease_expires_at,
        created=created,
    )


def _package_record(row: GovernanceExportPackageModel) -> GovernanceExportPackageRecord:
    return GovernanceExportPackageRecord(
        request_id=row.export_request_id,
        schema_version=row.schema_version,
        manifest=row.manifest,
        package=row.package,
        expires_at=row.expires_at,
        retrieved_at=row.retrieved_at,
    )


async def invalidate_export_packages(
    session: AsyncSession,
    *,
    scope: str,
    conversation_id: UUID | None = None,
    participant_ids: list[UUID] | None = None,
    reason: str,
    now: datetime | None = None,
) -> int:
    """Atomically revoke and clear active exports for an erased data scope."""

    current = now or datetime.now(UTC)
    conditions = [
        GovernanceExportRequestModel.scope == scope,
        GovernanceExportRequestModel.status.in_(
            [
                ExportRequestStatus.REQUESTED,
                ExportRequestStatus.IN_PROGRESS,
                ExportRequestStatus.COMPLETE,
                ExportRequestStatus.DELIVERED,
            ]
        ),
    ]
    if conversation_id is not None:
        conditions.append(
            GovernanceExportRequestModel.conversation_id == conversation_id
        )
    if participant_ids is not None:
        conditions.append(
            GovernanceExportRequestModel.participant_id.in_(participant_ids)
        )
    rows = list(
        await session.scalars(
            select(GovernanceExportRequestModel).where(*conditions).with_for_update()
        )
    )
    if not rows:
        return 0
    ids = [row.id for row in rows]
    await session.execute(
        update(GovernanceExportRequestModel)
        .where(GovernanceExportRequestModel.id.in_(ids))
        .values(
            status=ExportRequestStatus.EXPIRED,
            single_use_token_hash=None,
            lease_owner=None,
            lease_expires_at=None,
        )
    )
    cleared = list(
        await session.scalars(
            update(GovernanceExportPackageModel)
            .where(
                GovernanceExportPackageModel.export_request_id.in_(ids),
                GovernanceExportPackageModel.cleared_at.is_(None),
            )
            .values(package={}, cleared_at=current)
            .returning(GovernanceExportPackageModel.id)
        )
    )
    for row in rows:
        await _record_audit_event_in_session(
            session,
            event_type=GovernanceAuditEventType.EXPORT_EXPIRED,
            scope=row.scope,
            request_id=str(row.id),
            conversation_id=row.conversation_id,
            participant_id=row.participant_id,
            tenant_id=row.tenant_id,
            outcome="expired",
            detail=reason,
        )
    return len(cleared)


async def _record_audit_event_in_session(
    session: AsyncSession,
    *,
    event_type: str,
    scope: str,
    request_id: str | None,
    conversation_id: UUID | None,
    participant_id: UUID | None,
    tenant_id: UUID | None,
    outcome: str,
    detail: str | None = None,
    metadata: dict[str, object] | None = None,
) -> None:
    await session.execute(
        insert(GovernanceAuditEventModel)
        .values(
            id=uuid4(),
            event_type=event_type,
            scope=scope,
            request_id=request_id,
            conversation_id=conversation_id,
            participant_id=participant_id,
            tenant_id=tenant_id,
            outcome=outcome,
            detail=detail,
            metadata_=metadata or {},
        )
        .on_conflict_do_nothing(index_elements=["request_id", "event_type"])
    )
