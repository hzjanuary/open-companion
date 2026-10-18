"""PostgreSQL durable inbox/outbox implementation for platform ingress."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ingress import (
    AcceptedIngressUpdate,
    IngressEnvelope,
    IngressQueueEvent,
)
from app.domain.persistence import (
    IncomingUpdateStatus,
    IngressOutboxStatus,
    Platform,
)
from app.infrastructure.database.models import (
    IncomingPlatformUpdateModel,
    IngressOutboxEventModel,
    PollingCursorModel,
)
from app.infrastructure.database.tenancy import connection_authority


class UnknownPlatformConnectionError(ValueError):
    """The route/runtime connection does not exist or is not Telegram."""


class SqlAlchemyDurableIngressRepository:
    """Own transactional acceptance so inserts and outbox intent are atomic."""

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], schema_version: int
    ) -> None:
        self._session_factory = session_factory
        self._schema_version = schema_version

    async def accept(self, envelope: IngressEnvelope) -> AcceptedIngressUpdate:
        async with self._session_factory() as session:
            async with session.begin():
                authority = await connection_authority(
                    session, envelope.platform_connection_id
                )
                if (
                    authority is None
                    or authority.connection.platform != envelope.platform
                    or not authority.permits_external_io
                ):
                    raise UnknownPlatformConnectionError(
                        "platform connection is unavailable"
                    )
                statement = (
                    insert(IncomingPlatformUpdateModel)
                    .values(
                        platform_connection_id=envelope.platform_connection_id,
                        platform=envelope.platform,
                        platform_update_id=envelope.platform_update_id,
                        update_type=envelope.update_type,
                        ingress_source=envelope.ingress_source,
                        raw_payload=envelope.raw_payload,
                        status=(
                            IncomingUpdateStatus.RECEIVED
                            if envelope.supported
                            else IncomingUpdateStatus.REJECTED
                        ),
                        received_at=envelope.received_at,
                    )
                    .on_conflict_do_nothing(
                        index_elements=["platform_connection_id", "platform_update_id"]
                    )
                    .returning(IncomingPlatformUpdateModel.id)
                )
                incoming_id = await session.scalar(statement)
                if incoming_id is None:
                    duplicate_id = await session.scalar(
                        select(IncomingPlatformUpdateModel.id).where(
                            IncomingPlatformUpdateModel.platform_connection_id
                            == envelope.platform_connection_id,
                            IncomingPlatformUpdateModel.platform_update_id
                            == envelope.platform_update_id,
                        )
                    )
                    if duplicate_id is None:
                        raise RuntimeError("inbox duplicate could not be resolved")
                    return AcceptedIngressUpdate(duplicate_id, duplicate=True)
                if envelope.supported:
                    session.add(
                        IngressOutboxEventModel(
                            incoming_update_id=incoming_id,
                            schema_version=self._schema_version,
                            status=IngressOutboxStatus.PENDING,
                        )
                    )
                return AcceptedIngressUpdate(incoming_id, duplicate=False)

    async def accept_batch_and_advance_cursor(
        self, envelopes: tuple[IngressEnvelope, ...], next_offset: str | None
    ) -> tuple[AcceptedIngressUpdate, ...]:
        if not envelopes:
            return ()
        connection_id = envelopes[0].platform_connection_id
        if any(item.platform_connection_id != connection_id for item in envelopes):
            raise ValueError("polling batch must use one platform connection")
        results: list[AcceptedIngressUpdate] = []
        async with self._session_factory() as session:
            async with session.begin():
                authority = await connection_authority(session, connection_id)
                if (
                    authority is None
                    or authority.connection.platform != Platform.TELEGRAM
                    or not authority.permits_external_io
                ):
                    raise UnknownPlatformConnectionError(
                        "platform connection is unavailable"
                    )
                for envelope in envelopes:
                    statement = (
                        insert(IncomingPlatformUpdateModel)
                        .values(
                            platform_connection_id=envelope.platform_connection_id,
                            platform=envelope.platform,
                            platform_update_id=envelope.platform_update_id,
                            update_type=envelope.update_type,
                            ingress_source=envelope.ingress_source,
                            raw_payload=envelope.raw_payload,
                            status=(
                                IncomingUpdateStatus.RECEIVED
                                if envelope.supported
                                else IncomingUpdateStatus.REJECTED
                            ),
                            received_at=envelope.received_at,
                        )
                        .on_conflict_do_nothing(
                            index_elements=[
                                "platform_connection_id",
                                "platform_update_id",
                            ]
                        )
                        .returning(IncomingPlatformUpdateModel.id)
                    )
                    incoming_id = await session.scalar(statement)
                    if incoming_id is None:
                        incoming_id = await session.scalar(
                            select(IncomingPlatformUpdateModel.id).where(
                                IncomingPlatformUpdateModel.platform_connection_id
                                == envelope.platform_connection_id,
                                IncomingPlatformUpdateModel.platform_update_id
                                == envelope.platform_update_id,
                            )
                        )
                        if incoming_id is None:
                            raise RuntimeError("inbox duplicate could not be resolved")
                        results.append(
                            AcceptedIngressUpdate(incoming_id, duplicate=True)
                        )
                    else:
                        if envelope.supported:
                            session.add(
                                IngressOutboxEventModel(
                                    incoming_update_id=incoming_id,
                                    schema_version=self._schema_version,
                                )
                            )
                        results.append(
                            AcceptedIngressUpdate(incoming_id, duplicate=False)
                        )
                cursor = await session.get(PollingCursorModel, connection_id)
                if cursor is None:
                    session.add(
                        PollingCursorModel(
                            platform_connection_id=connection_id,
                            next_offset=next_offset,
                        )
                    )
                else:
                    cursor.next_offset = next_offset
        return tuple(results)

    async def polling_offset(self, platform_connection_id: UUID) -> str | None:
        async with self._session_factory() as session:
            authority = await connection_authority(session, platform_connection_id)
            if (
                authority is None
                or authority.connection.platform != Platform.TELEGRAM
                or not authority.permits_external_io
            ):
                raise UnknownPlatformConnectionError(
                    "platform connection is unavailable"
                )
            cursor = await session.get(PollingCursorModel, platform_connection_id)
            return cursor.next_offset if cursor is not None else None

    async def pending_events(self, batch_size: int) -> list[IngressOutboxEventModel]:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                result = await session.scalars(
                    select(IngressOutboxEventModel)
                    .where(
                        IngressOutboxEventModel.status == IngressOutboxStatus.PENDING,
                        IngressOutboxEventModel.available_at <= now,
                    )
                    .order_by(
                        IngressOutboxEventModel.created_at, IngressOutboxEventModel.id
                    )
                    .limit(batch_size)
                    .with_for_update(skip_locked=True)
                )
                events = list(result)
                return events

    async def event_for(self, event_id: UUID) -> IngressQueueEvent | None:
        async with self._session_factory() as session:
            event = await session.get(IngressOutboxEventModel, event_id)
            if event is None:
                return None
            incoming = await session.get(
                IncomingPlatformUpdateModel, event.incoming_update_id
            )
            if incoming is None:
                return None
            return IngressQueueEvent(
                schema_version=event.schema_version,
                incoming_update_id=incoming.id,
                platform=incoming.platform,
                platform_connection_id=incoming.platform_connection_id,
                platform_update_id=incoming.platform_update_id,
                update_type=incoming.update_type,
                received_at=incoming.received_at,
            )

    async def mark_published(self, event_id: UUID) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                event = await session.get(
                    IngressOutboxEventModel, event_id, with_for_update=True
                )
                if event is None:
                    return
                now = datetime.now(UTC)
                event.status = IngressOutboxStatus.PUBLISHED
                event.published_at = now
                event.last_error_category = None
                incoming = await session.get(
                    IncomingPlatformUpdateModel, event.incoming_update_id
                )
                if incoming is not None:
                    incoming.status = IncomingUpdateStatus.QUEUED
                    incoming.queued_at = now

    async def mark_publish_failed(self, event_id: UUID, delay_seconds: float) -> None:
        from datetime import timedelta

        async with self._session_factory() as session:
            async with session.begin():
                event = await session.get(
                    IngressOutboxEventModel, event_id, with_for_update=True
                )
                if event is None:
                    return
                now = datetime.now(UTC)
                event.attempt_count += 1
                event.last_attempt_at = now
                event.last_error_category = "queue_unavailable"
                event.available_at = now + timedelta(seconds=delay_seconds)
