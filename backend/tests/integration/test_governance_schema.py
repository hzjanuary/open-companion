"""PostgreSQL proof for SPEC-025 data governance command, export, and retrieval."""

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from functools import partial
from uuid import UUID, uuid4

import httpx
import jwt
import pytest
from sqlalchemy import delete, func, select, text

from app.application.governance_export import GovernanceExportBuilder
from app.application.ports.platform import (
    ChatMember,
    PlatformCapability,
    SentMessage,
)
from app.core.config import Settings
from app.domain.conversation import EligibilityReason, ProcessingOutcome
from app.domain.governance import (
    DEPLOYMENT_EXPORT_CATEGORIES,
    GROUP_EXPORT_CATEGORIES,
    SUBJECT_EXPORT_CATEGORIES,
    ErasureRequestStatus,
    GovernanceAuditEventType,
    GovernanceScope,
)
from app.domain.persistence import (
    AssistantStatus,
    CommandJobStatus,
    ConversationType,
    IngressSource,
    MemoryKind,
    MemoryScope,
    MemoryStatus,
    MemoryVisibility,
    MessageDirection,
    MessageType,
    Platform,
    PlatformConnectionStatus,
)
from app.domain.summary import (
    ConversationSummaryStatus,
    SummaryInvalidationReason,
)
from app.domain.tenancy import LEGACY_TENANT_ID
from app.infrastructure.database.database import Database
from app.infrastructure.database.governance import (
    GovernanceStateCounts,
    SqlAlchemyGovernanceRepository,
)
from app.infrastructure.database.memory import SqlAlchemyMemoryRepository
from app.infrastructure.database.models import (
    AssistantModel as DatabaseAssistantModel,
)
from app.infrastructure.database.models import (
    ControlAuditEventModel,
    ControlDeploymentAuthorityModel,
    ControlDeploymentAuthorityOperationModel,
    ControlOperatorIdentityModel,
    ControlOperatorMembershipModel,
    ControlTenantModel,
    ConversationModel,
    ConversationProcessingRecordModel,
    ConversationSummaryModel,
    GovernanceAuditEventModel,
    GovernanceErasureRequestModel,
    GovernanceExportPackageModel,
    GovernanceExportRequestModel,
    IncomingPlatformUpdateModel,
    MemoryItemModel,
    MessageModel,
    OutboundActionModel,
    ParticipantModel,
    ResponsePlanModel,
    TelegramCommandJobModel,
)
from app.infrastructure.database.models import (
    PlatformConnectionModel as DatabasePlatformConnectionModel,
)
from app.infrastructure.database.personality import ensure_conversation_configuration
from app.infrastructure.database.privacy import SqlAlchemyPrivacyRepository
from app.infrastructure.database.retention import SqlAlchemyRetentionRepository
from app.infrastructure.telemetry import InMemoryMetricsRecorder
from app.main import create_app
from app.runtime.governance_worker import consume_once as consume_governance_once
from app.runtime.outbound_delivery_worker import consume_once as consume_delivery_once
from app.runtime.telegram_command_worker import consume_once as consume_command_once

AssistantModel = partial(
    DatabaseAssistantModel,
    tenant_id=LEGACY_TENANT_ID,
    slug="governance-january",
    status=AssistantStatus.ACTIVE,
)
PlatformConnectionModel = partial(
    DatabasePlatformConnectionModel,
    tenant_id=LEGACY_TENANT_ID,
)


