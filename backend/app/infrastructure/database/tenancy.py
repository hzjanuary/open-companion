"""Canonical persisted tenant/Assistant/connection authority resolution."""

from dataclasses import dataclass
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.persistence import (
    AssistantStatus,
    PlatformConnectionStatus,
    TenantStatus,
)
from app.infrastructure.database.models import (
    AssistantModel,
    ControlTenantModel,
    ConversationModel,
    PlatformConnectionModel,
)


@dataclass(frozen=True, slots=True)
class ConnectionAuthority:
    tenant: ControlTenantModel
    assistant: AssistantModel
    connection: PlatformConnectionModel

    @property
    def permits_external_io(self) -> bool:
        return (
            self.tenant.status == TenantStatus.ACTIVE
            and self.assistant.status == AssistantStatus.ACTIVE
            and self.connection.status == PlatformConnectionStatus.ACTIVE
        )


async def assistant_for_tenant(
    session: AsyncSession, tenant_id: UUID, assistant_id: UUID
) -> AssistantModel | None:
    return cast(
        AssistantModel | None,
        await session.scalar(
            select(AssistantModel).where(
                AssistantModel.id == assistant_id,
                AssistantModel.tenant_id == tenant_id,
            )
        ),
    )


async def connection_for_tenant(
    session: AsyncSession, tenant_id: UUID, connection_id: UUID
) -> PlatformConnectionModel | None:
    return cast(
        PlatformConnectionModel | None,
        await session.scalar(
            select(PlatformConnectionModel).where(
                PlatformConnectionModel.id == connection_id,
                PlatformConnectionModel.tenant_id == tenant_id,
            )
        ),
    )


async def connection_authority(
    session: AsyncSession, connection_id: UUID
) -> ConnectionAuthority | None:
    row = (
        await session.execute(
            select(ControlTenantModel, AssistantModel, PlatformConnectionModel)
            .join(
                AssistantModel,
                AssistantModel.tenant_id == ControlTenantModel.id,
            )
            .join(
                PlatformConnectionModel,
                (PlatformConnectionModel.assistant_id == AssistantModel.id)
                & (PlatformConnectionModel.tenant_id == AssistantModel.tenant_id),
            )
            .where(PlatformConnectionModel.id == connection_id)
        )
    ).one_or_none()
    if row is None:
        return None
    tenant, assistant, connection = row
    return ConnectionAuthority(tenant, assistant, connection)


async def conversation_authority(
    session: AsyncSession, conversation_id: UUID
) -> tuple[ConversationModel, ConnectionAuthority] | None:
    row = (
        await session.execute(
            select(
                ConversationModel,
                ControlTenantModel,
                AssistantModel,
                PlatformConnectionModel,
            )
            .join(
                PlatformConnectionModel,
                PlatformConnectionModel.id == ConversationModel.platform_connection_id,
            )
            .join(
                AssistantModel,
                (AssistantModel.id == PlatformConnectionModel.assistant_id)
                & (AssistantModel.tenant_id == PlatformConnectionModel.tenant_id),
            )
            .join(ControlTenantModel, ControlTenantModel.id == AssistantModel.tenant_id)
            .where(ConversationModel.id == conversation_id)
        )
    ).one_or_none()
    if row is None:
        return None
    conversation, tenant, assistant, connection = row
    return conversation, ConnectionAuthority(tenant, assistant, connection)
