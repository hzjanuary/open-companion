"""Content-safe durable operations inspection and one-item replay."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.outbound import OutboundActionStatus
from app.domain.planning import PlanningJobStatus
from app.domain.recovery import RecoveryDisposition, RecoveryKind, RecoveryReason
from app.infrastructure.database.models import (
    OperationalRecoveryEventModel,
    OperationalRecoveryItemModel,
    OutboundActionModel,
    ResponsePlanningJobModel,
)


@dataclass(frozen=True)
class RecoveryInspection:
    work_id: UUID
    work_kind: RecoveryKind
    disposition: RecoveryDisposition
    reason: RecoveryReason
    attempt_count: int
    state: str
    next_available_at: datetime
    lease_expires_at: datetime | None
    created_at: datetime
    replayed_at: datetime | None


class SqlAlchemyRecoveryRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def classify(
        self,
        kind: RecoveryKind,
        work_id: UUID,
        disposition: RecoveryDisposition,
        reason: RecoveryReason,
    ) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                item = await session.scalar(
                    select(OperationalRecoveryItemModel)
                    .where(
                        OperationalRecoveryItemModel.work_kind == kind,
                        OperationalRecoveryItemModel.work_id == work_id,
                    )
                    .with_for_update()
                )
                if item is None:
                    item = OperationalRecoveryItemModel(
                        work_kind=kind,
                        work_id=work_id,
                        disposition=disposition,
                        reason=reason,
                    )
                    session.add(item)
                    await session.flush()
                else:
                    item.disposition, item.reason = disposition, reason
                session.add(
                    OperationalRecoveryEventModel(
                        recovery_item_id=item.id,
                        event_type="classified",
                        actor="runtime",
                    )
                )

    async def summarize(self, kind: RecoveryKind | None = None) -> dict[str, object]:
        async with self._session_factory() as session:
            query = select(
                OperationalRecoveryItemModel.work_kind,
                OperationalRecoveryItemModel.disposition,
                func.count(),
            ).group_by(
                OperationalRecoveryItemModel.work_kind,
                OperationalRecoveryItemModel.disposition,
            )
            if kind is not None:
                query = query.where(OperationalRecoveryItemModel.work_kind == kind)
            rows = await session.execute(query)
            recovery = {
                f"{work_kind.value}.{disposition.value}": count
                for work_kind, disposition, count in rows
            }
            result: dict[str, object] = {"recovery": recovery}
            if kind in (None, RecoveryKind.PLANNING):
                result[RecoveryKind.PLANNING.value] = await self._work_summary(
                    session, ResponsePlanningJobModel
                )
            if kind in (None, RecoveryKind.OUTBOUND):
                result[RecoveryKind.OUTBOUND.value] = await self._work_summary(
                    session, OutboundActionModel
                )
            return result

    async def show(self, work_id: UUID) -> RecoveryInspection | None:
        async with self._session_factory() as session:
            item = await session.scalar(
                select(OperationalRecoveryItemModel).where(
                    OperationalRecoveryItemModel.work_id == work_id
                )
            )
            if item is None:
                return None
            model = await self._model(session, item.work_kind, work_id)
            if model is None:
                return None
            return RecoveryInspection(
                work_id=work_id,
                work_kind=item.work_kind,
                disposition=item.disposition,
                reason=item.reason,
                attempt_count=model.attempt_count,
                state=model.status.value,
                next_available_at=model.available_at,
                lease_expires_at=model.lease_expires_at,
                created_at=item.created_at,
                replayed_at=item.replayed_at,
            )

    async def replay(
        self, kind: RecoveryKind, work_id: UUID, actor: str = "operator"
    ) -> bool:
        """Atomic one-item replay. It makes no external call and refuses quarantine."""
        async with self._session_factory() as session:
            async with session.begin():
                item = await session.scalar(
                    select(OperationalRecoveryItemModel)
                    .where(
                        OperationalRecoveryItemModel.work_kind == kind,
                        OperationalRecoveryItemModel.work_id == work_id,
                    )
                    .with_for_update()
                )
                if (
                    item is None
                    or item.disposition != RecoveryDisposition.DEAD_LETTER
                    or item.replayed_at is not None
                ):
                    return False
                model = await self._model(session, kind, work_id, locked=True)
                if model is None or model.status.value in {
                    "completed",
                    "delivered",
                    "delivery_unknown",
                    "leased",
                }:
                    return False
                if kind == RecoveryKind.PLANNING:
                    cast(
                        ResponsePlanningJobModel, model
                    ).status = PlanningJobStatus.PENDING
                else:
                    outbound = cast(OutboundActionModel, model)
                    outbound.status = OutboundActionStatus.PENDING
                model.available_at = datetime.now(UTC)
                model.lease_owner = None
                model.lease_expires_at = None
                item.replayed_at = datetime.now(UTC)
                session.add(
                    OperationalRecoveryEventModel(
                        recovery_item_id=item.id, event_type="replayed", actor=actor
                    )
                )
                return True

    async def _model(
        self,
        session: AsyncSession,
        kind: RecoveryKind,
        work_id: UUID,
        locked: bool = False,
    ) -> ResponsePlanningJobModel | OutboundActionModel | None:
        model = (
            ResponsePlanningJobModel
            if kind == RecoveryKind.PLANNING
            else OutboundActionModel
        )
        query = select(model).where(model.id == work_id)
        if locked:
            query = query.with_for_update()
        return cast(
            ResponsePlanningJobModel | OutboundActionModel | None,
            await session.scalar(query),
        )

    async def _work_summary(
        self,
        session: AsyncSession,
        model: type[ResponsePlanningJobModel] | type[OutboundActionModel],
    ) -> dict[str, object]:
        """Return operational counts only; none of these columns contain content."""
        rows = list(
            await session.execute(
                select(model.status, model.available_at, model.lease_expires_at)
            )
        )
        now = datetime.now(UTC)
        states: dict[str, int] = {}
        pending_times: list[datetime] = []
        active_leases = 0
        stale_leases = 0
        for status, available_at, lease_expires_at in rows:
            state = status.value
            states[state] = states.get(state, 0) + 1
            if state == "pending":
                pending_times.append(available_at)
            if state == "leased" and lease_expires_at is not None:
                if lease_expires_at > now:
                    active_leases += 1
                else:
                    stale_leases += 1
        oldest_pending = min(pending_times, default=None)
        return {
            "count_by_state": states,
            "oldest_pending_age_seconds": (
                max(0, int((now - oldest_pending).total_seconds()))
                if oldest_pending is not None
                else None
            ),
            "active_lease_count": active_leases,
            "stale_lease_count": stale_leases,
        }
