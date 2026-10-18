"""Transactional, credential-free Assistant and Telegram connection bootstrap."""

from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.bootstrap import BootstrapResult
from app.application.ports.platform import BotIdentity
from app.core.config import Settings
from app.domain.persistence import (
    AssistantStatus,
    Platform,
    PlatformConnectionStatus,
    TenantStatus,
)
from app.infrastructure.database.models import (
    AssistantModel,
    ControlAssistantBindingModel,
    ControlConnectionBindingModel,
    ControlTenantModel,
    PlatformConnectionModel,
)
from app.infrastructure.database.personality import ensure_assistant_default


class BootstrapConflictError(RuntimeError):
    pass


class SqlAlchemyOperatorBootstrap:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def reconcile(
        self, settings: Settings, identity: BotIdentity
    ) -> BootstrapResult:
        if not identity.is_bot or identity.platform != Platform.TELEGRAM:
            raise BootstrapConflictError("configured Telegram identity is not a bot")
        async with self._session_factory() as session:
            async with session.begin():
                configured = (
                    await session.get(
                        PlatformConnectionModel,
                        settings.telegram_platform_connection_id,
                    )
                    if settings.telegram_platform_connection_id is not None
                    else None
                )
                if (
                    configured is not None
                    and configured.external_bot_id != identity.external_bot_id
                ):
                    raise BootstrapConflictError(
                        "configured platform connection belongs to another bot"
                    )
                connection = await session.scalar(
                    select(PlatformConnectionModel).where(
                        PlatformConnectionModel.platform == Platform.TELEGRAM,
                        PlatformConnectionModel.external_bot_id
                        == identity.external_bot_id,
                    )
                )
                if (
                    configured is not None
                    and connection is not None
                    and configured.id != connection.id
                ):
                    raise BootstrapConflictError("conflicting Telegram connection rows")
                if connection is not None:
                    assistant = await session.get(
                        AssistantModel, connection.assistant_id
                    )
                    tenant = await session.get(ControlTenantModel, connection.tenant_id)
                    if assistant is None or assistant.name != settings.app_name:
                        raise BootstrapConflictError(
                            "existing bot connection belongs to another Assistant"
                        )
                    if (
                        connection.status != PlatformConnectionStatus.ACTIVE
                        or assistant.status != AssistantStatus.ACTIVE
                        or tenant is None
                        or tenant.status != TenantStatus.ACTIVE
                    ):
                        raise BootstrapConflictError(
                            "existing tenant, Assistant, or platform connection "
                            "is inactive"
                        )
                    if (
                        settings.telegram_tenant_id is not None
                        and connection.tenant_id != settings.telegram_tenant_id
                    ):
                        raise BootstrapConflictError(
                            "configured platform connection belongs to another tenant"
                        )
                else:
                    if settings.telegram_tenant_id is not None:
                        tenant = await session.get(
                            ControlTenantModel, settings.telegram_tenant_id
                        )
                        tenants = [tenant] if tenant is not None else []
                    else:
                        tenants = list(
                            await session.scalars(
                                select(ControlTenantModel)
                                .where(ControlTenantModel.status == TenantStatus.ACTIVE)
                                .order_by(ControlTenantModel.id)
                                .limit(2)
                            )
                        )
                    if len(tenants) != 1 or tenants[0] is None:
                        raise BootstrapConflictError(
                            "exactly one active tenant or telegram_tenant_id "
                            "is required"
                        )
                    tenant = tenants[0]
                    if tenant.status != TenantStatus.ACTIVE:
                        raise BootstrapConflictError("configured tenant is inactive")
                    assistants = list(
                        await session.scalars(
                            select(AssistantModel).where(
                                AssistantModel.tenant_id == tenant.id,
                                AssistantModel.name == settings.app_name,
                            )
                        )
                    )
                    if len(assistants) > 1:
                        raise BootstrapConflictError(
                            "conflicting duplicate Assistant rows"
                        )
                    assistant = assistants[0] if assistants else None
                    if (
                        assistant is not None
                        and assistant.status != AssistantStatus.ACTIVE
                    ):
                        raise BootstrapConflictError("existing Assistant is inactive")
                    if assistant is None:
                        assistant = AssistantModel(
                            tenant_id=tenant.id,
                            slug=(
                                "bootstrap-"
                                + sha256(identity.external_bot_id.encode()).hexdigest()[
                                    :16
                                ]
                            ),
                            name=settings.app_name,
                            status=AssistantStatus.ACTIVE,
                        )
                        session.add(assistant)
                        await session.flush()
                        session.add(
                            ControlAssistantBindingModel(
                                tenant_id=tenant.id, assistant_id=assistant.id
                            )
                        )
                    connection = PlatformConnectionModel(
                        tenant_id=tenant.id,
                        assistant_id=assistant.id,
                        platform=Platform.TELEGRAM,
                        external_bot_id=identity.external_bot_id,
                        credential_reference="env:JANUARY_TELEGRAM_BOT_TOKEN",
                    )
                    session.add(connection)
                    await session.flush()
                    session.add(
                        ControlConnectionBindingModel(
                            tenant_id=tenant.id, connection_id=connection.id
                        )
                    )
                connection.status = PlatformConnectionStatus.ACTIVE
                connection.configuration = {
                    "username": identity.username,
                    "display_name": identity.display_name,
                    "can_join_groups": identity.can_join_groups,
                    "can_read_all_group_messages": identity.can_read_all_group_messages,
                }
                await ensure_assistant_default(session, assistant)
                return BootstrapResult(
                    assistant.id,
                    connection.id,
                    identity.external_bot_id,
                    identity.username,
                    identity.display_name,
                    identity.can_join_groups,
                    identity.can_read_all_group_messages,
                )
