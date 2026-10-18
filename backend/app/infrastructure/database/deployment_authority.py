"""Durable, deployment-scoped authorization independent of tenant roles."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.governance import DeploymentAuthority
from app.infrastructure.database.models import (
    ControlAuditEventModel,
    ControlDeploymentAuthorityModel,
    ControlDeploymentAuthorityOperationModel,
    ControlOperatorIdentityModel,
)


@dataclass(frozen=True, slots=True)
class DeploymentAuthorityChange:
    identity_id: UUID
    active: bool
    changed: bool


class DeploymentAuthorityIdempotencyConflict(Exception):
    """One actor reused an authority-operation request id for another target."""


async def has_deployment_authority(session: AsyncSession, identity_id: UUID) -> bool:
    """Read current durable authority on every decision; no privilege cache."""

    authorized = await session.scalar(
        select(ControlDeploymentAuthorityModel.id)
        .join(
            ControlOperatorIdentityModel,
            ControlOperatorIdentityModel.id
            == ControlDeploymentAuthorityModel.identity_id,
        )
        .where(
            ControlDeploymentAuthorityModel.identity_id == identity_id,
            ControlDeploymentAuthorityModel.authority
            == DeploymentAuthority.DEPLOYMENT_OPERATOR,
            ControlDeploymentAuthorityModel.revoked_at.is_(None),
            ControlOperatorIdentityModel.disabled_at.is_(None),
        )
        .limit(1)
    )
    return authorized is not None


async def active_deployment_authority_count(session: AsyncSession) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(ControlDeploymentAuthorityModel)
        .join(
            ControlOperatorIdentityModel,
            ControlOperatorIdentityModel.id
            == ControlDeploymentAuthorityModel.identity_id,
        )
        .where(
            ControlDeploymentAuthorityModel.authority
            == DeploymentAuthority.DEPLOYMENT_OPERATOR,
            ControlDeploymentAuthorityModel.revoked_at.is_(None),
            ControlOperatorIdentityModel.disabled_at.is_(None),
        )
    )
    return int(count or 0)


class SqlAlchemyDeploymentAuthorityRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def has(self, identity_id: UUID) -> bool:
        async with self._session_factory() as session:
            return await has_deployment_authority(session, identity_id)

    async def grant(
        self,
        *,
        identity_id: UUID,
        actor_identity_id: UUID,
        request_id: str,
        now: datetime | None = None,
    ) -> DeploymentAuthorityChange:
        current = now or datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                return await _grant_in_session(
                    session,
                    identity_id=identity_id,
                    actor_identity_id=actor_identity_id,
                    request_id=request_id,
                    now=current,
                )

    async def bootstrap_self_grant(
        self,
        *,
        identity_id: UUID,
        request_id: str,
        now: datetime | None = None,
    ) -> DeploymentAuthorityChange:
        """Serialize establishment of the first configured root authority."""

        current = now or datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("LOCK TABLE control_deployment_authorities IN EXCLUSIVE MODE")
                )
                if await active_deployment_authority_count(session) != 0:
                    raise PermissionError("deployment authority is already established")
                return await _grant_in_session(
                    session,
                    identity_id=identity_id,
                    actor_identity_id=identity_id,
                    request_id=request_id,
                    now=current,
                )

    async def revoke(
        self,
        *,
        identity_id: UUID,
        actor_identity_id: UUID,
        request_id: str,
        now: datetime | None = None,
    ) -> DeploymentAuthorityChange:
        current = now or datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                replay = await _claim_operation(
                    session,
                    actor_identity_id=actor_identity_id,
                    target_identity_id=identity_id,
                    operation="revoke",
                    request_id=request_id,
                    resulting_active=False,
                )
                if replay is not None:
                    return replay
                revoked = await session.scalar(
                    update(ControlDeploymentAuthorityModel)
                    .where(
                        ControlDeploymentAuthorityModel.identity_id == identity_id,
                        ControlDeploymentAuthorityModel.authority
                        == DeploymentAuthority.DEPLOYMENT_OPERATOR,
                        ControlDeploymentAuthorityModel.revoked_at.is_(None),
                    )
                    .values(
                        revoked_by_identity_id=actor_identity_id,
                        revoked_at=current,
                    )
                    .returning(ControlDeploymentAuthorityModel.id)
                )
                changed = revoked is not None
                if changed:
                    session.add(
                        _audit_event(
                            actor_identity_id=actor_identity_id,
                            action="deployment_authority.revoke",
                            outcome="success",
                            resource_id=identity_id,
                            request_id=request_id,
                        )
                    )
                await _complete_operation(
                    session,
                    actor_identity_id=actor_identity_id,
                    operation="revoke",
                    request_id=request_id,
                    changed=changed,
                )
                return DeploymentAuthorityChange(identity_id, False, changed)


def _audit_event(
    *,
    actor_identity_id: UUID,
    action: str,
    outcome: str,
    resource_id: UUID | None,
    request_id: str,
) -> ControlAuditEventModel:
    return ControlAuditEventModel(
        tenant_id=None,
        actor_identity_id=actor_identity_id,
        action=action,
        outcome=outcome,
        resource_type="deployment_authority",
        resource_id=str(resource_id) if resource_id else None,
        request_id=request_id,
        metadata_={"schema_version": "spec-025-v1"},
    )


async def _grant_in_session(
    session: AsyncSession,
    *,
    identity_id: UUID,
    actor_identity_id: UUID,
    request_id: str,
    now: datetime,
) -> DeploymentAuthorityChange:
    replay = await _claim_operation(
        session,
        actor_identity_id=actor_identity_id,
        target_identity_id=identity_id,
        operation="grant",
        request_id=request_id,
        resulting_active=True,
    )
    if replay is not None:
        return replay
    target = await session.get(ControlOperatorIdentityModel, identity_id)
    if target is None or target.disabled_at is not None:
        raise ValueError("deployment authority target is unavailable")
    reactivated = await session.scalar(
        update(ControlDeploymentAuthorityModel)
        .where(
            ControlDeploymentAuthorityModel.identity_id == identity_id,
            ControlDeploymentAuthorityModel.authority
            == DeploymentAuthority.DEPLOYMENT_OPERATOR,
            ControlDeploymentAuthorityModel.revoked_at.is_not(None),
        )
        .values(
            granted_by_identity_id=actor_identity_id,
            granted_at=now,
            revoked_by_identity_id=None,
            revoked_at=None,
        )
        .returning(ControlDeploymentAuthorityModel.id)
    )
    inserted = None
    if reactivated is None:
        inserted = await session.scalar(
            insert(ControlDeploymentAuthorityModel)
            .values(
                identity_id=identity_id,
                authority=DeploymentAuthority.DEPLOYMENT_OPERATOR,
                granted_by_identity_id=actor_identity_id,
                granted_at=now,
            )
            .on_conflict_do_nothing(index_elements=["identity_id", "authority"])
            .returning(ControlDeploymentAuthorityModel.id)
        )
    changed = reactivated is not None or inserted is not None
    if changed:
        session.add(
            _audit_event(
                actor_identity_id=actor_identity_id,
                action="deployment_authority.grant",
                outcome="success",
                resource_id=identity_id,
                request_id=request_id,
            )
        )
    await _complete_operation(
        session,
        actor_identity_id=actor_identity_id,
        operation="grant",
        request_id=request_id,
        changed=changed,
    )
    return DeploymentAuthorityChange(identity_id, True, changed)


async def _claim_operation(
    session: AsyncSession,
    *,
    actor_identity_id: UUID,
    target_identity_id: UUID,
    operation: str,
    request_id: str,
    resulting_active: bool,
) -> DeploymentAuthorityChange | None:
    inserted = await session.scalar(
        insert(ControlDeploymentAuthorityOperationModel)
        .values(
            actor_identity_id=actor_identity_id,
            target_identity_id=target_identity_id,
            operation=operation,
            request_id=request_id,
            changed=False,
            resulting_active=resulting_active,
        )
        .on_conflict_do_nothing(
            index_elements=["actor_identity_id", "operation", "request_id"]
        )
        .returning(ControlDeploymentAuthorityOperationModel.id)
    )
    if inserted is not None:
        return None
    existing = await session.scalar(
        select(ControlDeploymentAuthorityOperationModel).where(
            ControlDeploymentAuthorityOperationModel.actor_identity_id
            == actor_identity_id,
            ControlDeploymentAuthorityOperationModel.operation == operation,
            ControlDeploymentAuthorityOperationModel.request_id == request_id,
        )
    )
    if existing is None:
        raise RuntimeError("deployment authority idempotency lookup failed")
    if existing.target_identity_id != target_identity_id:
        raise DeploymentAuthorityIdempotencyConflict(
            "deployment authority request id was reused"
        )
    return DeploymentAuthorityChange(
        target_identity_id,
        existing.resulting_active,
        False,
    )


async def _complete_operation(
    session: AsyncSession,
    *,
    actor_identity_id: UUID,
    operation: str,
    request_id: str,
    changed: bool,
) -> None:
    await session.execute(
        update(ControlDeploymentAuthorityOperationModel)
        .where(
            ControlDeploymentAuthorityOperationModel.actor_identity_id
            == actor_identity_id,
            ControlDeploymentAuthorityOperationModel.operation == operation,
            ControlDeploymentAuthorityOperationModel.request_id == request_id,
        )
        .values(changed=changed)
    )