@pytest.mark.integration
@pytest.mark.governance_integration
def test_governance_commands_create_export_requests_and_gate_group_admin(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def scenario() -> None:
        settings = Settings(
            _env_file=None,
            environment="test",
            data_governance_enabled=True,
            command_worker_enabled=True,
            governance_export_ttl_days=2,
        )
        database = Database(settings)
        telemetry = InMemoryMetricsRecorder()
        await database.start()
        try:
            async with database.session_factory() as session:
                async with session.begin():
                    await session.execute(text("TRUNCATE assistants CASCADE"))
                    assistant = AssistantModel(name="January")
                    session.add(assistant)
                    await session.flush()
                    connection = PlatformConnectionModel(
                        assistant_id=assistant.id,
                        platform=Platform.TELEGRAM,
                        external_bot_id="governance-bot",
                        status=PlatformConnectionStatus.ACTIVE,
                    )
                    session.add(connection)
                    await session.flush()
                    group = ConversationModel(
                        platform_connection_id=connection.id,
                        platform_conversation_id="governance-group",
                        conversation_type=ConversationType.GROUP,
                    )
                    session.add(group)
                    await session.flush()
                    await ensure_conversation_configuration(session, assistant, group)
                    admin = ParticipantModel(
                        conversation_id=group.id,
                        platform_user_id="admin-user",
                        display_name="Admin",
                    )
                    member = ParticipantModel(
                        conversation_id=group.id,
                        platform_user_id="member-user",
                        display_name="Member",
                    )
                    session.add_all([admin, member])
                    await session.flush()
                    connection_id = connection.id
                    group_id = group.id
                    admin_id = admin.id
                    member_id = member.id

            async def enqueue(
                name: str, arguments: str, participant_id: UUID, sequence: int
            ) -> UUID:
                async with database.session_factory() as session:
                    async with session.begin():
                        message = MessageModel(
                            conversation_id=group_id,
                            participant_id=participant_id,
                            platform_message_id=f"g-{sequence}",
                            direction=MessageDirection.INCOMING,
                            message_type=MessageType.TEXT,
                            text=f"/{name} {arguments}".strip(),
                        )
                        incoming = IncomingPlatformUpdateModel(
                            platform_connection_id=connection_id,
                            platform=Platform.TELEGRAM,
                            platform_update_id=f"g-{sequence}",
                            update_type="message",
                            ingress_source=IngressSource.POLLING,
                            raw_payload={},
                            received_at=datetime.now(UTC),
                        )
                        session.add_all([message, incoming])
                        await session.flush()
                        record = ConversationProcessingRecordModel(
                            incoming_update_id=incoming.id,
                            outcome=ProcessingOutcome.MESSAGE_CREATED,
                            conversation_id=group_id,
                            message_id=message.id,
                            eligible=False,
                            eligibility_reason=EligibilityReason.COMMAND_HANDOFF,
                        )
                        session.add(record)
                        await session.flush()
                        job = TelegramCommandJobModel(
                            conversation_processing_record_id=record.id,
                            conversation_id=group_id,
                            message_id=message.id,
                            participant_id=participant_id,
                            command_name=name,
                            arguments=arguments,
                        )
                        session.add(job)
                        await session.flush()
                        return job.id

            class Administrator:
                async def get_chat_member(
                    self, conversation_id: str, user_id: str
                ) -> ChatMember:
                    assert user_id == "admin-user"
                    return ChatMember(
                        conversation_id=conversation_id,
                        user_id=user_id,
                        status="administrator",
                        is_administrator=True,
                        is_owner=False,
                        permissions=frozenset(),
                    )

            class Member:
                async def get_chat_member(
                    self, conversation_id: str, user_id: str
                ) -> ChatMember:
                    return ChatMember(
                        conversation_id=conversation_id,
                        user_id=user_id,
                        status="member",
                        is_administrator=False,
                        is_owner=False,
                        permissions=frozenset(),
                    )

            job_ids: list[UUID] = []
            codes: list[str] = []

            async def drive(
                name: str, arguments: str, participant_id: UUID, adapter: object
            ) -> None:
                job_id = await enqueue(name, arguments, participant_id, len(codes) + 1)
                assert (
                    await consume_command_once(
                        settings, database, adapter, "test", telemetry
                    )
                    == 1
                )
                async with database.session_factory() as session:
                    job = await session.get(TelegramCommandJobModel, job_id)
                    assert job is not None
                    codes.append(job.result_code or "")
                    job_ids.append(job_id)

            await drive("export_my_data", "", member_id, Member())
            await drive("export_group_data", "", admin_id, Administrator())
            await drive("export_group_data", "", member_id, Member())
            await drive("data_summary", "", member_id, Member())

            async with database.session_factory() as session:
                rows = list(
                    await session.scalars(
                        select(GovernanceExportRequestModel).order_by(
                            GovernanceExportRequestModel.created_at
                        )
                    )
                )
                assert len(rows) == 2
                assert rows[0].scope == GovernanceScope.SUBJECT
                assert rows[1].scope == GovernanceScope.GROUP
                assert rows[0].participant_id == member_id
                assert rows[1].participant_id == admin_id
                assert set(rows[0].categories) == set(SUBJECT_EXPORT_CATEGORIES)
                assert rows[0].single_use_token_hash is None
                assert rows[0].source_command_job_id == job_ids[0]
                assert rows[1].source_command_job_id == job_ids[1]
                assert rows[0].expires_at is not None
                plans = list(await session.scalars(select(ResponsePlanModel)))
                assert len(plans) == 4
                requested = next(
                    plan
                    for plan in plans
                    if plan.command_job_id == job_ids[0] and plan.text is not None
                )
                assert requested.text is not None
                assert str(rows[0].id) in requested.text
                assert "token" not in requested.text.lower()
                outbound = await session.scalar(
                    select(OutboundActionModel).where(
                        OutboundActionModel.response_plan_id == requested.id
                    )
                )
                assert outbound is not None
                assert outbound.governance_export_request_id == rows[0].id
                assert outbound.text == requested.text
                summary_plan = next(
                    plan
                    for plan in plans
                    if plan.command_job_id == job_ids[3] and plan.text is not None
                )
                assert summary_plan.text is not None
                assert (
                    "profile, preferences, private schedules, your messages "
                    "(including captions and derived voice/audio transcripts), "
                    "and memories" in (summary_plan.text)
                )
                assert "export=requested; erasure=none" in summary_plan.text
                assert "recall=enabled" in summary_plan.text
                assert "owned_explicit=0" in summary_plan.text
                assert "shared_explicit=0" in summary_plan.text
                assert "personal_context=0" in summary_plan.text
                assert "deployment" not in summary_plan.text.lower()
                assert "global" not in summary_plan.text.lower()
            assert codes == [
                "export_requested",
                "export_requested",
                "denied",
                "data_summary",
            ]

            class Delivery:
                def __init__(self) -> None:
                    self.requests: list[object] = []

                @property
                def capabilities(self) -> frozenset[PlatformCapability]:
                    return frozenset({PlatformCapability.SEND_TEXT})

                async def send_text(self, request: object) -> SentMessage:
                    self.requests.append(request)
                    return SentMessage(
                        Platform.TELEGRAM,
                        f"governance-delivery-{len(self.requests)}",
                        "governance-group",
                        "governance-bot",
                        None,
                        datetime.now(UTC),
                    )

                async def send_sticker(self, request: object) -> SentMessage:
                    raise AssertionError("governance replies are text")

            delivery_settings = Settings(
                _env_file=None,
                environment="test",
                data_governance_enabled=True,
                telegram_enabled=True,
                telegram_bot_token="fake-token",
                telegram_platform_connection_id=connection_id,
                outbound_delivery_enabled=True,
            )
            delivery = Delivery()
            assert (
                await consume_delivery_once(
                    delivery_settings,
                    database,
                    delivery,  # type: ignore[arg-type]
                    telemetry=telemetry,
                )
                == 4
            )
            rendered = [str(getattr(item, "text", "")) for item in delivery.requests]
            credentials = [
                line.partition(": ")[2]
                for body in rendered
                for line in body.splitlines()
                if line.startswith("Single-use retrieval credential: ")
            ]
            assert len(credentials) == 2
            async with database.session_factory() as session:
                persisted_text = list(
                    await session.scalars(select(OutboundActionModel.text))
                )
                persisted_text.extend(
                    await session.scalars(select(ResponsePlanModel.text))
                )
                persisted_text.extend(await session.scalars(select(MessageModel.text)))
                assert all(
                    credential not in text
                    for credential in credentials
                    for text in persisted_text
                    if text is not None
                )
                token_hashes = set(
                    await session.scalars(
                        select(
                            GovernanceExportRequestModel.single_use_token_hash
                        ).where(
                            GovernanceExportRequestModel.single_use_token_hash.is_not(
                                None
                            )
                        )
                    )
                )
                assert token_hashes == {
                    hashlib.sha256(value.encode("ascii")).hexdigest()
                    for value in credentials
                }
                audit_text = "\n".join(
                    f"{row.request_id} {row.outcome} {row.detail} {row.metadata_}"
                    for row in await session.scalars(select(GovernanceAuditEventModel))
                )
                assert all(value not in audit_text for value in credentials)

            assert all(value not in caplog.text for value in credentials)
            metrics = telemetry.exposition()
            assert all(value not in metrics for value in credentials)

            repository = SqlAlchemyGovernanceRepository(database.session_factory)
            raced = await asyncio.gather(
                *(
                    repository.create_export_request(
                        scope=GovernanceScope.SUBJECT,
                        conversation_id=group_id,
                        participant_id=member_id,
                        tenant_id=None,
                        token_hash=None,
                        categories=SUBJECT_EXPORT_CATEGORIES,
                        ttl_days=2,
                        source_command_job_id=job_ids[2],
                    )
                    for _ in range(2)
                )
            )
            assert raced[0].id == raced[1].id
            assert sorted(item.created for item in raced) == [False, True]
            async with database.session_factory() as session:
                assert (
                    await session.scalar(
                        select(func.count(GovernanceExportRequestModel.id)).where(
                            GovernanceExportRequestModel.source_command_job_id
                            == job_ids[2]
                        )
                    )
                    == 1
                )
            assert await consume_command_once(settings, database, Member(), "test") == 0
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.governance_integration
def test_governance_gates_private_group_export_and_disabled_mode() -> None:
    async def scenario() -> None:
        settings = Settings(
            _env_file=None,
            environment="test",
            data_governance_enabled=True,
            command_worker_enabled=True,
        )
        database = Database(settings)
        await database.start()
        try:
            async with database.session_factory() as session:
                async with session.begin():
                    await session.execute(text("TRUNCATE assistants CASCADE"))
                    assistant = AssistantModel(name="January")
                    session.add(assistant)
                    await session.flush()
                    connection = PlatformConnectionModel(
                        assistant_id=assistant.id,
                        platform=Platform.TELEGRAM,
                        external_bot_id="governance-private-bot",
                        status=PlatformConnectionStatus.ACTIVE,
                    )
                    session.add(connection)
                    await session.flush()
                    private = ConversationModel(
                        platform_connection_id=connection.id,
                        platform_conversation_id="governance-private",
                        conversation_type=ConversationType.PRIVATE,
                    )
                    session.add(private)
                    await session.flush()
                    await ensure_conversation_configuration(session, assistant, private)
                    participant = ParticipantModel(
                        conversation_id=private.id,
                        platform_user_id="private-user",
                        display_name="Private",
                    )
                    session.add(participant)
                    await session.flush()
                    connection_id = connection.id
                    private_id = private.id
                    participant_id = participant.id

            async def enqueue(name: str, arguments: str, sequence: int) -> UUID:
                async with database.session_factory() as session:
                    async with session.begin():
                        message = MessageModel(
                            conversation_id=private_id,
                            participant_id=participant_id,
                            platform_message_id=f"p-{sequence}",
                            direction=MessageDirection.INCOMING,
                            message_type=MessageType.TEXT,
                            text=f"/{name} {arguments}".strip(),
                        )
                        incoming = IncomingPlatformUpdateModel(
                            platform_connection_id=connection_id,
                            platform=Platform.TELEGRAM,
                            platform_update_id=f"p-{sequence}",
                            update_type="message",
                            ingress_source=IngressSource.POLLING,
                            raw_payload={},
                            received_at=datetime.now(UTC),
                        )
                        session.add_all([message, incoming])
                        await session.flush()
                        record = ConversationProcessingRecordModel(
                            incoming_update_id=incoming.id,
                            outcome=ProcessingOutcome.MESSAGE_CREATED,
                            conversation_id=private_id,
                            message_id=message.id,
                            eligible=False,
                            eligibility_reason=EligibilityReason.COMMAND_HANDOFF,
                        )
                        session.add(record)
                        await session.flush()
                        job = TelegramCommandJobModel(
                            conversation_processing_record_id=record.id,
                            conversation_id=private_id,
                            message_id=message.id,
                            participant_id=participant_id,
                            command_name=name,
                            arguments=arguments,
                        )
                        session.add(job)
                        await session.flush()
                        return job.id

            class UnreachableAdapter:
                async def get_chat_member(self, *_args: str) -> ChatMember:
                    raise AssertionError("private chat must not authorize remotely")

            private_job = await enqueue("export_group_data", "", 1)
            assert (
                await consume_command_once(
                    settings, database, UnreachableAdapter(), "test"
                )
                == 1
            )

            disabled_settings = Settings(
                _env_file=None,
                environment="test",
                data_governance_enabled=False,
                command_worker_enabled=True,
            )
            disabled_job = await enqueue("export_my_data", "", 2)
            assert (
                await consume_command_once(disabled_settings, database, None, "test")
                == 1
            )

            async with database.session_factory() as session:
                assert (
                    await session.scalar(
                        select(func.count(GovernanceExportRequestModel.id))
                    )
                    == 0
                )
                private_result = await session.get(TelegramCommandJobModel, private_job)
                disabled_result = await session.get(
                    TelegramCommandJobModel, disabled_job
                )
                assert private_result is not None
                assert disabled_result is not None
                assert private_result.result_code == "export_group_private"
                assert disabled_result.result_code == "governance_disabled"
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.governance_integration
def test_subject_export_materializes_retrieves_once_and_audits() -> None:
    async def scenario() -> None:
        settings = Settings(
            _env_file=None,
            environment="test",
            data_governance_enabled=True,
            governance_worker_enabled=True,
            governance_export_batch_size=5,
            governance_export_lease_seconds=60,
        )
        database = Database(settings)
        telemetry = InMemoryMetricsRecorder()
        await database.start()
        try:
            async with database.session_factory() as session:
                async with session.begin():
                    await session.execute(text("TRUNCATE assistants CASCADE"))
                    assistant = AssistantModel(name="January")
                    session.add(assistant)
                    await session.flush()
                    connection = PlatformConnectionModel(
                        assistant_id=assistant.id,
                        platform=Platform.TELEGRAM,
                        external_bot_id="materialize-bot",
                        status=PlatformConnectionStatus.ACTIVE,
                    )
                    session.add(connection)
                    await session.flush()
                    conversation = ConversationModel(
                        platform_connection_id=connection.id,
                        platform_conversation_id="materialize-chat",
                        conversation_type=ConversationType.GROUP,
                    )
                    other_conversation = ConversationModel(
                        platform_connection_id=connection.id,
                        platform_conversation_id="materialize-other-chat",
                        conversation_type=ConversationType.GROUP,
                    )
                    session.add_all([conversation, other_conversation])
                    await session.flush()
                    await ensure_conversation_configuration(
                        session, assistant, conversation
                    )
                    participant = ParticipantModel(
                        conversation_id=conversation.id,
                        platform_user_id="materialize-user",
                        display_name="Subject",
                    )
                    session.add(participant)
                    await session.flush()
                    message = MessageModel(
                        conversation_id=conversation.id,
                        participant_id=participant.id,
                        platform_message_id="m-1",
                        direction=MessageDirection.INCOMING,
                        message_type=MessageType.TEXT,
                        text="record this",
                        mentions_assistant=True,
                        replies_to_assistant=False,
                        eligible=True,
                    )
                    session.add(message)
                    await session.flush()
                    conversation_id = conversation.id
                    other_conversation_id = other_conversation.id
                    participant_id = participant.id

            repository = SqlAlchemyGovernanceRepository(database.session_factory)
            token = "materialize-single-use-token"
            token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
            created = await repository.create_export_request(
                scope=GovernanceScope.SUBJECT,
                conversation_id=conversation_id,
                participant_id=participant_id,
                tenant_id=None,
                token_hash=token_hash,
                categories=SUBJECT_EXPORT_CATEGORIES,
                ttl_days=2,
            )
            assert created.status == "requested"
            assert (
                await consume_governance_once(settings, database, telemetry=telemetry)
                == 1
            )
            finished = await repository.get_export_request(created.id)
            assert finished is not None
            assert finished.status == "complete"
            assert finished.completed_at is not None

            retrievals = await asyncio.gather(
                repository.retrieve_export_by_token(token_hash),
                repository.retrieve_export_by_token(token_hash),
            )
            assert sum(item is not None for item in retrievals) == 1
            first = next(item for item in retrievals if item is not None)
            assert first is not None
            assert first.manifest == {
                "schema_version": "governance-export-v1",
                "request_id": str(created.id),
                "scope": "subject",
                "generated_at": first.manifest["generated_at"],
                "categories": list(SUBJECT_EXPORT_CATEGORIES),
            }
            assert first.package["schema_version"]
            assert first.package["manifest"] == first.manifest
            messages = first.package["data"]["messages"]
            assert messages[0]["text"] == "record this"

            assert await repository.retrieve_export_by_token(token_hash) is None

            builder = GovernanceExportBuilder(database.session_factory)
            with pytest.raises(
                ValueError, match="participant not found in export conversation"
            ):
                await builder.build_subject_export(
                    request_id=uuid4(),
                    conversation_id=other_conversation_id,
                    participant_id=participant_id,
                )
            group_request_id = uuid4()
            group_package = await builder.build_group_export(
                request_id=group_request_id,
                conversation_id=conversation_id,
            )
            assert group_package["manifest"] == {
                "schema_version": "governance-export-v1",
                "request_id": str(group_request_id),
                "scope": "group",
                "generated_at": group_package["manifest"]["generated_at"],
                "categories": [
                    "configuration",
                    "personality",
                    "safety",
                    "revision_history",
                    "memories",
                ],
            }
            deployment_package = await builder.build_deployment_snapshot(
                request_id="deployment-request",
                settings=settings,
                governance_counts=GovernanceStateCounts(0, 0, 0, 0, 0, 0, 0, 0),
            )
            assert deployment_package["manifest"] == {
                "schema_version": "governance-export-v1",
                "request_id": "deployment-request",
                "scope": "deployment",
                "generated_at": deployment_package["manifest"]["generated_at"],
                "categories": list(DEPLOYMENT_EXPORT_CATEGORIES),
            }

            invalid = await repository.create_export_request(
                scope=GovernanceScope.DEPLOYMENT,
                conversation_id=None,
                participant_id=None,
                tenant_id=None,
                token_hash=None,
                categories=DEPLOYMENT_EXPORT_CATEGORIES,
                ttl_days=2,
            )
            assert (
                await consume_governance_once(settings, database, telemetry=telemetry)
                == 0
            )
            failed = await repository.get_export_request(invalid.id)
            assert failed is not None
            assert failed.status == "failed"
            metrics = telemetry.exposition()
            assert (
                'january_governance_export_requests_total{outcome="complete",scope="subject"}'
                in metrics
            )
            assert (
                'january_governance_export_requests_total{outcome="failed",scope="deployment"}'
                in metrics
            )
            assert (
                'january_worker_operation_duration_seconds_count{operation="export_batch",outcome="failed",runtime="governance"}'
                in metrics
            )

            async with database.session_factory() as session:
                assert (
                    await session.scalar(
                        select(func.count(GovernanceExportRequestModel.id))
                    )
                    == 2
                )
                retrieved = await session.get(GovernanceExportRequestModel, created.id)
                assert retrieved is not None
                assert retrieved.status == "retrieved"
                assert retrieved.retrieved_at is not None
                event_types = list(
                    await session.scalars(
                        select(GovernanceAuditEventModel.event_type).where(
                            GovernanceAuditEventModel.conversation_id == conversation_id
                        )
                    )
                )
                assert GovernanceAuditEventType.EXPORT_REQUEST in event_types
                assert GovernanceAuditEventType.EXPORT_COMPLETE in event_types
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.governance_integration
def test_retrieval_is_single_use_and_deployment_export_requires_operator(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def scenario() -> None:
        deployment_subject = f"deployment-sub-{uuid4().hex[:8]}"
        alternate_bootstrap_subject = f"deployment-alt-{uuid4().hex[:8]}"
        settings = Settings(
            _env_file=None,
            environment="test",
            data_governance_enabled=True,
            governance_worker_enabled=True,
            governance_export_ttl_days=2,
            control_plane_enabled=True,
            control_plane_jwt_secret="s" * 40,
            control_plane_jwt_issuer="issuer",
            control_plane_jwt_audience="audience",
            control_plane_deployment_bootstrap_subjects=(
                deployment_subject,
                alternate_bootstrap_subject,
            ),
            metrics_enabled=True,
        )
        database = Database(settings)
        await database.start()
        try:
            async with database.session_factory() as session:
                async with session.begin():
                    await session.execute(text("TRUNCATE assistants CASCADE"))
                    await session.execute(
                        text("TRUNCATE control_operator_identities CASCADE")
                    )
                    await session.execute(
                        text("TRUNCATE control_deployment_authorities CASCADE")
                    )
                    await session.execute(
                        text(
                            "TRUNCATE governance_export_requests, "
                            "governance_export_packages, "
                            "governance_erasure_requests CASCADE"
                        )
                    )
                    await session.execute(
                        delete(ControlAuditEventModel).where(
                            ControlAuditEventModel.action.in_(
                                [
                                    "deployment_authority.grant",
                                    "deployment_authority.revoke",
                                    "governance.deployment_export",
                                ]
                            )
                        )
                    )
                    assistant = AssistantModel(name="January")
                    session.add(assistant)
                    await session.flush()
                    connection = PlatformConnectionModel(
                        assistant_id=assistant.id,
                        platform=Platform.TELEGRAM,
                        external_bot_id="http-bot",
                        status=PlatformConnectionStatus.ACTIVE,
                    )
                    session.add(connection)
                    await session.flush()
                    conversation = ConversationModel(
                        platform_connection_id=connection.id,
                        platform_conversation_id="http-chat",
                        conversation_type=ConversationType.GROUP,
                    )
                    session.add(conversation)
                    await session.flush()
                    await ensure_conversation_configuration(
                        session, assistant, conversation
                    )
                    participant = ParticipantModel(
                        conversation_id=conversation.id,
                        platform_user_id="http-user",
                        display_name="Subject",
                    )
                    session.add(participant)
                    await session.flush()
                    message = MessageModel(
                        conversation_id=conversation.id,
                        participant_id=participant.id,
                        platform_message_id="h-1",
                        direction=MessageDirection.INCOMING,
                        message_type=MessageType.TEXT,
                        text="http export",
                        mentions_assistant=True,
                        replies_to_assistant=False,
                        eligible=True,
                    )
                    session.add(message)
                    await session.flush()
                    conversation_id = conversation.id
                    participant_id = participant.id

            repository = SqlAlchemyGovernanceRepository(database.session_factory)
            token = "http-retrieval-token"
            token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
            created = await repository.create_export_request(
                scope=GovernanceScope.SUBJECT,
                conversation_id=conversation_id,
                participant_id=participant_id,
                tenant_id=None,
                token_hash=token_hash,
                categories=SUBJECT_EXPORT_CATEGORIES,
                ttl_days=2,
            )
            assert await consume_governance_once(settings, database) == 1
            finished = await repository.get_export_request(created.id)
            assert finished is not None and finished.status == "complete"

            expired_token = "expired-http-retrieval-token"
            expired_hash = hashlib.sha256(expired_token.encode("ascii")).hexdigest()
            expired_at = datetime.now(UTC) - timedelta(days=3)
            expired = await repository.create_export_request(
                scope=GovernanceScope.SUBJECT,
                conversation_id=conversation_id,
                participant_id=participant_id,
                tenant_id=None,
                token_hash=expired_hash,
                categories=SUBJECT_EXPORT_CATEGORIES,
                ttl_days=2,
                now=expired_at,
            )
            assert await repository.claim_export_request(
                request_id=expired.id,
                lease_owner="expired-test",
                lease_seconds=60,
                max_attempts=5,
                now=expired_at,
            )
            assert await repository.complete_export(
                request_id=expired.id,
                schema_version="governance-export-v1",
                manifest={"scope": "subject"},
                package={"expired": True},
                expires_at=expired_at + timedelta(days=2),
                now=expired_at,
            )
            assert (
                await repository.retrieve_export_by_token(
                    expired_hash, now=datetime.now(UTC)
                )
                is None
            )

            app = create_app(settings)
            app.state.database = database
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                missing = await client.post(
                    "/api/v1/governance/exports/retrieve",
                    headers={"Authorization": "Bearer definitely-not-a-token"},
                )
                assert missing.status_code == 404
                no_header = await client.post("/api/v1/governance/exports/retrieve")
                assert no_header.status_code == 401
                first = await client.post(
                    "/api/v1/governance/exports/retrieve",
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert first.status_code == 200
                assert token not in str(first.request.url)
                assert first.request.url.query == b""
                assert first.headers["cache-control"] == "no-store"
                assert first.json()["data"]["messages"][0]["text"] == "http export"
                second = await client.post(
                    "/api/v1/governance/exports/retrieve",
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert second.status_code == 404

            governance_paths = [
                path for path in app.openapi()["paths"] if "governance/exports" in path
            ]
            assert governance_paths == ["/api/v1/governance/exports/retrieve"]
            assert all("{" not in path and "?" not in path for path in governance_paths)

            assert token not in caplog.text

            tenant_id = uuid4()
            other_tenant_id = uuid4()
            admin_subject = f"owner-sub-{uuid4().hex[:8]}"
            tenant_admin_subject = f"admin-sub-{uuid4().hex[:8]}"
            other_owner_subject = f"other-owner-sub-{uuid4().hex[:8]}"
            group_admin_subject = "admin-user"
            delegated_subject = f"delegated-sub-{uuid4().hex[:8]}"
            disabled_subject = f"disabled-sub-{uuid4().hex[:8]}"
            async with database.session_factory() as session:
                async with session.begin():
                    session.add_all(
                        [
                            ControlTenantModel(
                                id=tenant_id,
                                slug=f"http-tenant-{uuid4().hex[:8]}",
                                name="HTTP Tenant",
                            ),
                            ControlTenantModel(
                                id=other_tenant_id,
                                slug=f"other-tenant-{uuid4().hex[:8]}",
                                name="Other Tenant",
                            ),
                        ]
                    )
                    identities = {
                        subject: ControlOperatorIdentityModel(
                            issuer="issuer", subject=subject, display_name=label
                        )
                        for subject, label in (
                            (admin_subject, "Owner"),
                            (tenant_admin_subject, "Tenant admin"),
                            (other_owner_subject, "Other owner"),
                            (group_admin_subject, "Telegram group admin"),
                            (delegated_subject, "Deployment operator"),
                            (disabled_subject, "Disabled identity"),
                        )
                    }
                    identities[disabled_subject].disabled_at = datetime.now(UTC)
                    session.add_all(list(identities.values()))
                    await session.flush()
                    session.add_all(
                        [
                            ControlOperatorMembershipModel(
                                tenant_id=tenant_id,
                                identity_id=identities[admin_subject].id,
                                role="tenant_owner",
                            ),
                            ControlOperatorMembershipModel(
                                tenant_id=tenant_id,
                                identity_id=identities[tenant_admin_subject].id,
                                role="tenant_admin",
                            ),
                            ControlOperatorMembershipModel(
                                tenant_id=other_tenant_id,
                                identity_id=identities[other_owner_subject].id,
                                role="tenant_owner",
                            ),
                        ]
                    )
                    delegated_identity_id = identities[delegated_subject].id
                    disabled_identity_id = identities[disabled_subject].id

            def control_token(subject: str) -> str:
                return jwt.encode(
                    {
                        "iss": "issuer",
                        "sub": subject,
                        "aud": "audience",
                        "exp": datetime.now(UTC) + timedelta(hours=1),
                    },
                    settings.control_plane_jwt_secret.get_secret_value(),
                    algorithm="HS256",
                )

            deployment_token = control_token(deployment_subject)
            alternate_bootstrap_token = control_token(alternate_bootstrap_subject)
            delegated_token = control_token(delegated_subject)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                anon = await client.post("/control/v1/governance/deployment/export")
                assert anon.status_code == 401

                for index, subject in enumerate(
                    (
                        admin_subject,
                        tenant_admin_subject,
                        other_owner_subject,
                        group_admin_subject,
                    )
                ):
                    rejected = await client.post(
                        "/control/v1/governance/deployment/export",
                        headers={
                            "Authorization": f"Bearer {control_token(subject)}",
                            "X-Request-ID": f"deployment-denied-{index}",
                        },
                    )
                    assert rejected.status_code == 403

                # Authentication creates the configured bootstrap identity, but
                # does not grant authority until the explicit self-grant.
                before = await client.get(
                    "/control/v1/me",
                    headers={"Authorization": f"Bearer {deployment_token}"},
                )
                assert before.status_code == 200
                assert before.json()["deployment_operator"] is False
                deployment_identity_id = UUID(before.json()["identity_id"])
                alternate_before = await client.get(
                    "/control/v1/me",
                    headers={"Authorization": f"Bearer {alternate_bootstrap_token}"},
                )
                assert alternate_before.status_code == 200
                alternate_identity_id = UUID(alternate_before.json()["identity_id"])

                bootstrap_path = (
                    f"/control/v1/deployment/authorities/{deployment_identity_id}"
                )
                alternate_bootstrap_path = (
                    f"/control/v1/deployment/authorities/{alternate_identity_id}"
                )
                bootstrap_attempts = await asyncio.gather(
                    client.put(
                        bootstrap_path,
                        headers={
                            "Authorization": f"Bearer {deployment_token}",
                            "X-Request-ID": "bootstrap-grant-a",
                        },
                    ),
                    client.put(
                        alternate_bootstrap_path,
                        headers={
                            "Authorization": f"Bearer {alternate_bootstrap_token}",
                            "X-Request-ID": "bootstrap-grant-b",
                        },
                    ),
                )
                assert sorted(
                    response.status_code for response in bootstrap_attempts
                ) == [200, 403]
                winner = next(
                    index
                    for index, response in enumerate(bootstrap_attempts)
                    if response.status_code == 200
                )
                root_token = (
                    deployment_token if winner == 0 else alternate_bootstrap_token
                )
                root_path = bootstrap_path if winner == 0 else alternate_bootstrap_path
                root_request_id = (
                    "bootstrap-grant-a" if winner == 0 else "bootstrap-grant-b"
                )
                assert bootstrap_attempts[winner].json()["changed"] is True
                replayed_grant = await client.put(
                    root_path,
                    headers={
                        "Authorization": f"Bearer {root_token}",
                        "X-Request-ID": root_request_id,
                    },
                )
                assert replayed_grant.status_code == 200
                assert replayed_grant.json()["changed"] is False

                disabled_grant = await client.put(
                    f"/control/v1/deployment/authorities/{disabled_identity_id}",
                    headers={
                        "Authorization": f"Bearer {root_token}",
                        "X-Request-ID": "disabled-grant",
                    },
                )
                assert disabled_grant.status_code == 404

                delegated_path = (
                    f"/control/v1/deployment/authorities/{delegated_identity_id}"
                )
                concurrent_grants = await asyncio.gather(
                    client.put(
                        delegated_path,
                        headers={
                            "Authorization": f"Bearer {root_token}",
                            "X-Request-ID": "delegated-grant-a",
                        },
                    ),
                    client.put(
                        delegated_path,
                        headers={
                            "Authorization": f"Bearer {root_token}",
                            "X-Request-ID": "delegated-grant-b",
                        },
                    ),
                )
                assert [response.status_code for response in concurrent_grants] == [
                    200,
                    200,
                ]
                assert sorted(
                    response.json()["changed"] for response in concurrent_grants
                ) == [False, True]
                grant_replay = await client.put(
                    delegated_path,
                    headers={
                        "Authorization": f"Bearer {root_token}",
                        "X-Request-ID": "delegated-grant-a",
                    },
                )
                assert grant_replay.status_code == 200
                assert grant_replay.json()["changed"] is False
                mismatched_replay = await client.put(
                    root_path,
                    headers={
                        "Authorization": f"Bearer {root_token}",
                        "X-Request-ID": "delegated-grant-a",
                    },
                )
                assert mismatched_replay.status_code == 409

                # Deployment authority does not confer tenant membership.
                tenant_access = await client.get(
                    f"/control/v1/tenants/{tenant_id}/assistants",
                    headers={"Authorization": f"Bearer {delegated_token}"},
                )
                assert tenant_access.status_code == 404

                deployment_control_request_id = "d" * 128
                export_headers = {
                    "Authorization": f"Bearer {delegated_token}",
                    "X-Request-ID": deployment_control_request_id,
                }
                pending = await client.post(
                    "/control/v1/governance/deployment/export",
                    headers=export_headers,
                )
                assert pending.status_code == 202
                assert pending.headers["cache-control"] == "no-store"
                assert pending.headers["retry-after"] == "1"
                assert "retrieval_credential" not in pending.json()
                deployment_request_id = UUID(pending.json()["request_id"])
                pending_replay = await client.post(
                    "/control/v1/governance/deployment/export",
                    headers=export_headers,
                )
                assert pending_replay.status_code == 202
                assert pending_replay.json()["request_id"] == str(deployment_request_id)

                assert (
                    await consume_governance_once(
                        settings,
                        database,
                        telemetry=app.state.telemetry,
                    )
                    == 2
                )
                exported = await client.post(
                    "/control/v1/governance/deployment/export",
                    headers=export_headers,
                )
                assert exported.status_code == 200
                assert exported.headers["cache-control"] == "no-store"
                export_body = exported.json()
                credential = export_body["retrieval_credential"]
                assert UUID(export_body["request_id"]) == deployment_request_id
                assert credential not in str(exported.request.url)
                assert exported.request.url.query == b""

                export_replay = await client.post(
                    "/control/v1/governance/deployment/export",
                    headers=export_headers,
                )
                assert export_replay.status_code == 409

                async with database.session_factory() as session:
                    request_row = await session.get(
                        GovernanceExportRequestModel, deployment_request_id
                    )
                    assert request_row is not None
                    assert (
                        request_row.single_use_token_hash
                        == hashlib.sha256(credential.encode("ascii")).hexdigest()
                    )
                    assert (
                        await session.scalar(
                            select(func.count())
                            .select_from(GovernanceExportRequestModel)
                            .where(
                                GovernanceExportRequestModel.source_control_identity_id
                                == delegated_identity_id,
                                GovernanceExportRequestModel.source_control_request_id
                                == deployment_control_request_id,
                            )
                        )
                        == 1
                    )
                    persisted_text = " ".join(
                        value or ""
                        for value in (
                            list(await session.scalars(select(ResponsePlanModel.text)))
                            + list(
                                await session.scalars(select(OutboundActionModel.text))
                            )
                        )
                    )
                    assert credential not in persisted_text

                retrieved_deployment = await client.post(
                    "/api/v1/governance/exports/retrieve",
                    headers={"Authorization": f"Bearer {credential}"},
                )
                assert retrieved_deployment.status_code == 200
                deployment_package = retrieved_deployment.json()
                assert deployment_package["schema_version"] == "governance-export-v1"
                assert deployment_package["manifest"] == {
                    "schema_version": "governance-export-v1",
                    "request_id": str(deployment_request_id),
                    "scope": "deployment",
                    "generated_at": deployment_package["manifest"]["generated_at"],
                    "categories": list(DEPLOYMENT_EXPORT_CATEGORIES),
                }
                inventory_names = {
                    item["category"]
                    for item in deployment_package["data"]["data_inventory"][
                        "categories"
                    ]
                }
                assert "control_deployment_authorities" in inventory_names
                assert "control_deployment_authority_operations" in inventory_names
                assert (
                    deployment_package["data"]["data_volumes"][
                        "control_deployment_authorities"
                    ]
                    == 2
                )
                assert (
                    deployment_package["data"]["data_volumes"][
                        "control_deployment_authority_operations"
                    ]
                    == 3
                )
                governance_state = deployment_package["data"]["governance_state"]
                assert governance_state["export_pending"] >= 2
                assert governance_state["export_retrieved"] >= 1
                assert governance_state["packages_cleared"] >= 1
                assert governance_state["audit_events"] >= 6

                pending_before_revoke = await client.post(
                    "/control/v1/governance/deployment/export",
                    headers={
                        "Authorization": f"Bearer {delegated_token}",
                        "X-Request-ID": "pending-before-revoke",
                    },
                )
                assert pending_before_revoke.status_code == 202
                revoked_pending_request_id = UUID(
                    pending_before_revoke.json()["request_id"]
                )

                revoked = await client.delete(
                    delegated_path,
                    headers={
                        "Authorization": f"Bearer {root_token}",
                        "X-Request-ID": "delegated-revoke",
                    },
                )
                assert revoked.status_code == 204
                revoke_replay = await client.delete(
                    delegated_path,
                    headers={
                        "Authorization": f"Bearer {root_token}",
                        "X-Request-ID": "delegated-revoke",
                    },
                )
                assert revoke_replay.status_code == 204
                assert (
                    await consume_governance_once(
                        settings,
                        database,
                        telemetry=app.state.telemetry,
                    )
                    == 0
                )
                async with database.session_factory() as session:
                    revoked_pending = await session.get(
                        GovernanceExportRequestModel, revoked_pending_request_id
                    )
                    assert revoked_pending is not None
                    assert revoked_pending.status == "failed"
                    assert revoked_pending.failure_reason == "authorization_revoked"
                    revoked_failure_audit = await session.scalar(
                        select(GovernanceAuditEventModel).where(
                            GovernanceAuditEventModel.request_id
                            == str(revoked_pending_request_id),
                            GovernanceAuditEventModel.event_type
                            == GovernanceAuditEventType.EXPORT_FAILED,
                        )
                    )
                    assert revoked_failure_audit is not None
                    assert revoked_failure_audit.detail == "authorization_revoked"
                    assert (
                        await session.scalar(
                            select(func.count())
                            .select_from(GovernanceExportPackageModel)
                            .where(
                                GovernanceExportPackageModel.export_request_id
                                == revoked_pending_request_id
                            )
                        )
                        == 0
                    )
                stale_grant_replay = await client.put(
                    delegated_path,
                    headers={
                        "Authorization": f"Bearer {root_token}",
                        "X-Request-ID": "delegated-grant-a",
                    },
                )
                assert stale_grant_replay.status_code == 200
                assert stale_grant_replay.json()["changed"] is False
                revoked_export = await client.post(
                    "/control/v1/governance/deployment/export",
                    headers={
                        "Authorization": f"Bearer {delegated_token}",
                        "X-Request-ID": "revoked-export",
                    },
                )
                assert revoked_export.status_code == 403
                after = await client.get(
                    "/control/v1/me",
                    headers={"Authorization": f"Bearer {delegated_token}"},
                )
                assert after.json()["deployment_operator"] is False

            assert credential not in caplog.text
            metrics_text = app.state.telemetry.exposition()
            assert credential not in metrics_text
            assert (
                'january_governance_export_requests_total{outcome="requested",scope="deployment"}'
                in metrics_text
            )
            assert (
                'january_governance_export_requests_total{outcome="complete",scope="deployment"}'
                in metrics_text
            )
            assert (
                'january_governance_export_requests_total{outcome="failed",scope="deployment"}'
                in metrics_text
            )

            async with database.session_factory() as session:
                event_types = list(
                    await session.scalars(select(GovernanceAuditEventModel.event_type))
                )
                assert GovernanceAuditEventType.EXPORT_RETRIEVED in event_types
                assert GovernanceAuditEventType.EXPORT_REQUEST in event_types
                assert GovernanceAuditEventType.EXPORT_COMPLETE in event_types
                retrieved_event = await session.scalar(
                    select(GovernanceAuditEventModel).where(
                        GovernanceAuditEventModel.event_type
                        == GovernanceAuditEventType.EXPORT_RETRIEVED
                    )
                )
                assert retrieved_event is not None
                assert retrieved_event.request_id == str(created.id)
                authority_rows = list(
                    await session.scalars(select(ControlDeploymentAuthorityModel))
                )
                assert len(authority_rows) == 2
                assert sum(row.revoked_at is None for row in authority_rows) == 1
                assert (
                    await session.scalar(
                        select(func.count()).select_from(
                            ControlDeploymentAuthorityOperationModel
                        )
                    )
                    == 4
                )
                authority_audits = list(
                    await session.scalars(
                        select(ControlAuditEventModel).where(
                            ControlAuditEventModel.action.in_(
                                [
                                    "deployment_authority.grant",
                                    "deployment_authority.revoke",
                                ]
                            ),
                            ControlAuditEventModel.outcome == "success",
                        )
                    )
                )
                assert len(authority_audits) == 3
                assert all(event.tenant_id is None for event in authority_audits)
                failed_authority_audits = list(
                    await session.scalars(
                        select(ControlAuditEventModel).where(
                            ControlAuditEventModel.action
                            == "deployment_authority.grant",
                            ControlAuditEventModel.outcome == "failed",
                            ControlAuditEventModel.resource_id
                            == str(disabled_identity_id),
                        )
                    )
                )
                assert len(failed_authority_audits) == 1
                export_authorizations = list(
                    await session.scalars(
                        select(ControlAuditEventModel).where(
                            ControlAuditEventModel.action
                            == "governance.deployment_export",
                            ControlAuditEventModel.outcome == "authorized",
                            ControlAuditEventModel.request_id
                            == deployment_control_request_id,
                        )
                    )
                )
                assert len(export_authorizations) == 1
                assert export_authorizations[0].resource_id == str(
                    deployment_request_id
                )
                credential_issuance_audits = list(
                    await session.scalars(
                        select(ControlAuditEventModel).where(
                            ControlAuditEventModel.action
                            == "governance.deployment_export.credential_issued",
                            ControlAuditEventModel.outcome == "authorized",
                            ControlAuditEventModel.request_id
                            == deployment_control_request_id,
                        )
                    )
                )
                assert len(credential_issuance_audits) == 1
                assert credential_issuance_audits[0].resource_id == str(
                    deployment_request_id
                )
                export_denials = list(
                    await session.scalars(
                        select(ControlAuditEventModel).where(
                            ControlAuditEventModel.action
                            == "governance.deployment_export",
                            ControlAuditEventModel.outcome == "denied",
                        )
                    )
                )
                assert len(export_denials) == 5
                assert all(event.tenant_id is None for event in export_denials)
                serialized_audits = " ".join(
                    f"{event.action} {event.outcome} {event.metadata_}"
                    for event in (
                        authority_audits
                        + failed_authority_audits
                        + export_authorizations
                        + credential_issuance_audits
                    )
                )
                assert credential not in serialized_audits
                governance_audits = list(
                    await session.scalars(select(GovernanceAuditEventModel))
                )
                assert credential not in " ".join(
                    f"{event.event_type} {event.outcome} {event.detail or ''}"
                    for event in governance_audits
                )
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.governance_integration
def test_group_reset_invalidates_derived_summaries() -> None:
    async def scenario() -> None:
        settings = Settings(_env_file=None, environment="test")
        database = Database(settings)
        await database.start()
        try:
            async with database.session_factory() as session:
                async with session.begin():
                    await session.execute(text("TRUNCATE assistants CASCADE"))
                    assistant = AssistantModel(name="January")
                    session.add(assistant)
                    await session.flush()
                    connection = PlatformConnectionModel(
                        assistant_id=assistant.id,
                        platform=Platform.TELEGRAM,
                        external_bot_id="group-reset-bot",
                        status=PlatformConnectionStatus.ACTIVE,
                    )
                    session.add(connection)
                    await session.flush()
                    conversation = ConversationModel(
                        platform_connection_id=connection.id,
                        platform_conversation_id="group-reset-chat",
                        conversation_type=ConversationType.GROUP,
                    )
                    session.add(conversation)
                    await session.flush()
                    await ensure_conversation_configuration(
                        session, assistant, conversation
                    )
                    participant = ParticipantModel(
                        conversation_id=conversation.id,
                        platform_user_id="group-reset-user",
                        display_name="Admin",
                    )
                    session.add(participant)
                    await session.flush()
                    message = MessageModel(
                        conversation_id=conversation.id,
                        participant_id=participant.id,
                        platform_message_id="gr-1",
                        direction=MessageDirection.INCOMING,
                        message_type=MessageType.TEXT,
                        text="reset source",
                    )
                    session.add(message)
                    await session.flush()
                    incoming = IncomingPlatformUpdateModel(
                        platform_connection_id=connection.id,
                        platform=Platform.TELEGRAM,
                        platform_update_id="gr-1",
                        update_type="message",
                        ingress_source=IngressSource.POLLING,
                        raw_payload={},
                        received_at=datetime.now(UTC),
                    )
                    session.add(incoming)
                    await session.flush()
                    record = ConversationProcessingRecordModel(
                        incoming_update_id=incoming.id,
                        outcome=ProcessingOutcome.MESSAGE_CREATED,
                        conversation_id=conversation.id,
                        message_id=message.id,
                        eligible=False,
                        eligibility_reason=EligibilityReason.COMMAND_HANDOFF,
                    )
                    session.add(record)
                    await session.flush()
                    command = TelegramCommandJobModel(
                        conversation_processing_record_id=record.id,
                        conversation_id=conversation.id,
                        message_id=message.id,
                        participant_id=participant.id,
                        command_name="reset_group",
                        arguments="",
                    )
                    session.add(command)
                    await session.flush()
                    memory = MemoryItemModel(
                        assistant_id=assistant.id,
                        platform_connection_id=connection.id,
                        conversation_id=conversation.id,
                        creator_participant_id=participant.id,
                        source_message_id=message.id,
                        source_command_job_id=command.id,
                        public_id="reset-public-id",
                        kind=MemoryKind.EXPLICIT_FACT,
                        scope=MemoryScope.GROUP_CONVERSATION,
                        visibility=MemoryVisibility.SAME_CONVERSATION,
                        status=MemoryStatus.ACTIVE,
                        content="reset fact",
                        confidence=1.0,
                    )
                    session.add(memory)
                    await session.flush()
                    summary = ConversationSummaryModel(
                        conversation_id=conversation.id,
                        schema_version="conversation-summary-v1",
                        prompt_version="conversation-summary-prompt-v1",
                        source_first_message_id=message.id,
                        source_last_message_id=message.id,
                        source_started_at=datetime.now(UTC),
                        source_ended_at=datetime.now(UTC),
                        source_count=1,
                        source_window_hash="reset-window-hash",
                        summary_text="derived summary",
                        status=ConversationSummaryStatus.COMPLETED,
                        expires_at=datetime.now(UTC) + timedelta(days=1),
                    )
                    session.add(summary)
                    await session.flush()
                    conversation_id = conversation.id
                    assistant_id = assistant.id
                    connection_id = connection.id
                    actor_id = participant.id
                    command_job_id = command.id
                    memory_id = memory.id
                    summary_id = summary.id

            repository = SqlAlchemyMemoryRepository(
                database.session_factory, "test-version"
            )
            assert (
                await repository.reset_group(
                    assistant_id=assistant_id,
                    platform_connection_id=connection_id,
                    conversation_id=conversation_id,
                    actor_id=actor_id,
                    command_job_id=command_job_id,
                )
                == 1
            )
            async with database.session_factory() as session:
                memory = await session.get(MemoryItemModel, memory_id)
                assert memory is not None
                assert memory.status == MemoryStatus.DELETED
                assert memory.content is None
                summary = await session.get(ConversationSummaryModel, summary_id)
                assert summary is not None
                assert summary.status == ConversationSummaryStatus.INVALIDATED
                assert summary.summary_text is None
                assert (
                    summary.invalidation_reason == SummaryInvalidationReason.GROUP_RESET
                )
                assert summary.invalidated_at is not None
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.governance_integration
def test_forget_me_and_group_reset_write_durable_erasure_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        settings = Settings(
            _env_file=None,
            environment="test",
            data_governance_enabled=True,
            command_worker_enabled=True,
        )
        database = Database(settings)
        telemetry = InMemoryMetricsRecorder()
        await database.start()
        try:
            async with database.session_factory() as session:
                async with session.begin():
                    await session.execute(text("TRUNCATE assistants CASCADE"))
                    assistant = AssistantModel(name="January")
                    session.add(assistant)
                    await session.flush()
                    connection = PlatformConnectionModel(
                        assistant_id=assistant.id,
                        platform=Platform.TELEGRAM,
                        external_bot_id="erasure-bot",
                        status=PlatformConnectionStatus.ACTIVE,
                    )
                    session.add(connection)
                    await session.flush()
                    group = ConversationModel(
                        platform_connection_id=connection.id,
                        platform_conversation_id="erasure-group",
                        conversation_type=ConversationType.GROUP,
                    )
                    session.add(group)
                    await session.flush()
                    await ensure_conversation_configuration(session, assistant, group)
                    admin = ParticipantModel(
                        conversation_id=group.id,
                        platform_user_id="erasure-admin",
                        display_name="Admin",
                    )
                    member = ParticipantModel(
                        conversation_id=group.id,
                        platform_user_id="erasure-member",
                        display_name="Member",
                    )
                    session.add_all([admin, member])
                    await session.flush()
                    source = MessageModel(
                        conversation_id=group.id,
                        participant_id=member.id,
                        platform_message_id="erasure-source-message",
                        direction=MessageDirection.INCOMING,
                        message_type=MessageType.TEXT,
                        text="member fact",
                        mentions_assistant=True,
                        replies_to_assistant=False,
                        eligible=True,
                    )
                    session.add(source)
                    await session.flush()
                    source_incoming = IncomingPlatformUpdateModel(
                        platform_connection_id=connection.id,
                        platform=Platform.TELEGRAM,
                        platform_update_id="erasure-source-update",
                        update_type="message",
                        ingress_source=IngressSource.POLLING,
                        raw_payload={},
                        received_at=datetime.now(UTC),
                    )
                    session.add(source_incoming)
                    await session.flush()
                    source_record = ConversationProcessingRecordModel(
                        incoming_update_id=source_incoming.id,
                        outcome=ProcessingOutcome.MESSAGE_CREATED,
                        conversation_id=group.id,
                        message_id=source.id,
                        eligible=False,
                        eligibility_reason=EligibilityReason.COMMAND_HANDOFF,
                    )
                    session.add(source_record)
                    await session.flush()
                    source_job = TelegramCommandJobModel(
                        conversation_processing_record_id=source_record.id,
                        conversation_id=group.id,
                        message_id=source.id,
                        participant_id=member.id,
                        command_name="forget_me",
                        arguments="confirm",
                        status=CommandJobStatus.COMPLETED,
                        result_code="forget_me_done",
                        completed_at=datetime.now(UTC),
                    )
                    session.add(source_job)
                    await session.flush()
                    member_memory = MemoryItemModel(
                        assistant_id=assistant.id,
                        platform_connection_id=connection.id,
                        conversation_id=group.id,
                        creator_participant_id=member.id,
                        source_message_id=source.id,
                        source_command_job_id=source_job.id,
                        public_id="member-memory",
                        kind=MemoryKind.EXPLICIT_FACT,
                        scope=MemoryScope.GROUP_CONVERSATION,
                        visibility=MemoryVisibility.SAME_CONVERSATION,
                        status=MemoryStatus.ACTIVE,
                        content="member secret fact",
                        confidence=1.0,
                    )
                    session.add(member_memory)
                    await session.flush()
                    member_summary = ConversationSummaryModel(
                        conversation_id=group.id,
                        schema_version="conversation-summary-v1",
                        prompt_version="conversation-summary-prompt-v1",
                        source_first_message_id=source.id,
                        source_last_message_id=source.id,
                        source_started_at=datetime.now(UTC),
                        source_ended_at=datetime.now(UTC),
                        source_count=1,
                        source_window_hash="erasure-window-hash",
                        summary_text="member derived summary",
                        status=ConversationSummaryStatus.COMPLETED,
                        expires_at=datetime.now(UTC) + timedelta(days=1),
                    )
                    session.add(member_summary)
                    await session.flush()
                    connection_id = connection.id
                    assistant_id = assistant.id
                    group_id = group.id
                    admin_id = admin.id
                    member_id = member.id
                    member_memory_id = member_memory.id
                    member_summary_id = member_summary.id
                    fixture_source_job_id = source_job.id

            async def enqueue(
                name: str, arguments: str, participant_id: UUID, sequence: int
            ) -> UUID:
                async with database.session_factory() as session:
                    async with session.begin():
                        message = MessageModel(
                            conversation_id=group_id,
                            participant_id=participant_id,
                            platform_message_id=f"e-{sequence}",
                            direction=MessageDirection.INCOMING,
                            message_type=MessageType.TEXT,
                            text=f"/{name} {arguments}".strip(),
                        )
                        incoming = IncomingPlatformUpdateModel(
                            platform_connection_id=connection_id,
                            platform=Platform.TELEGRAM,
                            platform_update_id=f"e-{sequence}",
                            update_type="message",
                            ingress_source=IngressSource.POLLING,
                            raw_payload={},
                            received_at=datetime.now(UTC),
                        )
                        session.add_all([message, incoming])
                        await session.flush()
                        record = ConversationProcessingRecordModel(
                            incoming_update_id=incoming.id,
                            outcome=ProcessingOutcome.MESSAGE_CREATED,
                            conversation_id=group_id,
                            message_id=message.id,
                            eligible=False,
                            eligibility_reason=EligibilityReason.COMMAND_HANDOFF,
                        )
                        session.add(record)
                        await session.flush()
                        job = TelegramCommandJobModel(
                            conversation_processing_record_id=record.id,
                            conversation_id=group_id,
                            message_id=message.id,
                            participant_id=participant_id,
                            command_name=name,
                            arguments=arguments,
                        )
                        session.add(job)
                        await session.flush()
                        return job.id

            class Administrator:
                async def get_chat_member(
                    self, conversation_id: str, user_id: str
                ) -> ChatMember:
                    assert user_id == "erasure-admin"
                    return ChatMember(
                        conversation_id=conversation_id,
                        user_id=user_id,
                        status="administrator",
                        is_administrator=True,
                        is_owner=False,
                        permissions=frozenset(),
                    )

            driven_job_ids: list[UUID] = []

            async def drive(
                name: str,
                arguments: str,
                participant_id: UUID,
                adapter: object,
                sequence: int,
            ) -> str:
                job_id = await enqueue(name, arguments, participant_id, sequence)
                driven_job_ids.append(job_id)
                assert (
                    await consume_command_once(
                        settings, database, adapter, "test", telemetry
                    )
                    == 1
                )
                async with database.session_factory() as session:
                    job = await session.get(TelegramCommandJobModel, job_id)
                    assert job is not None
                    return job.result_code or ""

            repository = SqlAlchemyGovernanceRepository(database.session_factory)
            subject_token_hash = hashlib.sha256(b"subject-before-erasure").hexdigest()
            subject_export = await repository.create_export_request(
                scope=GovernanceScope.SUBJECT,
                conversation_id=group_id,
                participant_id=member_id,
                tenant_id=None,
                token_hash=subject_token_hash,
                categories=SUBJECT_EXPORT_CATEGORIES,
                ttl_days=2,
            )
            assert await repository.claim_export_request(
                request_id=subject_export.id,
                lease_owner="erasure-test",
                lease_seconds=60,
                max_attempts=5,
            )
            assert await repository.complete_export(
                request_id=subject_export.id,
                schema_version="governance-export-v1",
                manifest={"scope": "subject"},
                package={"subject": "sensitive"},
                expires_at=datetime.now(UTC) + timedelta(days=2),
            )
            assert await drive(
                "forget_me", "confirm", member_id, Administrator(), 2
            ) in {
                "forget_me_done",
                "forget_me_unchanged",
            }

            async with database.session_factory() as session:
                erasures = list(
                    await session.scalars(
                        select(GovernanceErasureRequestModel).order_by(
                            GovernanceErasureRequestModel.created_at
                        )
                    )
                )
                assert len(erasures) == 1
                assert erasures[0].scope == GovernanceScope.SUBJECT
                assert erasures[0].participant_id == member_id
                assert erasures[0].status == ErasureRequestStatus.COMPLETE
                assert erasures[0].completed_at is not None
                memory = await session.get(MemoryItemModel, member_memory_id)
                assert memory is not None and memory.content is None
                summary = await session.get(ConversationSummaryModel, member_summary_id)
                assert summary is not None
                assert summary.status == ConversationSummaryStatus.INVALIDATED
                assert (
                    summary.invalidation_reason
                    == SummaryInvalidationReason.PRIVACY_ERASURE
                )
                erasure_event_types = list(
                    await session.scalars(
                        select(GovernanceAuditEventModel.event_type).where(
                            GovernanceAuditEventModel.request_id == str(erasures[0].id)
                        )
                    )
                )
                assert GovernanceAuditEventType.ERASURE_REQUEST in erasure_event_types
                assert GovernanceAuditEventType.ERASURE_COMPLETE in erasure_event_types
                revoked = await session.get(
                    GovernanceExportRequestModel, subject_export.id
                )
                assert revoked is not None
                assert revoked.status == "expired"
                assert revoked.single_use_token_hash is None
                revoked_package = await session.scalar(
                    select(GovernanceExportPackageModel).where(
                        GovernanceExportPackageModel.export_request_id
                        == subject_export.id
                    )
                )
                assert revoked_package is not None
                assert revoked_package.package == {}
                assert revoked_package.cleared_at is not None
            assert await repository.retrieve_export_by_token(subject_token_hash) is None

            async with database.session_factory() as session:
                async with session.begin():
                    group_source_incoming = IncomingPlatformUpdateModel(
                        platform_connection_id=connection_id,
                        platform=Platform.TELEGRAM,
                        platform_update_id="erasure-group-source-update",
                        update_type="message",
                        ingress_source=IngressSource.POLLING,
                        raw_payload={},
                        received_at=datetime.now(UTC),
                    )
                    session.add(group_source_incoming)
                    await session.flush()
                    group_source_record = ConversationProcessingRecordModel(
                        incoming_update_id=group_source_incoming.id,
                        outcome=ProcessingOutcome.MESSAGE_CREATED,
                        conversation_id=group_id,
                        message_id=source.id,
                        eligible=False,
                        eligibility_reason=EligibilityReason.COMMAND_HANDOFF,
                    )
                    session.add(group_source_record)
                    await session.flush()
                    group_source_job = TelegramCommandJobModel(
                        conversation_processing_record_id=group_source_record.id,
                        conversation_id=group_id,
                        message_id=source.id,
                        participant_id=admin_id,
                        command_name="memory",
                        arguments="reset_group",
                        status=CommandJobStatus.COMPLETED,
                        result_code="memory_reset",
                        completed_at=datetime.now(UTC),
                    )
                    session.add(group_source_job)
                    await session.flush()
                    group_memory = MemoryItemModel(
                        assistant_id=assistant_id,
                        platform_connection_id=connection_id,
                        conversation_id=group_id,
                        creator_participant_id=admin_id,
                        source_message_id=source.id,
                        source_command_job_id=group_source_job.id,
                        public_id="group-memory",
                        kind=MemoryKind.EXPLICIT_FACT,
                        scope=MemoryScope.GROUP_CONVERSATION,
                        visibility=MemoryVisibility.SAME_CONVERSATION,
                        status=MemoryStatus.ACTIVE,
                        content="group secret fact",
                        confidence=1.0,
                    )
                    session.add(group_memory)
                    await session.flush()
                    group_summary = ConversationSummaryModel(
                        conversation_id=group_id,
                        schema_version="conversation-summary-v1",
                        prompt_version="conversation-summary-prompt-v1",
                        source_first_message_id=source.id,
                        source_last_message_id=source.id,
                        source_started_at=datetime.now(UTC),
                        source_ended_at=datetime.now(UTC),
                        source_count=1,
                        source_window_hash="group-reset-window-hash",
                        summary_text="group derived summary",
                        status=ConversationSummaryStatus.COMPLETED,
                        expires_at=datetime.now(UTC) + timedelta(days=1),
                    )
                    session.add(group_summary)
                    await session.flush()
                    group_memory_id = group_memory.id
                    group_summary_id = group_summary.id

            group_token_hash = hashlib.sha256(b"group-before-reset").hexdigest()
            group_export = await repository.create_export_request(
                scope=GovernanceScope.GROUP,
                conversation_id=group_id,
                participant_id=admin_id,
                tenant_id=None,
                token_hash=group_token_hash,
                categories=GROUP_EXPORT_CATEGORIES,
                ttl_days=2,
            )
            assert await repository.claim_export_request(
                request_id=group_export.id,
                lease_owner="group-reset-test",
                lease_seconds=60,
                max_attempts=5,
            )
            assert await repository.complete_export(
                request_id=group_export.id,
                schema_version="governance-export-v1",
                manifest={"scope": "group"},
                package={"group": "sensitive"},
                expires_at=datetime.now(UTC) + timedelta(days=2),
            )
            assert await drive(
                "memory", "reset_group confirm", admin_id, Administrator(), 3
            ) == ("memory_reset")

            async with database.session_factory() as session:
                erasures = list(
                    await session.scalars(
                        select(GovernanceErasureRequestModel).order_by(
                            GovernanceErasureRequestModel.created_at
                        )
                    )
                )
                assert len(erasures) == 2
                group_erasure = erasures[-1]
                assert group_erasure.scope == GovernanceScope.GROUP
                assert group_erasure.participant_id == admin_id
                assert group_erasure.status == ErasureRequestStatus.COMPLETE
                memory = await session.get(MemoryItemModel, group_memory_id)
                assert memory is not None and memory.content is None
                summary = await session.get(ConversationSummaryModel, group_summary_id)
                assert summary is not None
                assert summary.status == ConversationSummaryStatus.INVALIDATED
                assert (
                    summary.invalidation_reason == SummaryInvalidationReason.GROUP_RESET
                )
                revoked_group = await session.get(
                    GovernanceExportRequestModel, group_export.id
                )
                assert revoked_group is not None
                assert revoked_group.status == "expired"
                assert revoked_group.single_use_token_hash is None
                revoked_group_package = await session.scalar(
                    select(GovernanceExportPackageModel).where(
                        GovernanceExportPackageModel.export_request_id
                        == group_export.id
                    )
                )
                assert revoked_group_package is not None
                assert revoked_group_package.package == {}
                assert revoked_group_package.cleared_at is not None

            async def fail_erasure(*_args: object, **_kwargs: object) -> object:
                raise RuntimeError("synthetic repository failure")

            monkeypatch.setattr(
                SqlAlchemyPrivacyRepository, "erase_subject", fail_erasure
            )
            assert (
                await drive("forget_me", "confirm", admin_id, Administrator(), 4)
                == "safe_failure"
            )
            monkeypatch.undo()
            async with database.session_factory() as session:
                partial = await session.scalar(
                    select(GovernanceErasureRequestModel).where(
                        GovernanceErasureRequestModel.source_command_job_id
                        == driven_job_ids[-1]
                    )
                )
                assert partial is not None
                assert partial.status == ErasureRequestStatus.PARTIAL
                assert partial.partial_reason == "repository_error"
                partial_event = await session.scalar(
                    select(GovernanceAuditEventModel).where(
                        GovernanceAuditEventModel.request_id == str(partial.id),
                        GovernanceAuditEventModel.event_type
                        == GovernanceAuditEventType.ERASURE_PARTIAL,
                    )
                )
                assert partial_event is not None
                assert partial_event.detail == "repository_error"
            erasure_metrics = telemetry.exposition()
            assert 'outcome="complete"' in erasure_metrics
            assert 'outcome="partial"' in erasure_metrics

            replayed = await repository.create_erasure_request(
                scope=GovernanceScope.SUBJECT,
                conversation_id=group_id,
                participant_id=member_id,
                requested_via="telegram_command",
                source_command_job_id=driven_job_ids[0],
            )
            assert replayed.id == erasures[0].id
            assert not replayed.created
            raced = await asyncio.gather(
                *(
                    repository.create_erasure_request(
                        scope=GovernanceScope.SUBJECT,
                        conversation_id=group_id,
                        participant_id=member_id,
                        requested_via="telegram_command",
                        source_command_job_id=fixture_source_job_id,
                    )
                    for _ in range(2)
                )
            )
            assert raced[0].id == raced[1].id
            assert sorted(item.created for item in raced) == [False, True]
            lease_start = datetime(2026, 1, 1, tzinfo=UTC)
            assert await repository.mark_erasure_in_progress(
                raced[0].id,
                lease_owner="crashed-owner",
                lease_seconds=5,
                now=lease_start,
            )
            assert not await repository.mark_erasure_in_progress(
                raced[0].id,
                lease_owner="would-be-thief",
                lease_seconds=60,
                now=lease_start + timedelta(seconds=2),
            )
            assert await repository.fail_stale_erasure_requests(limit=1) == ["subject"]
            recovered = await repository.get_erasure_request(raced[0].id)
            assert recovered is not None
            assert recovered.status == ErasureRequestStatus.FAILED
            assert recovered.partial_reason == "worker_restart"
            assert await repository.mark_erasure_in_progress(
                raced[0].id,
                lease_owner="recovery-owner",
                lease_seconds=60,
            )
            assert not await repository.complete_erasure_request(
                raced[0].id,
                lease_owner="crashed-owner",
            )
            assert await repository.complete_erasure_request(
                raced[0].id,
                lease_owner="recovery-owner",
            )
            async with database.session_factory() as session:
                assert (
                    await session.scalar(
                        select(func.count(GovernanceErasureRequestModel.id)).where(
                            GovernanceErasureRequestModel.source_command_job_id
                            == fixture_source_job_id
                        )
                    )
                    == 1
                )
                recovery_failure = await session.scalar(
                    select(GovernanceAuditEventModel).where(
                        GovernanceAuditEventModel.request_id == str(raced[0].id),
                        GovernanceAuditEventModel.event_type
                        == GovernanceAuditEventType.ERASURE_FAILED,
                    )
                )
                assert recovery_failure is not None
                assert recovery_failure.detail == "worker_restart"
            assert (
                await consume_command_once(
                    settings, database, Administrator(), "test", telemetry
                )
                == 0
            )
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.governance_integration
def test_audit_retention_purges_both_audit_tables_idempotently() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            now = datetime(2026, 8, 1, tzinfo=UTC)
            expired = now - timedelta(days=45)
            async with database.session_factory() as session:
                async with session.begin():
                    await session.execute(text("TRUNCATE assistants CASCADE"))
                    await session.execute(text("TRUNCATE control_audit_events CASCADE"))
                    await session.execute(
                        text("TRUNCATE governance_audit_events CASCADE")
                    )
                    tenant = ControlTenantModel(
                        slug=f"retention-tenant-{uuid4().hex[:8]}",
                        name="Retention Tenant",
                    )
                    session.add(tenant)
                    await session.flush()
                    session.add(
                        ControlAuditEventModel(
                            tenant_id=tenant.id,
                            action="governance.export",
                            outcome="complete",
                            resource_type="deployment_export",
                            request_id="retention-request",
                            metadata_={"schema_version": "spec-021-v1"},
                            created_at=expired,
                        )
                    )
                    session.add(
                        ControlAuditEventModel(
                            tenant_id=tenant.id,
                            action="governance.export",
                            outcome="complete",
                            resource_type="deployment_export",
                            request_id="retention-fresh",
                            metadata_={"schema_version": "spec-021-v1"},
                            created_at=now,
                        )
                    )
                    session.add(
                        GovernanceAuditEventModel(
                            event_type=GovernanceAuditEventType.EXPORT_REQUEST,
                            scope=GovernanceScope.DEPLOYMENT,
                            request_id="expired-governance",
                            outcome="requested",
                            created_at=expired,
                        )
                    )
                    session.add(
                        GovernanceAuditEventModel(
                            event_type=GovernanceAuditEventType.EXPORT_REQUEST,
                            scope=GovernanceScope.DEPLOYMENT,
                            request_id="fresh-governance",
                            outcome="requested",
                            created_at=now,
                        )
                    )
                    for index in range(2):
                        session.add(
                            ControlAuditEventModel(
                                tenant_id=None if index == 0 else tenant.id,
                                action="governance.export",
                                outcome="complete",
                                resource_type="deployment_export",
                                request_id=f"retention-extra-{index}",
                                metadata_={"schema_version": "spec-021-v1"},
                                created_at=expired,
                            )
                        )
                        session.add(
                            GovernanceAuditEventModel(
                                event_type=GovernanceAuditEventType.EXPORT_REQUEST,
                                scope=GovernanceScope.DEPLOYMENT,
                                request_id=f"expired-governance-extra-{index}",
                                outcome="requested",
                                created_at=expired,
                            )
                        )
                    assistant = AssistantModel(name="January")
                    session.add(assistant)
                    await session.flush()
                    connection = PlatformConnectionModel(
                        assistant_id=assistant.id,
                        platform=Platform.TELEGRAM,
                        external_bot_id="retention-export-bot",
                        status=PlatformConnectionStatus.ACTIVE,
                    )
                    session.add(connection)
                    await session.flush()
                    conversation = ConversationModel(
                        platform_connection_id=connection.id,
                        platform_conversation_id="retention-export-chat",
                        conversation_type=ConversationType.GROUP,
                    )
                    session.add(conversation)
                    await session.flush()
                    await ensure_conversation_configuration(
                        session, assistant, conversation
                    )
                    participant = ParticipantModel(
                        conversation_id=conversation.id,
                        platform_user_id="retention-export-user",
                        display_name="Subject",
                    )
                    session.add(participant)
                    await session.flush()
                    conversation_id = conversation.id
                    participant_id = participant.id

            governance = SqlAlchemyGovernanceRepository(database.session_factory)
            export = await governance.create_export_request(
                scope=GovernanceScope.SUBJECT,
                conversation_id=conversation_id,
                participant_id=participant_id,
                tenant_id=None,
                token_hash="a" * 64,
                categories=SUBJECT_EXPORT_CATEGORIES,
                ttl_days=2,
                now=now,
            )
            erasure = await governance.create_erasure_request(
                scope=GovernanceScope.SUBJECT,
                conversation_id=conversation_id,
                participant_id=participant_id,
                requested_via="telegram_command",
            )

            retention = SqlAlchemyRetentionRepository(database.session_factory)
            counts = await retention.redact_once(
                now=now,
                retention_days=30,
                governance_audit_retention_days=30,
                batch_size=2,
            )
            assert counts.audit_events == 2
            assert counts.control_audit_events == 2

            second_counts = await retention.redact_once(
                now=now,
                retention_days=30,
                governance_audit_retention_days=30,
                batch_size=2,
            )
            assert second_counts.audit_events == 1
            assert second_counts.control_audit_events == 1

            async with database.session_factory() as session:
                remaining_governance = list(
                    await session.scalars(select(GovernanceAuditEventModel.request_id))
                )
                assert "expired-governance" not in remaining_governance
                assert "fresh-governance" in remaining_governance
                assert str(export.id) in remaining_governance
                remaining_control = list(
                    await session.scalars(select(ControlAuditEventModel.request_id))
                )
                assert remaining_control == ["retention-fresh"]
                assert await session.get(GovernanceExportRequestModel, export.id)
                assert await session.get(GovernanceErasureRequestModel, erasure.id)

            assert (
                await retention.redact_once(
                    now=now,
                    retention_days=30,
                    governance_audit_retention_days=30,
                    batch_size=2,
                )
                == type(counts)()
            )
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.governance_integration
def test_export_package_expiry_clears_packages_idempotently() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            now = datetime(2026, 8, 1, tzinfo=UTC)
            async with database.session_factory() as session:
                async with session.begin():
                    await session.execute(text("TRUNCATE assistants CASCADE"))
                    assistant = AssistantModel(name="January")
                    session.add(assistant)
                    await session.flush()
                    connection = PlatformConnectionModel(
                        assistant_id=assistant.id,
                        platform=Platform.TELEGRAM,
                        external_bot_id="expiry-bot",
                        status=PlatformConnectionStatus.ACTIVE,
                    )
                    session.add(connection)
                    await session.flush()
                    conversation = ConversationModel(
                        platform_connection_id=connection.id,
                        platform_conversation_id="expiry-chat",
                        conversation_type=ConversationType.GROUP,
                    )
                    session.add(conversation)
                    await session.flush()
                    await ensure_conversation_configuration(
                        session, assistant, conversation
                    )
                    participant = ParticipantModel(
                        conversation_id=conversation.id,
                        platform_user_id="expiry-user",
                        display_name="Subject",
                    )
                    session.add(participant)
                    await session.flush()
                    conversation_id = conversation.id
                    participant_id = participant.id

            repository = SqlAlchemyGovernanceRepository(database.session_factory)
            expired_request = await repository.create_export_request(
                scope=GovernanceScope.SUBJECT,
                conversation_id=conversation_id,
                participant_id=participant_id,
                tenant_id=None,
                token_hash="b" * 64,
                categories=SUBJECT_EXPORT_CATEGORIES,
                ttl_days=2,
                now=now,
            )
            fresh_request = await repository.create_export_request(
                scope=GovernanceScope.GROUP,
                conversation_id=conversation_id,
                participant_id=None,
                tenant_id=None,
                token_hash="c" * 64,
                categories=SUBJECT_EXPORT_CATEGORIES,
                ttl_days=30,
                now=now,
            )
            extra_expired = [
                await repository.create_export_request(
                    scope=GovernanceScope.SUBJECT,
                    conversation_id=conversation_id,
                    participant_id=participant_id,
                    tenant_id=None,
                    token_hash=character * 64,
                    categories=SUBJECT_EXPORT_CATEGORIES,
                    ttl_days=2,
                    now=now,
                )
                for character in ("d", "e")
            ]
            assert await repository.claim_export_request(
                request_id=expired_request.id,
                lease_owner="first-owner",
                lease_seconds=60,
                max_attempts=5,
                now=now,
            )
            assert not await repository.claim_export_request(
                request_id=expired_request.id,
                lease_owner="second-owner",
                lease_seconds=60,
                max_attempts=5,
                now=now + timedelta(seconds=30),
            )
            assert (
                expired_request.id
                not in await repository.find_claimable_export_requests(
                    limit=10,
                    max_attempts=5,
                    now=now + timedelta(seconds=30),
                )
            )
            assert (
                expired_request.id
                in await repository.find_claimable_export_requests(
                    limit=10,
                    max_attempts=5,
                    now=now + timedelta(seconds=61),
                )
            )
            assert await repository.claim_export_request(
                request_id=expired_request.id,
                lease_owner="second-owner",
                lease_seconds=60,
                max_attempts=5,
                now=now + timedelta(seconds=61),
            )
            assert not await repository.complete_export(
                request_id=expired_request.id,
                schema_version="governance-export-v1",
                manifest={"scope": GovernanceScope.SUBJECT},
                package={"secret": "stale owner package"},
                expires_at=now + timedelta(days=2),
                lease_owner="first-owner",
                now=now + timedelta(seconds=61),
            )
            assert not await repository.record_export_failed(
                request_id=expired_request.id,
                reason="stale_owner",
                max_attempts=5,
                lease_owner="first-owner",
            )
            assert await repository.complete_export(
                request_id=expired_request.id,
                schema_version="governance-export-v1",
                manifest={"scope": GovernanceScope.SUBJECT},
                package={"secret": "package body"},
                expires_at=now + timedelta(days=2),
                lease_owner="second-owner",
                now=now + timedelta(seconds=61),
            )
            assert await repository.claim_export_request(
                request_id=fresh_request.id,
                lease_owner="test",
                lease_seconds=60,
                max_attempts=5,
                now=now,
            )
            assert await repository.complete_export(
                request_id=fresh_request.id,
                schema_version="governance-export-v1",
                manifest={"scope": GovernanceScope.GROUP},
                package={"secret": "package body"},
                expires_at=now + timedelta(days=30),
                now=now,
            )
            for extra in extra_expired:
                assert await repository.claim_export_request(
                    request_id=extra.id,
                    lease_owner="test",
                    lease_seconds=60,
                    max_attempts=5,
                    now=now,
                )
                assert await repository.complete_export(
                    request_id=extra.id,
                    schema_version="governance-export-v1",
                    manifest={"scope": GovernanceScope.SUBJECT},
                    package={"secret": "package body"},
                    expires_at=now + timedelta(days=2),
                    now=now,
                )

            assert (
                await repository.expire_stale_exports(
                    limit=2, now=now + timedelta(days=3)
                )
                == 2
            )
            assert (
                await repository.expire_stale_exports(
                    limit=2, now=now + timedelta(days=3)
                )
                == 1
            )
            async with database.session_factory() as session:
                expired_row = await session.get(
                    GovernanceExportRequestModel, expired_request.id
                )
                assert expired_row is not None
                assert expired_row.status == "expired"
                assert expired_row.single_use_token_hash is None
                expired_package = await session.scalar(
                    select(GovernanceExportPackageModel).where(
                        GovernanceExportPackageModel.export_request_id
                        == expired_request.id
                    )
                )
                assert expired_package is not None
                assert expired_package.package == {}
                assert expired_package.cleared_at is not None
                fresh_row = await session.get(
                    GovernanceExportRequestModel, fresh_request.id
                )
                assert fresh_row is not None
                assert fresh_row.status == "complete"
                fresh_package = await session.scalar(
                    select(GovernanceExportPackageModel).where(
                        GovernanceExportPackageModel.export_request_id
                        == fresh_request.id
                    )
                )
                assert fresh_package is not None
                assert fresh_package.package == {"secret": "package body"}
                assert fresh_package.cleared_at is None
                expired_audit_count = await session.scalar(
                    select(func.count(GovernanceAuditEventModel.id)).where(
                        GovernanceAuditEventModel.event_type
                        == GovernanceAuditEventType.EXPORT_EXPIRED,
                        GovernanceAuditEventModel.detail == "ttl_expired",
                    )
                )
                assert expired_audit_count == 3

            assert (
                await repository.expire_stale_exports(
                    limit=2, now=now + timedelta(days=3)
                )
                == 0
            )
        finally:
            await database.stop()

    asyncio.run(scenario())
