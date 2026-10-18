"""Live PostgreSQL proof for SPEC-030 canonical tenancy and authorization."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import jwt
import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.domain.conversation import ProcessingOutcome
from app.domain.persistence import (
    AssistantStatus,
    ConversationType,
    IngressSource,
    MemoryKind,
    MemoryScope,
    MemoryVisibility,
    MessageDirection,
    MessageType,
    Platform,
    PlatformConnectionStatus,
)
from app.domain.provider_governance import BudgetScope, WorkloadClass
from app.domain.tenancy import LEGACY_TENANT_ID
from app.infrastructure.database.database import Database
from app.infrastructure.database.models import (
    AssistantModel,
    ControlAssistantBindingModel,
    ControlConnectionBindingModel,
    ControlDeploymentAuthorityModel,
    ControlGroupBindingModel,
    ControlOperatorIdentityModel,
    ControlOperatorMembershipModel,
    ControlTenantModel,
    ConversationModel,
    ConversationProcessingRecordModel,
    IncomingPlatformUpdateModel,
    MemoryItemModel,
    MemoryRecallPolicyModel,
    MessageModel,
    ParticipantModel,
    PlatformConnectionModel,
    ProviderRoutingPolicyRevisionModel,
    TelegramCommandJobModel,
)
from app.infrastructure.database.tenancy import connection_authority
from app.main import create_app

pytestmark = [pytest.mark.integration, pytest.mark.multi_tenant_integration]


async def _restore_legacy_tenant(database: Database) -> None:
    async with database.session_factory() as session, session.begin():
        if await session.get(ControlTenantModel, LEGACY_TENANT_ID) is None:
            session.add(
                ControlTenantModel(
                    id=LEGACY_TENANT_ID,
                    slug="legacy-default",
                    name="Legacy default",
                )
            )


async def _integrity_error(database: Database, statement: object) -> None:
    async with database.engine.connect() as connection:
        transaction = await connection.begin()
        with pytest.raises(IntegrityError):
            await connection.execute(statement)  # type: ignore[arg-type]
        await transaction.rollback()


def _token(settings: Settings, subject: str) -> str:
    assert settings.control_plane_jwt_secret is not None
    return jwt.encode(
        {
            "iss": "spec030-issuer",
            "sub": subject,
            "aud": "spec030-audience",
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        settings.control_plane_jwt_secret.get_secret_value(),
        algorithm="HS256",
    )


async def _database_rejects_cross_tenant_and_cross_assistant_chains() -> None:
    database = Database(Settings(_env_file=None, environment="test"))
    await database.start()
    try:
        async with database.session_factory() as session, session.begin():
            await session.execute(
                text(
                    "TRUNCATE control_operator_identities, control_tenants, "
                    "assistants CASCADE"
                )
            )
            tenant_a = ControlTenantModel(slug="spec030-a", name="Tenant A")
            tenant_b = ControlTenantModel(slug="spec030-b", name="Tenant B")
            actor = ControlOperatorIdentityModel(
                issuer="spec030-issuer", subject="schema-actor"
            )
            session.add_all([tenant_a, tenant_b, actor])
            await session.flush()
            a1 = AssistantModel(
                tenant_id=tenant_a.id,
                slug="same-name",
                name="Same display name",
                status=AssistantStatus.ACTIVE,
            )
            a2 = AssistantModel(
                tenant_id=tenant_a.id,
                slug="second",
                name="Same display name",
                status=AssistantStatus.ACTIVE,
            )
            b1 = AssistantModel(
                tenant_id=tenant_b.id,
                slug="same-name",
                name="Same display name",
                status=AssistantStatus.ACTIVE,
            )
            session.add_all([a1, a2, b1])
            await session.flush()
            connections = []
            for assistant, tenant, suffix in (
                (a1, tenant_a, "a1"),
                (a2, tenant_a, "a2"),
                (b1, tenant_b, "b1"),
            ):
                connection = PlatformConnectionModel(
                    tenant_id=tenant.id,
                    assistant_id=assistant.id,
                    platform=Platform.TELEGRAM,
                    external_bot_id=f"spec030-{suffix}",
                    status=PlatformConnectionStatus.ACTIVE,
                )
                session.add(connection)
                connections.append(connection)
            await session.flush()
            conversations = []
            for connection, suffix in zip(connections, ("a1", "a2", "b1"), strict=True):
                conversation = ConversationModel(
                    platform_connection_id=connection.id,
                    platform_conversation_id=f"private-{suffix}",
                    conversation_type=ConversationType.PRIVATE,
                )
                session.add(conversation)
                conversations.append(conversation)
            await session.flush()
            participants = [
                ParticipantModel(
                    conversation_id=conversation.id,
                    platform_user_id="same-platform-user",
                    display_name="Same person",
                )
                for conversation in conversations
            ]
            session.add_all(participants)
            await session.flush()
            assert len({participant.id for participant in participants}) == 3
            participant = participants[0]
            message = MessageModel(
                conversation_id=conversations[0].id,
                participant_id=participant.id,
                platform_message_id="memory-source",
                direction=MessageDirection.INCOMING,
                message_type=MessageType.TEXT,
                text="private fixture",
            )
            incoming = IncomingPlatformUpdateModel(
                platform_connection_id=connections[0].id,
                platform=Platform.TELEGRAM,
                platform_update_id="memory-source",
                update_type="message",
                ingress_source=IngressSource.WEBHOOK,
                raw_payload={},
                received_at=datetime.now(UTC),
            )
            session.add_all([message, incoming])
            await session.flush()
            processing = ConversationProcessingRecordModel(
                incoming_update_id=incoming.id,
                outcome=ProcessingOutcome.MESSAGE_CREATED,
                conversation_id=conversations[0].id,
                message_id=message.id,
            )
            session.add(processing)
            await session.flush()
            command = TelegramCommandJobModel(
                conversation_processing_record_id=processing.id,
                conversation_id=conversations[0].id,
                message_id=message.id,
                participant_id=participant.id,
                command_name="memory",
                arguments="fixture",
            )
            session.add(command)
            await session.flush()
            memory = MemoryItemModel(
                public_id="SPEC030MEMORY0000000001",
                assistant_id=a1.id,
                platform_connection_id=connections[0].id,
                conversation_id=conversations[0].id,
                creator_participant_id=participant.id,
                kind=MemoryKind.EXPLICIT_FACT,
                scope=MemoryScope.PRIVATE_CONVERSATION,
                visibility=MemoryVisibility.SAME_CONVERSATION,
                content="private fixture",
                normalized_content_hash="a" * 64,
                confidence=1.0,
                source_message_id=message.id,
                source_command_job_id=command.id,
            )
            recall = MemoryRecallPolicyModel(
                assistant_id=a1.id,
                platform_connection_id=connections[0].id,
                conversation_id=conversations[0].id,
                participant_id=participant.id,
                enabled=False,
                source_command_job_id=command.id,
            )
            session.add_all(
                [
                    memory,
                    recall,
                    ControlAssistantBindingModel(
                        tenant_id=tenant_a.id, assistant_id=a1.id
                    ),
                    ControlConnectionBindingModel(
                        tenant_id=tenant_a.id, connection_id=connections[0].id
                    ),
                ]
            )
            await session.flush()
            ids = {
                "tenant_a": tenant_a.id,
                "tenant_b": tenant_b.id,
                "a1": a1.id,
                "a2": a2.id,
                "connection_a1": connections[0].id,
                "conversation_b1": conversations[2].id,
                "memory": memory.id,
                "recall": recall.id,
                "actor": actor.id,
            }

        async with database.session_factory() as session:
            authority = await connection_authority(session, ids["connection_a1"])
            assert authority is not None
            assert authority.tenant.id == ids["tenant_a"]
            assert authority.assistant.id == ids["a1"]

        await _integrity_error(
            database,
            update(PlatformConnectionModel)
            .where(PlatformConnectionModel.id == ids["connection_a1"])
            .values(tenant_id=ids["tenant_b"]),
        )
        await _integrity_error(
            database,
            update(PlatformConnectionModel)
            .where(PlatformConnectionModel.id == ids["connection_a1"])
            .values(assistant_id=ids["a2"]),
        )
        await _integrity_error(
            database,
            update(AssistantModel)
            .where(AssistantModel.id == ids["a1"])
            .values(tenant_id=ids["tenant_b"]),
        )
        await _integrity_error(
            database,
            ControlAssistantBindingModel.__table__.insert().values(
                tenant_id=ids["tenant_b"], assistant_id=ids["a2"]
            ),
        )
        await _integrity_error(
            database,
            ControlGroupBindingModel.__table__.insert().values(
                tenant_id=ids["tenant_b"],
                connection_id=ids["connection_a1"],
                external_group_id="foreign-group",
            ),
        )
        await _integrity_error(
            database,
            update(MemoryItemModel)
            .where(MemoryItemModel.id == ids["memory"])
            .values(assistant_id=ids["a2"]),
        )
        await _integrity_error(
            database,
            update(MemoryRecallPolicyModel)
            .where(MemoryRecallPolicyModel.id == ids["recall"])
            .values(conversation_id=ids["conversation_b1"]),
        )
        await _integrity_error(
            database,
            ProviderRoutingPolicyRevisionModel.__table__.insert().values(
                scope_type=BudgetScope.ASSISTANT,
                scope_key=f"assistant:{ids['a1']}",
                tenant_id=ids["tenant_b"],
                assistant_id=ids["a1"],
                workload_class=WorkloadClass.CHAT_GENERATION,
                schema_version="provider-routing-v1",
                version=1,
                requirements={},
                effective_at=datetime.now(UTC),
                created_by_identity_id=ids["actor"],
            ),
        )
    finally:
        await _restore_legacy_tenant(database)
        await database.stop()


def test_database_rejects_cross_tenant_and_cross_assistant_chains() -> None:
    asyncio.run(_database_rejects_cross_tenant_and_cross_assistant_chains())


async def _control_plane_roles_isolation_lifecycle_and_concurrency() -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        control_plane_enabled=True,
        control_plane_jwt_secret="s" * 40,
        control_plane_jwt_issuer="spec030-issuer",
        control_plane_jwt_audience="spec030-audience",
    )
    database = Database(settings)
    await database.start()
    try:
        async with database.session_factory() as session, session.begin():
            await session.execute(
                text(
                    "TRUNCATE control_operator_identities, control_tenants, "
                    "assistants CASCADE"
                )
            )
            tenant_a = ControlTenantModel(slug="control-a", name="Control A")
            tenant_b = ControlTenantModel(slug="control-b", name="Control B")
            session.add_all([tenant_a, tenant_b])
            await session.flush()
            subjects = {
                role: f"{role}-subject"
                for role in (
                    "tenant_owner",
                    "tenant_admin",
                    "operator",
                    "auditor",
                    "viewer",
                    "deployment_operator",
                    "other_owner",
                )
            }
            identities = {
                role: ControlOperatorIdentityModel(
                    issuer="spec030-issuer", subject=subject
                )
                for role, subject in subjects.items()
            }
            session.add_all(identities.values())
            await session.flush()
            for role in (
                "tenant_owner",
                "tenant_admin",
                "operator",
                "auditor",
                "viewer",
            ):
                session.add(
                    ControlOperatorMembershipModel(
                        tenant_id=tenant_a.id,
                        identity_id=identities[role].id,
                        role=role,
                    )
                )
            session.add(
                ControlOperatorMembershipModel(
                    tenant_id=tenant_b.id,
                    identity_id=identities["other_owner"].id,
                    role="tenant_owner",
                )
            )
            session.add(
                ControlDeploymentAuthorityModel(
                    identity_id=identities["deployment_operator"].id,
                    granted_by_identity_id=identities["deployment_operator"].id,
                )
            )
            foreign = AssistantModel(
                tenant_id=tenant_b.id,
                slug="foreign",
                name="Same display name",
                status=AssistantStatus.ACTIVE,
            )
            session.add(foreign)
            await session.flush()
            tenant_a_id = tenant_a.id
            tenant_b_id = tenant_b.id
            foreign_id = foreign.id

        app = create_app(settings)
        app.state.database = database
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        headers = {
            role: {"Authorization": f"Bearer {_token(settings, subject)}"}
            for role, subject in subjects.items()
        }
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            provisioned = await client.post(
                "/control/v1/tenants",
                headers=headers["deployment_operator"],
                json={"slug": "provisioned", "name": "Provisioned"},
            )
            assert provisioned.status_code == 201
            assert provisioned.json()["revision"] == 1
            assert (
                await client.get(
                    f"/control/v1/tenants/{tenant_a_id}", headers=headers["viewer"]
                )
            ).status_code == 200
            assert (
                await client.get(
                    f"/control/v1/tenants/{tenant_a_id}",
                    headers=headers["deployment_operator"],
                )
            ).status_code == 404

            assistant_path = f"/control/v1/tenants/{tenant_a_id}/assistants"
            attempts = await asyncio.gather(
                client.post(
                    assistant_path,
                    headers=headers["tenant_admin"],
                    json={"slug": "shared", "name": "Same display name"},
                ),
                client.post(
                    assistant_path,
                    headers=headers["tenant_admin"],
                    json={"slug": "shared", "name": "Same display name"},
                ),
            )
            assert sorted(response.status_code for response in attempts) == [201, 409]
            created = next(
                response for response in attempts if response.status_code == 201
            )
            assistant_id = UUID(created.json()["id"])
            assert created.json()["status"] == "disabled"
            assert "default_personality_profile_version_id" not in created.json()

            assert (
                await client.post(
                    assistant_path,
                    headers=headers["operator"],
                    json={"slug": "operator-write", "name": "Denied"},
                )
            ).status_code == 403
            assert (
                await client.get(
                    f"{assistant_path}/{assistant_id}", headers=headers["auditor"]
                )
            ).status_code == 200
            assert (
                await client.get(
                    f"{assistant_path}/{assistant_id}", headers=headers["operator"]
                )
            ).status_code == 200
            assert (
                await client.get(
                    f"{assistant_path}/{assistant_id}", headers=headers["viewer"]
                )
            ).status_code == 403
            assert (
                await client.get(
                    f"{assistant_path}/{foreign_id}",
                    headers=headers["tenant_owner"],
                )
            ).status_code == 404
            assert (
                await client.get(
                    f"/control/v1/tenants/{tenant_b_id}/assistants/{foreign_id}",
                    headers=headers["tenant_owner"],
                )
            ).status_code == 404
            assert (
                await client.get(
                    f"{assistant_path}/not-a-uuid",
                    headers=headers["tenant_owner"],
                )
            ).status_code == 422
            assert (
                await client.post(
                    assistant_path,
                    headers=headers["deployment_operator"],
                    json={"slug": "authority-only", "name": "Denied"},
                )
            ).status_code == 404

            patches = await asyncio.gather(
                client.patch(
                    f"{assistant_path}/{assistant_id}",
                    headers=headers["tenant_admin"],
                    json={"expected_revision": 1, "name": "Winner A"},
                ),
                client.patch(
                    f"{assistant_path}/{assistant_id}",
                    headers=headers["tenant_admin"],
                    json={"expected_revision": 1, "name": "Winner B"},
                ),
            )
            assert sorted(response.status_code for response in patches) == [200, 409]
            enabled = await client.patch(
                f"{assistant_path}/{assistant_id}",
                headers=headers["tenant_admin"],
                json={"expected_revision": 2, "status": "active"},
            )
            assert enabled.status_code == 200
            assert enabled.json()["revision"] == 3

            connections_path = f"/control/v1/tenants/{tenant_a_id}/connections"
            connection_payload = {
                "assistant_id": str(assistant_id),
                "platform": "telegram",
                "external_bot_id": f"spec030-{uuid4().hex}",
            }
            connection_attempts = await asyncio.gather(
                client.post(
                    connections_path,
                    headers=headers["tenant_admin"],
                    json=connection_payload,
                ),
                client.post(
                    connections_path,
                    headers=headers["tenant_admin"],
                    json=connection_payload,
                ),
            )
            assert sorted(response.status_code for response in connection_attempts) == [
                201,
                409,
            ]
            connection = next(
                response
                for response in connection_attempts
                if response.status_code == 201
            )
            assert connection.status_code == 201
            assert connection.json()["status"] == "disabled"
            connection_id = UUID(connection.json()["id"])
            activated = await client.patch(
                f"{connections_path}/{connection_id}",
                headers=headers["tenant_admin"],
                json={"expected_revision": 1, "status": "active"},
            )
            assert activated.status_code == 200

            admin_lifecycle = await client.patch(
                f"/control/v1/tenants/{tenant_a_id}",
                headers=headers["tenant_admin"],
                json={"expected_revision": 1, "status": "disabled"},
            )
            assert admin_lifecycle.status_code == 403
            disabled = await client.patch(
                f"/control/v1/tenants/{tenant_a_id}",
                headers=headers["tenant_owner"],
                json={"expected_revision": 1, "status": "disabled"},
            )
            assert disabled.status_code == 200
            assert disabled.json()["revision"] == 2

            retired = await client.patch(
                f"{assistant_path}/{assistant_id}",
                headers=headers["tenant_owner"],
                json={"expected_revision": 3, "status": "retired"},
            )
            assert retired.status_code == 200
            immutable = await client.patch(
                f"{assistant_path}/{assistant_id}",
                headers=headers["tenant_owner"],
                json={"expected_revision": 4, "status": "active"},
            )
            assert immutable.status_code == 409

        async with database.session_factory() as session:
            created_assistant = await session.get(AssistantModel, assistant_id)
            created_connection = await session.get(
                PlatformConnectionModel, connection_id
            )
            assert created_assistant is not None
            assert created_assistant.default_personality_profile_version_id is not None
            assert created_connection is not None
            assert created_connection.assistant_id == assistant_id
            provisioned_id = UUID(provisioned.json()["id"])
            owner = await session.scalar(
                select(ControlOperatorMembershipModel).where(
                    ControlOperatorMembershipModel.tenant_id == provisioned_id,
                    ControlOperatorMembershipModel.identity_id
                    == identities["deployment_operator"].id,
                    ControlOperatorMembershipModel.role == "tenant_owner",
                )
            )
            assert owner is not None
    finally:
        await _restore_legacy_tenant(database)
        await database.stop()


def test_control_plane_roles_isolation_lifecycle_and_concurrency() -> None:
    asyncio.run(_control_plane_roles_isolation_lifecycle_and_concurrency())
