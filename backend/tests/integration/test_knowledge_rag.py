"""Live PostgreSQL authority proof for SPEC-033 knowledge RAG."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import jwt
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.application.knowledge import KnowledgeCandidate, KnowledgePoint
from app.application.memory import normalize_explicit_memory
from app.application.semantic_memory import EmbeddingVector, embedding_version
from app.core.config import Settings
from app.domain.conversation import EligibilityReason, ProcessingOutcome
from app.domain.knowledge import (
    KnowledgeBaseStatus,
    KnowledgeContentType,
    KnowledgeDocumentStatus,
    KnowledgeIndexJobStatus,
    KnowledgeIndexState,
)
from app.domain.persistence import (
    AssistantStatus,
    ConversationType,
    IngressSource,
    MemoryScope,
    MessageDirection,
    MessageProcessingStatus,
    MessageType,
    Platform,
    PlatformConnectionStatus,
)
from app.infrastructure.database.database import Database
from app.infrastructure.database.knowledge import (
    KnowledgeConflict,
    SqlAlchemyKnowledgeRepository,
)
from app.infrastructure.database.memory import SqlAlchemyMemoryRepository
from app.infrastructure.database.models import (
    AssistantModel,
    ControlDeploymentAuthorityModel,
    ControlOperatorIdentityModel,
    ControlOperatorMembershipModel,
    ControlTenantModel,
    ConversationModel,
    ConversationProcessingRecordModel,
    ExplicitMemorySemanticIndexJobModel,
    IncomingPlatformUpdateModel,
    KnowledgeBaseModel,
    KnowledgeChunkModel,
    KnowledgeDocumentModel,
    KnowledgeDocumentRevisionModel,
    KnowledgeIndexJobModel,
    MemoryControlOperationModel,
    MemoryEventModel,
    MemoryItemModel,
    MessageModel,
    ParticipantModel,
    PlatformConnectionModel,
    ResponsePlanningJobModel,
    TelegramCommandJobModel,
)
from app.infrastructure.knowledge import KnowledgeRetriever, QdrantKnowledgeIndex
from app.main import create_app
from app.runtime.knowledge_index_worker import consume_once
from app.runtime.knowledge_operations import operate

pytestmark = [pytest.mark.integration, pytest.mark.knowledge_rag_integration]


async def _scenario() -> None:
    settings = Settings(_env_file=None, environment="test")
    database = Database(settings)
    await database.start()
    repository = SqlAlchemyKnowledgeRepository(database.session_factory)
    version = embedding_version("ollama", "fixture", 2)
    try:
        async with database.session_factory() as session, session.begin():
            await session.execute(
                text(
                    "TRUNCATE control_operator_identities, control_tenants, "
                    "assistants CASCADE"
                )
            )
            tenant = ControlTenantModel(slug="spec033", name="SPEC 033")
            foreign_tenant = ControlTenantModel(slug="spec033-foreign", name="Foreign")
            actor = ControlOperatorIdentityModel(issuer="spec033", subject="owner")
            session.add_all([tenant, foreign_tenant, actor])
            await session.flush()
            assistant = AssistantModel(
                tenant_id=tenant.id,
                slug="knowledge",
                name="Knowledge",
                status=AssistantStatus.ACTIVE,
                knowledge_enabled=True,
            )
            foreign_assistant = AssistantModel(
                tenant_id=foreign_tenant.id,
                slug="knowledge",
                name="Foreign Knowledge",
                status=AssistantStatus.ACTIVE,
                knowledge_enabled=True,
            )
            sibling_assistant = AssistantModel(
                tenant_id=tenant.id,
                slug="knowledge-sibling",
                name="Sibling Knowledge",
                status=AssistantStatus.ACTIVE,
                knowledge_enabled=True,
            )
            session.add_all([assistant, foreign_assistant, sibling_assistant])
            await session.flush()
            base = await repository.create_base(
                session,
                tenant_id=tenant.id,
                assistant_id=assistant.id,
                slug="facts",
                name="Facts",
            )
            document = await repository.create_document(
                session,
                knowledge_base=base,
                slug="policy",
                title="Policy",
                source_label="operator",
                source_reference="inert-ref",
                content_type=KnowledgeContentType.MARKDOWN,
            )
            first = await repository.create_revision(
                session,
                document=document,
                expected_revision=document.revision,
                content="Canonical first revision",
                actor_id=actor.id,
                embedding_version=version,
                target_collection="knowledge",
            )
            sibling_base = await repository.create_base(
                session,
                tenant_id=tenant.id,
                assistant_id=sibling_assistant.id,
                slug="sibling-facts",
                name="Sibling Facts",
            )
            sibling_document = await repository.create_document(
                session,
                knowledge_base=sibling_base,
                slug="sibling-policy",
                title="Sibling Policy",
                source_label=None,
                source_reference=None,
                content_type=KnowledgeContentType.TEXT,
            )
            sibling_revision = await repository.create_revision(
                session,
                document=sibling_document,
                expected_revision=sibling_document.revision,
                content="Foreign Assistant content",
                actor_id=actor.id,
                embedding_version=version,
                target_collection="knowledge",
            )
            foreign_base = await repository.create_base(
                session,
                tenant_id=foreign_tenant.id,
                assistant_id=foreign_assistant.id,
                slug="foreign-facts",
                name="Foreign Facts",
            )
            foreign_document = await repository.create_document(
                session,
                knowledge_base=foreign_base,
                slug="foreign-policy",
                title="Foreign Policy",
                source_label=None,
                source_reference=None,
                content_type=KnowledgeContentType.TEXT,
            )
            foreign_revision = await repository.create_revision(
                session,
                document=foreign_document,
                expected_revision=foreign_document.revision,
                content="Foreign tenant content",
                actor_id=actor.id,
                embedding_version=version,
                target_collection="knowledge",
            )
            tenant_id = tenant.id
            assistant_id = assistant.id
            base_id = base.id
            document_id = document.id
            first_id = first.id
            sibling_base_id = sibling_base.id
            sibling_assistant_id = sibling_assistant.id
            sibling_revision_id = sibling_revision.id
            foreign_base_id = foreign_base.id
            foreign_revision_id = foreign_revision.id

        async with database.session_factory() as session, session.begin():
            unready_base = await session.get(
                KnowledgeBaseModel, base_id, with_for_update=True
            )
            assert unready_base is not None
            with pytest.raises(KnowledgeConflict, match="not activation-ready"):
                await repository.transition_base(
                    session,
                    unready_base,
                    expected_revision=unready_base.revision,
                    target=KnowledgeBaseStatus.ACTIVE,
                )

        jobs = await repository.claim("first", 20, 60)
        assert jobs
        assert await repository.point_for_upsert(jobs[0].id) is not None
        for job in jobs:
            assert await repository.complete(job.id, "first")

        async with database.session_factory() as session, session.begin():
            base = await session.get(KnowledgeBaseModel, base_id, with_for_update=True)
            assert base is not None
            await repository.transition_base(
                session,
                base,
                expected_revision=base.revision,
                target=KnowledgeBaseStatus.ACTIVE,
            )
            for owned_base_id in (sibling_base_id, foreign_base_id):
                owned_base = await session.get(
                    KnowledgeBaseModel, owned_base_id, with_for_update=True
                )
                assert owned_base is not None
                await repository.transition_base(
                    session,
                    owned_base,
                    expected_revision=owned_base.revision,
                    target=KnowledgeBaseStatus.ACTIVE,
                )
            first_chunk = await session.scalar(
                select(KnowledgeChunkModel).where(
                    KnowledgeChunkModel.revision_id == first_id
                )
            )
            assert first_chunk is not None
            first_chunk_id = first_chunk.id
            sibling_chunk_id = await session.scalar(
                select(KnowledgeChunkModel.id).where(
                    KnowledgeChunkModel.revision_id == sibling_revision_id
                )
            )
            foreign_chunk_id = await session.scalar(
                select(KnowledgeChunkModel.id).where(
                    KnowledgeChunkModel.revision_id == foreign_revision_id
                )
            )
            assert sibling_chunk_id is not None and foreign_chunk_id is not None

        enabled = await repository.retrieval_enabled(tenant_id, assistant_id)
        assert enabled == (base_id,)
        first_result = await repository.revalidate_candidates(
            (first_chunk_id, sibling_chunk_id, foreign_chunk_id, uuid4()),
            tenant_id=tenant_id,
            assistant_id=assistant_id,
            eligible_base_ids=enabled,
            scores={
                first_chunk_id: 0.7,
                sibling_chunk_id: 1.0,
                foreign_chunk_id: 0.9,
            },
            embedding_version=version,
            index_schema_version="knowledge-index-v1",
        )
        assert [item.content for item in first_result] == ["Canonical first revision"]
        assert first_result[0].title == "Policy"
        assert first_result[0].source_label == "operator"
        assert (
            await repository.revalidate_candidates(
                (first_chunk_id,),
                tenant_id=tenant_id,
                assistant_id=assistant_id,
                eligible_base_ids=enabled,
                scores={first_chunk_id: 1.0},
                embedding_version="wrong-version",
                index_schema_version="knowledge-index-v1",
            )
            == ()
        )
        async with database.session_factory() as session, session.begin():
            base = await session.get(KnowledgeBaseModel, base_id, with_for_update=True)
            assert base is not None
            await repository.transition_base(
                session,
                base,
                expected_revision=base.revision,
                target=KnowledgeBaseStatus.DISABLED,
            )
        assert (
            await repository.revalidate_candidates(
                (first_chunk_id,),
                tenant_id=tenant_id,
                assistant_id=assistant_id,
                eligible_base_ids=enabled,
                scores={first_chunk_id: 1.0},
                embedding_version=version,
                index_schema_version="knowledge-index-v1",
            )
            == ()
        )
        async with database.session_factory() as session, session.begin():
            base = await session.get(KnowledgeBaseModel, base_id, with_for_update=True)
            assert base is not None
            await repository.transition_base(
                session,
                base,
                expected_revision=base.revision,
                target=KnowledgeBaseStatus.ACTIVE,
            )

        async with database.session_factory() as session, session.begin():
            document = await session.get(
                KnowledgeDocumentModel, document_id, with_for_update=True
            )
            assert document is not None
            second = await repository.create_revision(
                session,
                document=document,
                expected_revision=document.revision,
                content="Canonical second revision",
                actor_id=actor.id,
                embedding_version=version,
                target_collection="knowledge",
            )
            second_id = second.id
        # A not-yet-ready revision never replaces the prior current revision.
        still_first = await repository.revalidate_candidates(
            (first_chunk_id,),
            tenant_id=tenant_id,
            assistant_id=assistant_id,
            eligible_base_ids=enabled,
            scores={first_chunk_id: 0.9},
            embedding_version=version,
            index_schema_version="knowledge-index-v1",
        )
        assert len(still_first) == 1

        jobs = await repository.claim("second", 20, 60)
        for job in jobs:
            if job.revision_id == second_id:
                assert await repository.complete(job.id, "second")
        async with database.session_factory() as session:
            second_chunk = await session.scalar(
                select(KnowledgeChunkModel).where(
                    KnowledgeChunkModel.revision_id == second_id
                )
            )
            document = await session.get(KnowledgeDocumentModel, document_id)
            assert second_chunk is not None and document is not None
            second_chunk_id = second_chunk.id
            assert document.current_revision_id == second_id
        selected = await repository.revalidate_candidates(
            (first_chunk_id, second_chunk_id, uuid4()),
            tenant_id=tenant_id,
            assistant_id=assistant_id,
            eligible_base_ids=enabled,
            scores={first_chunk_id: 1.0, second_chunk_id: 0.8},
            embedding_version=version,
            index_schema_version="knowledge-index-v1",
        )
        assert [item.chunk_id for item in selected] == [second_chunk_id]

        # A failed later revision never replaces the ready current revision.
        async with database.session_factory() as session, session.begin():
            document = await session.get(
                KnowledgeDocumentModel, document_id, with_for_update=True
            )
            assert document is not None
            third = await repository.create_revision(
                session,
                document=document,
                expected_revision=document.revision,
                content="Revision that fails indexing",
                actor_id=actor.id,
                embedding_version=version,
                target_collection="knowledge",
            )
            third_id = third.id
        jobs = await repository.claim("third", 20, 60)
        third_job = next(job for job in jobs if job.revision_id == third_id)
        status = await repository.release(
            third_job.id, "third", "provider_denied", 0, 1, False
        )
        assert status == KnowledgeIndexJobStatus.FAILED
        async with database.session_factory() as session:
            document = await session.get(KnowledgeDocumentModel, document_id)
            third = await session.get(KnowledgeDocumentRevisionModel, third_id)
            assert document is not None and third is not None
            assert document.current_revision_id == second_id
            assert third.index_state == KnowledgeIndexState.FAILED

        async with database.session_factory() as session, session.begin():
            document = await session.get(
                KnowledgeDocumentModel, document_id, with_for_update=True
            )
            assert document is not None
            bounded = await repository.create_revision(
                session,
                document=document,
                expected_revision=document.revision,
                content="z" * 7_000,
                actor_id=actor.id,
                embedding_version=version,
                target_collection="knowledge",
            )
            bounded_id = bounded.id
        bounded_jobs = [
            job
            for job in await repository.claim("bounded", 20, 60)
            if job.revision_id == bounded_id
        ]
        assert len(bounded_jobs) == 7
        for job in bounded_jobs:
            assert await repository.complete(job.id, "bounded")
        async with database.session_factory() as session:
            bounded_chunk_ids = tuple(
                await session.scalars(
                    select(KnowledgeChunkModel.id)
                    .where(KnowledgeChunkModel.revision_id == bounded_id)
                    .order_by(KnowledgeChunkModel.ordinal)
                )
            )
        scores = {
            chunk_id: float(len(bounded_chunk_ids) - ordinal)
            for ordinal, chunk_id in enumerate(bounded_chunk_ids)
        }
        bounded_context = await repository.revalidate_candidates(
            bounded_chunk_ids,
            tenant_id=tenant_id,
            assistant_id=assistant_id,
            eligible_base_ids=enabled,
            scores=scores,
            embedding_version=version,
            index_schema_version="knowledge-index-v1",
        )
        assert len(bounded_context) == 5
        assert sum(len(item.content) for item in bounded_context) == 6_000
        assert all(item.content == "z" * 1_200 for item in bounded_context)

        async with database.session_factory() as session, session.begin():
            document = await session.get(
                KnowledgeDocumentModel, document_id, with_for_update=True
            )
            assert document is not None
            await repository.delete_document(
                session, document, expected_revision=document.revision
            )
        assert (
            await repository.revalidate_candidates(
                (second_chunk_id,),
                tenant_id=tenant_id,
                assistant_id=assistant_id,
                eligible_base_ids=enabled,
                scores={second_chunk_id: 0.9},
                embedding_version=version,
                index_schema_version="knowledge-index-v1",
            )
            == ()
        )
        async with database.session_factory() as session:
            document = await session.get(KnowledgeDocumentModel, document_id)
            base = await session.get(KnowledgeBaseModel, base_id)
            revisions = list(
                await session.scalars(
                    select(KnowledgeDocumentRevisionModel).where(
                        KnowledgeDocumentRevisionModel.document_id == document_id
                    )
                )
            )
            delete_jobs = list(
                await session.scalars(
                    select(KnowledgeIndexJobModel).where(
                        KnowledgeIndexJobModel.document_id == document_id,
                        KnowledgeIndexJobModel.operation == "delete",
                    )
                )
            )
            assert document is not None
            assert document.status == KnowledgeDocumentStatus.DELETED
            assert base is not None and base.status == KnowledgeBaseStatus.DISABLED
            assert all(
                item.content is None and item.content_checksum is None
                for item in revisions
            )
            assert delete_jobs

        # Composite ownership constraints reject cross-Assistant attachment.
        async with database.session_factory() as session:
            foreign_assistant_id = await session.scalar(
                select(AssistantModel.id).where(AssistantModel.tenant_id != tenant_id)
            )
            assert foreign_assistant_id is not None
            session.add(
                KnowledgeBaseModel(
                    tenant_id=tenant_id,
                    assistant_id=foreign_assistant_id,
                    slug="forged",
                    name="Forged",
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
        async with database.session_factory() as session:
            immutable_ids = {
                "knowledge_document_revisions": first_id,
                "knowledge_chunks": first_chunk_id,
                "knowledge_index_jobs": await session.scalar(
                    select(KnowledgeIndexJobModel.id).where(
                        KnowledgeIndexJobModel.chunk_id == first_chunk_id,
                        KnowledgeIndexJobModel.operation == "upsert",
                    )
                ),
            }
        for table, row_id in immutable_ids.items():
            assert row_id is not None
            with pytest.raises(DBAPIError, match="knowledge ownership is immutable"):
                async with database.session_factory() as session, session.begin():
                    await session.execute(
                        text(
                            f"UPDATE {table} SET assistant_id = :assistant_id "
                            "WHERE id = :row_id"
                        ),
                        {"assistant_id": sibling_assistant_id, "row_id": row_id},
                    )
        async with database.session_factory() as session:
            memory_counts = [
                int(await session.scalar(select(func.count(model.id))) or 0)
                for model in (
                    MemoryItemModel,
                    MemoryEventModel,
                    MemoryControlOperationModel,
                    ExplicitMemorySemanticIndexJobModel,
                )
            ]
            assert memory_counts == [0, 0, 0, 0]
    finally:
        await database.stop()


def test_postgresql_authority_revisioning_and_deletion() -> None:
    asyncio.run(_scenario())


def test_real_qdrant_stores_only_opaque_identifiers() -> None:
    settings = Settings(_env_file=None, environment="test")
    collection = f"spec033_{uuid4().hex}"
    point = KnowledgePoint(
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        "test-v1",
        "knowledge-index-v1",
    )

    async def scenario() -> None:
        index = QdrantKnowledgeIndex(settings.qdrant_url)
        client = httpx.AsyncClient(base_url=settings.qdrant_url)
        try:
            await index.ensure_collection(collection, 2)
            await index.upsert(
                collection, point, EmbeddingVector.validated((0.2, 0.8), 2)
            )
            matches = await index.query(
                collection,
                EmbeddingVector.validated((0.2, 0.8), 2),
                tenant_id=point.tenant_id,
                assistant_id=point.assistant_id,
                knowledge_base_ids=(point.knowledge_base_id,),
                embedding_version=point.embedding_version,
                index_schema_version=point.index_schema_version,
                limit=20,
                minimum_score=None,
            )
            assert [item.chunk_id for item in matches] == [point.chunk_id]
            response = await client.get(
                f"/collections/{collection}/points/{point.chunk_id}"
            )
            response.raise_for_status()
            payload = response.json()["result"]["payload"]
            assert payload == point.payload()
            assert not ({"content", "text", "title", "url", "prompt"} & set(payload))
            await index.delete(collection, point.chunk_id)
            assert await index.count(collection) == 0
        finally:
            await client.delete(f"/collections/{collection}")
            await client.aclose()
            await index.aclose()

    asyncio.run(scenario())


def test_control_plane_roles_and_foreign_scope_are_fail_closed() -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        control_plane_enabled=True,
        control_plane_jwt_secret="spec033-secret-that-is-at-least-thirty-two-characters",
        control_plane_jwt_issuer="spec033-issuer",
        control_plane_jwt_audience="spec033-audience",
        embedding_provider="ollama",
        embedding_model="fixture",
        embedding_dimension=2,
    )

    def token(subject: str) -> str:
        assert settings.control_plane_jwt_secret is not None
        return jwt.encode(
            {
                "iss": settings.control_plane_jwt_issuer,
                "sub": subject,
                "aud": settings.control_plane_jwt_audience,
                "exp": datetime.now(UTC) + timedelta(hours=1),
            },
            settings.control_plane_jwt_secret.get_secret_value(),
            algorithm="HS256",
        )

    async def scenario() -> None:
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
                tenant = ControlTenantModel(slug="roles", name="Roles")
                foreign = ControlTenantModel(slug="roles-foreign", name="Foreign")
                session.add_all([tenant, foreign])
                await session.flush()
                assistant = AssistantModel(
                    tenant_id=tenant.id,
                    slug="roles-assistant",
                    name="Roles Assistant",
                    status=AssistantStatus.ACTIVE,
                )
                session.add(assistant)
                identities = {
                    role: ControlOperatorIdentityModel(
                        issuer="spec033-issuer", subject=role
                    )
                    for role in (
                        "tenant_owner",
                        "tenant_admin",
                        "auditor",
                        "operator",
                        "viewer",
                    )
                }
                deployment_only = ControlOperatorIdentityModel(
                    issuer="spec033-issuer", subject="deployment-only"
                )
                foreign_owner = ControlOperatorIdentityModel(
                    issuer="spec033-issuer", subject="foreign-owner"
                )
                session.add_all([*identities.values(), deployment_only, foreign_owner])
                await session.flush()
                session.add_all(
                    [
                        ControlOperatorMembershipModel(
                            tenant_id=tenant.id,
                            identity_id=identity.id,
                            role=role,
                        )
                        for role, identity in identities.items()
                    ]
                    + [
                        ControlOperatorMembershipModel(
                            tenant_id=foreign.id,
                            identity_id=foreign_owner.id,
                            role="tenant_owner",
                        )
                    ]
                )
                session.add(
                    ControlDeploymentAuthorityModel(
                        identity_id=deployment_only.id,
                        granted_by_identity_id=deployment_only.id,
                    )
                )
                tenant_id = tenant.id
                assistant_id = assistant.id
            app = create_app(settings)
            app.state.database = database
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                path = (
                    f"/control/v1/tenants/{tenant_id}/assistants/"
                    f"{assistant_id}/knowledge-bases"
                )
                created = await client.post(
                    path,
                    headers={"Authorization": f"Bearer {token('tenant_owner')}"},
                    json={"slug": "handbook", "name": "Handbook"},
                )
                assert created.status_code == 201
                base_id = created.json()["id"]
                enabled = await client.patch(
                    f"/control/v1/tenants/{tenant_id}/assistants/"
                    f"{assistant_id}/knowledge",
                    headers={"Authorization": f"Bearer {token('tenant_admin')}"},
                    json={"expected_revision": 1, "enabled": True},
                )
                assert enabled.status_code == 200
                assert enabled.json()["knowledge_enabled"] is True
                renamed = await client.patch(
                    f"{path}/{base_id}",
                    headers={"Authorization": f"Bearer {token('tenant_admin')}"},
                    json={"expected_revision": 1, "name": "Renamed Handbook"},
                )
                assert renamed.status_code == 200
                assert renamed.json()["revision"] == 2
                conflict = await client.patch(
                    f"{path}/{base_id}",
                    headers={"Authorization": f"Bearer {token('tenant_admin')}"},
                    json={"expected_revision": 1, "name": "Stale Update"},
                )
                assert conflict.status_code == 409
                auditor = await client.get(
                    path,
                    headers={"Authorization": f"Bearer {token('auditor')}"},
                )
                assert auditor.status_code == 200
                assert auditor.json()[0]["slug"] is None
                assert auditor.json()[0]["name"] is None
                document_path = f"{path}/{base_id}/documents"
                unsupported = await client.post(
                    document_path,
                    headers={"Authorization": f"Bearer {token('tenant_admin')}"},
                    json={
                        "slug": "pdf",
                        "title": "PDF",
                        "content_type": "application/pdf",
                    },
                )
                assert unsupported.status_code == 422
                created_document = await client.post(
                    document_path,
                    headers={"Authorization": f"Bearer {token('tenant_admin')}"},
                    json={
                        "slug": "policy",
                        "title": "Private Operator Title",
                        "source_label": "Private Source",
                        "source_reference": "https://not-fetched.invalid/reference",
                        "content_type": "text/plain",
                    },
                )
                assert created_document.status_code == 201
                document_id = created_document.json()["id"]
                revision = await client.post(
                    f"{document_path}/{document_id}/revisions",
                    headers={"Authorization": f"Bearer {token('tenant_admin')}"},
                    json={
                        "expected_revision": 1,
                        "content": "Write-only canonical content",
                    },
                )
                assert revision.status_code == 202
                assert "content" not in revision.json()
                revision_id = revision.json()["id"]
                auditor_documents = await client.get(
                    document_path,
                    headers={"Authorization": f"Bearer {token('auditor')}"},
                )
                assert auditor_documents.status_code == 200
                for field in ("slug", "title", "source_label", "source_reference"):
                    assert auditor_documents.json()[0][field] is None
                auditor_revision = await client.get(
                    f"{document_path}/{document_id}/revisions/{revision_id}",
                    headers={"Authorization": f"Bearer {token('auditor')}"},
                )
                assert auditor_revision.status_code == 200
                assert auditor_revision.json()["content_checksum"] is None
                assert "content" not in auditor_revision.json()
                status = await client.get(
                    f"/control/v1/tenants/{tenant_id}/assistants/"
                    f"{assistant_id}/knowledge-index/status",
                    headers={"Authorization": f"Bearer {token('auditor')}"},
                )
                assert status.status_code == 200
                reindex = await client.post(
                    f"/control/v1/tenants/{tenant_id}/assistants/"
                    f"{assistant_id}/knowledge-index/reindex",
                    headers={"Authorization": f"Bearer {token('tenant_admin')}"},
                )
                assert reindex.status_code == 202
                assert reindex.json()["scheduled"] == 0
                malformed = await client.get(
                    f"{path}/not-a-uuid",
                    headers={"Authorization": f"Bearer {token('auditor')}"},
                )
                assert malformed.status_code == 422
                deleted = await client.delete(
                    f"{document_path}/{document_id}?expected_revision=2",
                    headers={"Authorization": f"Bearer {token('tenant_owner')}"},
                )
                assert deleted.status_code == 204
                auditor_write = await client.post(
                    path,
                    headers={"Authorization": f"Bearer {token('auditor')}"},
                    json={"slug": "denied", "name": "Denied"},
                )
                assert auditor_write.status_code == 403
                for subject in ("operator", "viewer"):
                    denied = await client.get(
                        path,
                        headers={"Authorization": f"Bearer {token(subject)}"},
                    )
                    assert denied.status_code == 403
                for subject in ("deployment-only", "foreign-owner"):
                    hidden = await client.get(
                        path,
                        headers={"Authorization": f"Bearer {token(subject)}"},
                    )
                    assert hidden.status_code == 404
        finally:
            await database.stop()

    asyncio.run(scenario())


def test_concurrent_revision_cas_and_duplicate_document_slug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        settings = Settings(_env_file=None, environment="test")
        database = Database(settings)
        await database.start()
        repository = SqlAlchemyKnowledgeRepository(database.session_factory)
        version = embedding_version("ollama", "fixture", 2)
        try:
            async with database.session_factory() as session, session.begin():
                await session.execute(
                    text(
                        "TRUNCATE control_operator_identities, control_tenants, "
                        "assistants CASCADE"
                    )
                )
                tenant = ControlTenantModel(slug="concurrency", name="Concurrency")
                actor = ControlOperatorIdentityModel(
                    issuer="spec033-concurrency", subject="owner"
                )
                session.add_all([tenant, actor])
                await session.flush()
                assistant = AssistantModel(
                    tenant_id=tenant.id,
                    slug="concurrency-assistant",
                    name="Concurrency Assistant",
                    status=AssistantStatus.ACTIVE,
                    knowledge_enabled=True,
                )
                session.add(assistant)
                await session.flush()
                base = await repository.create_base(
                    session,
                    tenant_id=tenant.id,
                    assistant_id=assistant.id,
                    slug="concurrency-base",
                    name="Concurrency Base",
                )
                document = await repository.create_document(
                    session,
                    knowledge_base=base,
                    slug="canonical",
                    title="Canonical",
                    source_label=None,
                    source_reference=None,
                    content_type=KnowledgeContentType.TEXT,
                )
                base_id = base.id
                assistant_id = assistant.id
                document_id = document.id
                actor_id = actor.id

            revision_barrier = asyncio.Barrier(2)

            async def create_competing_revision(content: str):
                async with database.session_factory() as session, session.begin():
                    document = await session.get(KnowledgeDocumentModel, document_id)
                    assert document is not None
                    await revision_barrier.wait()
                    return await repository.create_revision(
                        session,
                        document=document,
                        expected_revision=1,
                        content=content,
                        actor_id=actor_id,
                        embedding_version=version,
                        target_collection="knowledge",
                    )

            results = await asyncio.gather(
                create_competing_revision("first contender"),
                create_competing_revision("second contender"),
                return_exceptions=True,
            )
            winners = [
                item
                for item in results
                if isinstance(item, KnowledgeDocumentRevisionModel)
            ]
            conflicts = [
                item for item in results if isinstance(item, KnowledgeConflict)
            ]
            assert len(winners) == 1
            assert len(conflicts) == 1
            winner = winners[0]
            async with database.session_factory() as session, session.begin():
                document = await session.get(KnowledgeDocumentModel, document_id)
                assert document is not None
                retried = await repository.create_revision(
                    session,
                    document=document,
                    expected_revision=1,
                    content=winner.content or "",
                    actor_id=actor_id,
                    embedding_version=version,
                    target_collection="knowledge",
                )
                assert retried.id == winner.id

            crashed = await repository.claim("crashed-worker", 1, 60)
            assert len(crashed) == 1
            async with database.session_factory() as session, session.begin():
                await session.execute(
                    text(
                        "UPDATE knowledge_index_jobs "
                        "SET lease_expires_at = :expired WHERE id = :job_id"
                    ),
                    {
                        "expired": datetime.now(UTC) - timedelta(seconds=1),
                        "job_id": crashed[0].id,
                    },
                )
            reclaimed = await repository.claim("recovery-worker", 1, 60)
            assert [job.id for job in reclaimed] == [crashed[0].id]
            assert reclaimed[0].attempt_count == 2

            document_barrier = asyncio.Barrier(2)

            async def create_duplicate_document(title: str):
                try:
                    async with database.session_factory() as session, session.begin():
                        base = await session.get(KnowledgeBaseModel, base_id)
                        assert base is not None
                        await document_barrier.wait()
                        return await repository.create_document(
                            session,
                            knowledge_base=base,
                            slug="duplicate",
                            title=title,
                            source_label=None,
                            source_reference=None,
                            content_type=KnowledgeContentType.TEXT,
                        )
                except IntegrityError as exc:
                    return exc

            duplicate_results = await asyncio.gather(
                create_duplicate_document("First"),
                create_duplicate_document("Second"),
            )
            assert (
                sum(
                    isinstance(item, KnowledgeDocumentModel)
                    for item in duplicate_results
                )
                == 1
            )
            assert (
                sum(isinstance(item, IntegrityError) for item in duplicate_results) == 1
            )
            async with database.session_factory() as session, session.begin():
                assistant = await session.get(
                    AssistantModel, assistant_id, with_for_update=True
                )
                assert assistant is not None
                assistant.status = AssistantStatus.RETIRED
                await session.execute(
                    text(
                        "UPDATE knowledge_index_jobs SET status = 'pending', "
                        "available_at = now(), lease_owner = NULL, "
                        "lease_expires_at = NULL WHERE id = :job_id"
                    ),
                    {"job_id": reclaimed[0].id},
                )
            provider_factory = Mock(
                side_effect=AssertionError("disabled Assistant created provider")
            )
            monkeypatch.setattr(
                "app.runtime.knowledge_index_worker.create_embedding_provider",
                provider_factory,
            )
            index = AsyncMock()
            assert (
                await consume_once(
                    Settings(
                        _env_file=None,
                        environment="test",
                        knowledge_rag_enabled=True,
                        knowledge_index_worker_enabled=True,
                        embedding_provider="ollama",
                        embedding_model="fixture",
                        embedding_dimension=2,
                    ),
                    database,
                    index=index,
                    owner="disabled-owner",
                )
                == 1
            )
            provider_factory.assert_not_called()
            index.ensure_collection.assert_not_awaited()
            index.upsert.assert_not_awaited()
        finally:
            await database.stop()

    asyncio.run(scenario())


def test_activation_failure_and_query_time_disable_races_fail_closed() -> None:
    async def scenario() -> None:
        settings = Settings(
            _env_file=None,
            environment="test",
            knowledge_rag_enabled=True,
            embedding_provider="ollama",
            embedding_model="fixture",
            embedding_dimension=2,
            provider_governance_mode="legacy",
            rate_limit_enabled=False,
            provider_concurrency_enabled=False,
        )
        database = Database(settings)
        await database.start()
        repository = SqlAlchemyKnowledgeRepository(database.session_factory)
        version = embedding_version("ollama", "fixture", 2)
        try:
            async with database.session_factory() as session, session.begin():
                await session.execute(
                    text(
                        "TRUNCATE control_operator_identities, control_tenants, "
                        "assistants CASCADE"
                    )
                )
                tenant = ControlTenantModel(slug="authority-race", name="Race")
                actor = ControlOperatorIdentityModel(
                    issuer="spec033-race", subject="owner"
                )
                session.add_all([tenant, actor])
                await session.flush()
                assistant = AssistantModel(
                    tenant_id=tenant.id,
                    slug="authority-race",
                    name="Authority Race",
                    status=AssistantStatus.ACTIVE,
                    knowledge_enabled=True,
                )
                session.add(assistant)
                await session.flush()
                base = await repository.create_base(
                    session,
                    tenant_id=tenant.id,
                    assistant_id=assistant.id,
                    slug="race-base",
                    name="Race Base",
                )
                document = await repository.create_document(
                    session,
                    knowledge_base=base,
                    slug="race-document",
                    title="Race Document",
                    source_label=None,
                    source_reference=None,
                    content_type=KnowledgeContentType.TEXT,
                )
                failed_revision = await repository.create_revision(
                    session,
                    document=document,
                    expected_revision=document.revision,
                    content="revision that fails during activation",
                    actor_id=actor.id,
                    embedding_version=version,
                    target_collection="knowledge",
                )
                tenant_id = tenant.id
                assistant_id = assistant.id
                base_id = base.id
                document_id = document.id
                actor_id = actor.id

            claimed = await repository.claim("activation-race", 1, 60)
            assert len(claimed) == 1
            race_barrier = asyncio.Barrier(2)

            async def activate() -> KnowledgeConflict:
                async with database.session_factory() as session, session.begin():
                    base = await session.get(
                        KnowledgeBaseModel, base_id, with_for_update=True
                    )
                    assert base is not None
                    await race_barrier.wait()
                    try:
                        await repository.transition_base(
                            session,
                            base,
                            expected_revision=base.revision,
                            target=KnowledgeBaseStatus.ACTIVE,
                        )
                    except KnowledgeConflict as exc:
                        return exc
                raise AssertionError("unready base activated during failed indexing")

            async def fail_indexing() -> KnowledgeIndexJobStatus:
                await race_barrier.wait()
                return await repository.release(
                    claimed[0].id,
                    "activation-race",
                    "provider_denied",
                    0,
                    1,
                    False,
                )

            activation_result, failure_result = await asyncio.gather(
                activate(), fail_indexing()
            )
            assert "not activation-ready" in str(activation_result)
            assert failure_result == KnowledgeIndexJobStatus.FAILED
            async with database.session_factory() as session:
                base = await session.get(KnowledgeBaseModel, base_id)
                revision = await session.get(
                    KnowledgeDocumentRevisionModel, failed_revision.id
                )
                assert base is not None and revision is not None
                assert base.status == KnowledgeBaseStatus.DRAFT
                assert revision.index_state == KnowledgeIndexState.FAILED

            async with database.session_factory() as session, session.begin():
                document = await session.get(
                    KnowledgeDocumentModel, document_id, with_for_update=True
                )
                assert document is not None
                ready_revision = await repository.create_revision(
                    session,
                    document=document,
                    expected_revision=document.revision,
                    content="authoritative content",
                    actor_id=actor_id,
                    embedding_version=version,
                    target_collection="knowledge",
                )
            ready_jobs = await repository.claim("ready-worker", 20, 60)
            ready_job = next(
                job for job in ready_jobs if job.revision_id == ready_revision.id
            )
            assert await repository.complete(ready_job.id, "ready-worker")
            async with database.session_factory() as session, session.begin():
                base = await session.get(
                    KnowledgeBaseModel, base_id, with_for_update=True
                )
                assert base is not None
                await repository.transition_base(
                    session,
                    base,
                    expected_revision=base.revision,
                    target=KnowledgeBaseStatus.ACTIVE,
                )
                chunk_id = await session.scalar(
                    select(KnowledgeChunkModel.id).where(
                        KnowledgeChunkModel.revision_id == ready_revision.id
                    )
                )
                assert chunk_id is not None

            class Provider:
                provider_id = "ollama"
                model = "fixture"
                dimension = 2

                async def embed_text(self, _: str) -> EmbeddingVector:
                    assert database.engine.pool.checkedout() == 0  # type: ignore[attr-defined]
                    return EmbeddingVector.validated((0.4, 0.6), 2)

                async def aclose(self) -> None:
                    return None

            query_calls = 0

            class DisablingIndex:
                async def query(self, *args, **kwargs):
                    nonlocal query_calls
                    query_calls += 1
                    assert database.engine.pool.checkedout() == 0  # type: ignore[attr-defined]
                    async with database.session_factory() as session, session.begin():
                        base = await session.get(
                            KnowledgeBaseModel, base_id, with_for_update=True
                        )
                        assert base is not None
                        await repository.transition_base(
                            session,
                            base,
                            expected_revision=base.revision,
                            target=KnowledgeBaseStatus.DISABLED,
                        )
                    return (KnowledgeCandidate(chunk_id, 1.0),)

                async def aclose(self) -> None:
                    return None

            retriever = KnowledgeRetriever(
                settings,
                database.session_factory,
                embedding_provider_factory=lambda _: Provider(),
                index_factory=lambda _: DisablingIndex(),
            )
            selected = await retriever.retrieve(
                "What is authoritative?",
                tenant_id=tenant_id,
                assistant_id=assistant_id,
            )
            assert query_calls == 1
            assert selected == ()
        finally:
            await database.stop()

    asyncio.run(scenario())


def test_explicit_memory_creation_creates_no_knowledge_state() -> None:
    async def scenario() -> None:
        settings = Settings(_env_file=None, environment="test")
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
                tenant = ControlTenantModel(slug="memory-separation", name="Memory")
                session.add(tenant)
                await session.flush()
                assistant = AssistantModel(
                    tenant_id=tenant.id,
                    slug="memory-assistant",
                    name="Memory Assistant",
                    status=AssistantStatus.ACTIVE,
                )
                session.add(assistant)
                await session.flush()
                connection = PlatformConnectionModel(
                    tenant_id=tenant.id,
                    assistant_id=assistant.id,
                    platform=Platform.TELEGRAM,
                    external_bot_id="memory-separation-bot",
                    status=PlatformConnectionStatus.ACTIVE,
                )
                session.add(connection)
                await session.flush()
                conversation = ConversationModel(
                    platform_connection_id=connection.id,
                    platform_conversation_id="memory-separation-chat",
                    conversation_type=ConversationType.GROUP,
                )
                session.add(conversation)
                await session.flush()
                participant = ParticipantModel(
                    conversation_id=conversation.id,
                    platform_user_id="memory-user",
                    display_name="Memory User",
                )
                session.add(participant)
                await session.flush()
                message = MessageModel(
                    conversation_id=conversation.id,
                    participant_id=participant.id,
                    platform_message_id="memory-message",
                    direction=MessageDirection.INCOMING,
                    message_type=MessageType.TEXT,
                    processing_status=MessageProcessingStatus.PROCESSED,
                    text="/memory remember separate fact",
                    platform_sent_at=datetime.now(UTC),
                )
                incoming = IncomingPlatformUpdateModel(
                    platform_connection_id=connection.id,
                    platform=Platform.TELEGRAM,
                    platform_update_id="memory-update",
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
                    command_name="memory",
                    arguments="remember separate fact",
                )
                session.add(command)
                planning = ResponsePlanningJobModel(
                    conversation_processing_record_id=record.id,
                    conversation_id=conversation.id,
                    message_id=message.id,
                    prompt_version="spec033-test",
                    response_schema_version="spec033-test",
                )
                session.add(planning)
                await session.flush()
                ids = (
                    assistant.id,
                    connection.id,
                    conversation.id,
                    participant.id,
                    message.id,
                    command.id,
                    planning.id,
                )
            memory = await SqlAlchemyMemoryRepository(
                database.session_factory, "separation-v1"
            ).create(
                assistant_id=ids[0],
                platform_connection_id=ids[1],
                conversation_id=ids[2],
                creator_participant_id=ids[3],
                source_message_id=ids[4],
                source_command_job_id=ids[5],
                draft=normalize_explicit_memory(
                    "separate fact", MemoryScope.GROUP_CONVERSATION
                ),
            )
            assert memory.content == "separate fact"
            with pytest.raises(IntegrityError):
                async with database.session_factory() as session, session.begin():
                    await session.execute(
                        text(
                            "UPDATE response_planning_jobs "
                            "SET knowledge_provenance = CAST(:value AS jsonb) "
                            "WHERE id = :job_id"
                        ),
                        {
                            "value": json.dumps(
                                [
                                    {
                                        "chunk_id": str(uuid4()),
                                        "document_id": str(uuid4()),
                                        "knowledge_base_id": str(uuid4()),
                                        "revision_id": str(uuid4()),
                                        "content": "forbidden",
                                    }
                                ]
                            ),
                            "job_id": ids[6],
                        },
                    )
            async with database.session_factory() as session:
                assert (
                    int(
                        await session.scalar(select(func.count(MemoryItemModel.id)))
                        or 0
                    )
                    == 1
                )
                knowledge_counts = [
                    int(await session.scalar(select(func.count(model.id))) or 0)
                    for model in (
                        KnowledgeBaseModel,
                        KnowledgeDocumentModel,
                        KnowledgeDocumentRevisionModel,
                        KnowledgeChunkModel,
                        KnowledgeIndexJobModel,
                    )
                ]
                assert knowledge_counts == [0, 0, 0, 0, 0]
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("mutation", ["delete", "retire"])
def test_authority_change_during_qdrant_upsert_never_activates_stale_work(
    mutation: str,
) -> None:
    async def scenario() -> None:
        settings = Settings(
            _env_file=None,
            environment="test",
            knowledge_rag_enabled=True,
            knowledge_index_worker_enabled=True,
            embedding_provider="ollama",
            embedding_model="fixture",
            embedding_dimension=2,
            provider_governance_mode="legacy",
            rate_limit_enabled=False,
            provider_concurrency_enabled=False,
        )
        database = Database(settings)
        await database.start()
        repository = SqlAlchemyKnowledgeRepository(database.session_factory)
        version = embedding_version("ollama", "fixture", 2)
        points: set = set()
        try:
            async with database.session_factory() as session, session.begin():
                await session.execute(
                    text(
                        "TRUNCATE control_operator_identities, control_tenants, "
                        "assistants CASCADE"
                    )
                )
                tenant = ControlTenantModel(slug=f"race-{mutation}", name="Race")
                actor = ControlOperatorIdentityModel(
                    issuer="spec033-race", subject=mutation
                )
                session.add_all([tenant, actor])
                await session.flush()
                assistant = AssistantModel(
                    tenant_id=tenant.id,
                    slug=f"race-{mutation}",
                    name="Race Assistant",
                    status=AssistantStatus.ACTIVE,
                    knowledge_enabled=True,
                )
                session.add(assistant)
                await session.flush()
                base = await repository.create_base(
                    session,
                    tenant_id=tenant.id,
                    assistant_id=assistant.id,
                    slug="race-base",
                    name="Race Base",
                )
                document = await repository.create_document(
                    session,
                    knowledge_base=base,
                    slug="race-document",
                    title="Race Document",
                    source_label=None,
                    source_reference=None,
                    content_type=KnowledgeContentType.TEXT,
                )
                revision = await repository.create_revision(
                    session,
                    document=document,
                    expected_revision=document.revision,
                    content="Content whose authority changes during upsert",
                    actor_id=actor.id,
                    embedding_version=version,
                    target_collection="race-collection",
                )
                base_id = base.id
                document_id = document.id
                revision_id = revision.id

            class Provider:
                provider_id = "ollama"
                model = "fixture"
                dimension = 2

                async def embed_text(self, _: str) -> EmbeddingVector:
                    assert database.engine.pool.checkedout() == 0  # type: ignore[attr-defined]
                    return EmbeddingVector.validated((0.3, 0.7), 2)

                async def aclose(self) -> None:
                    return None

            class RacingIndex:
                async def health(self) -> bool:
                    return True

                async def ensure_collection(self, _: str, __: int) -> None:
                    assert database.engine.pool.checkedout() == 0  # type: ignore[attr-defined]

                async def upsert(self, _, point: KnowledgePoint, __) -> None:
                    assert database.engine.pool.checkedout() == 0  # type: ignore[attr-defined]
                    async with database.session_factory() as session, session.begin():
                        if mutation == "delete":
                            document = await session.get(
                                KnowledgeDocumentModel,
                                document_id,
                                with_for_update=True,
                            )
                            assert document is not None
                            await repository.delete_document(
                                session,
                                document,
                                expected_revision=document.revision,
                            )
                        else:
                            base = await session.get(
                                KnowledgeBaseModel, base_id, with_for_update=True
                            )
                            assert base is not None
                            await repository.transition_base(
                                session,
                                base,
                                expected_revision=base.revision,
                                target=KnowledgeBaseStatus.RETIRED,
                            )
                    points.add(point.chunk_id)

                async def delete(self, _: str, chunk_id) -> None:
                    assert database.engine.pool.checkedout() == 0  # type: ignore[attr-defined]
                    points.discard(chunk_id)

                async def count(self, _: str) -> int:
                    return len(points)

                async def list_chunk_ids(self, _: str):
                    return tuple(points)

                async def query(self, *args, **kwargs):
                    return ()

                async def aclose(self) -> None:
                    return None

            assert (
                await consume_once(
                    settings,
                    database,
                    provider=Provider(),
                    index=RacingIndex(),
                    owner=f"race-{mutation}",
                )
                == 1
            )
            assert len(points) == 1
            async with database.session_factory() as session:
                document = await session.get(KnowledgeDocumentModel, document_id)
                revision = await session.get(
                    KnowledgeDocumentRevisionModel, revision_id
                )
                assert document is not None and revision is not None
                assert document.current_revision_id is None
                assert revision.index_state in {
                    KnowledgeIndexState.DELETED,
                    KnowledgeIndexState.FAILED,
                }
            assert (
                await consume_once(
                    settings,
                    database,
                    provider=Provider(),
                    index=RacingIndex(),
                    owner=f"race-cleanup-{mutation}",
                )
                == 1
            )
            assert points == set()
        finally:
            await database.stop()

    asyncio.run(scenario())


def test_worker_closes_database_scope_and_stale_point_cannot_return_content() -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        knowledge_rag_enabled=True,
        knowledge_index_worker_enabled=True,
        embedding_provider="ollama",
        embedding_model="fixture",
        embedding_dimension=2,
        provider_governance_mode="legacy",
        rate_limit_enabled=False,
        provider_concurrency_enabled=False,
    )

    async def scenario() -> None:
        database = Database(settings)
        await database.start()
        repository = SqlAlchemyKnowledgeRepository(database.session_factory)
        raw_index = QdrantKnowledgeIndex(settings.qdrant_url)
        collection = f"spec033_worker_{uuid4().hex}"

        class GuardedProvider:
            provider_id = "ollama"
            model = "fixture"
            dimension = 2

            async def embed_text(self, value: str) -> EmbeddingVector:
                assert value == "Worker-owned canonical content"
                assert database.engine.pool.checkedout() == 0  # type: ignore[attr-defined]
                return EmbeddingVector.validated((0.4, 0.6), 2)

            async def aclose(self) -> None:
                return None

        class GuardedIndex:
            async def health(self) -> bool:
                return await raw_index.health()

            async def ensure_collection(self, name: str, dimension: int) -> None:
                assert database.engine.pool.checkedout() == 0  # type: ignore[attr-defined]
                await raw_index.ensure_collection(name, dimension)

            async def upsert(
                self, name: str, point: KnowledgePoint, vector: EmbeddingVector
            ) -> None:
                assert database.engine.pool.checkedout() == 0  # type: ignore[attr-defined]
                await raw_index.upsert(name, point, vector)

            async def delete(self, name: str, chunk_id) -> None:
                assert database.engine.pool.checkedout() == 0  # type: ignore[attr-defined]
                await raw_index.delete(name, chunk_id)

            async def count(self, name: str) -> int | None:
                return await raw_index.count(name)

            async def list_chunk_ids(self, name: str):
                return await raw_index.list_chunk_ids(name)

            async def query(self, *args, **kwargs):
                return await raw_index.query(*args, **kwargs)

            async def aclose(self) -> None:
                return None

        try:
            async with database.session_factory() as session, session.begin():
                await session.execute(
                    text(
                        "TRUNCATE control_operator_identities, control_tenants, "
                        "assistants CASCADE"
                    )
                )
                tenant = ControlTenantModel(slug="worker", name="Worker")
                actor = ControlOperatorIdentityModel(
                    issuer="spec033-worker", subject="owner"
                )
                session.add_all([tenant, actor])
                await session.flush()
                assistant = AssistantModel(
                    tenant_id=tenant.id,
                    slug="worker-assistant",
                    name="Worker Assistant",
                    status=AssistantStatus.ACTIVE,
                    knowledge_enabled=True,
                )
                session.add(assistant)
                await session.flush()
                base = await repository.create_base(
                    session,
                    tenant_id=tenant.id,
                    assistant_id=assistant.id,
                    slug="worker-base",
                    name="Worker Base",
                )
                document = await repository.create_document(
                    session,
                    knowledge_base=base,
                    slug="worker-doc",
                    title="Worker Doc",
                    source_label=None,
                    source_reference=None,
                    content_type=KnowledgeContentType.TEXT,
                )
                revision = await repository.create_revision(
                    session,
                    document=document,
                    expected_revision=document.revision,
                    content="Worker-owned canonical content",
                    actor_id=actor.id,
                    embedding_version=embedding_version("ollama", "fixture", 2),
                    target_collection=collection,
                )
                tenant_id = tenant.id
                assistant_id = assistant.id
                base_id = base.id
                document_id = document.id
                revision_id = revision.id
            assert (
                await consume_once(
                    settings,
                    database,
                    provider=GuardedProvider(),
                    index=GuardedIndex(),
                    owner="guarded-worker",
                )
                == 1
            )
            async with database.session_factory() as session, session.begin():
                base = await session.get(
                    KnowledgeBaseModel, base_id, with_for_update=True
                )
                assert base is not None
                await repository.transition_base(
                    session,
                    base,
                    expected_revision=base.revision,
                    target=KnowledgeBaseStatus.ACTIVE,
                )
                chunk = await session.scalar(
                    select(KnowledgeChunkModel).where(
                        KnowledgeChunkModel.revision_id == revision_id
                    )
                )
                assert chunk is not None
                chunk_id = chunk.id
            matches = await raw_index.query(
                collection,
                EmbeddingVector.validated((0.4, 0.6), 2),
                tenant_id=tenant_id,
                assistant_id=assistant_id,
                knowledge_base_ids=(base_id,),
                embedding_version=embedding_version("ollama", "fixture", 2),
                index_schema_version="knowledge-index-v1",
                limit=20,
                minimum_score=None,
            )
            assert [item.chunk_id for item in matches] == [chunk_id]
            enabled = await repository.retrieval_enabled(tenant_id, assistant_id)
            selected = await repository.revalidate_candidates(
                (chunk_id,),
                tenant_id=tenant_id,
                assistant_id=assistant_id,
                eligible_base_ids=enabled,
                scores={chunk_id: 1.0},
                embedding_version=embedding_version("ollama", "fixture", 2),
                index_schema_version="knowledge-index-v1",
            )
            assert [item.content for item in selected] == [
                "Worker-owned canonical content"
            ]
            # Qdrant is disposable: reset it, prove PostgreSQL still serves as
            # authority, then rebuild an exact fresh derived collection.
            async with httpx.AsyncClient(base_url=settings.qdrant_url) as client:
                reset = await client.delete(f"/collections/{collection}")
                reset.raise_for_status()
            assert await raw_index.count(collection) is None
            after_reset = await repository.revalidate_candidates(
                (chunk_id,),
                tenant_id=tenant_id,
                assistant_id=assistant_id,
                eligible_base_ids=enabled,
                scores={chunk_id: 1.0},
                embedding_version=embedding_version("ollama", "fixture", 2),
                index_schema_version="knowledge-index-v1",
            )
            assert [item.content for item in after_reset] == [
                "Worker-owned canonical content"
            ]
            rebuilt = await operate(
                "rebuild",
                True,
                settings=settings,
                database=database,
                index=GuardedIndex(),
                provider=GuardedProvider(),
            )
            rebuilt_collection = rebuilt["collection"]
            assert isinstance(rebuilt_collection, str)
            assert rebuilt["active_chunk_count"] == 1
            assert rebuilt["indexed_point_count"] == 1
            assert (
                await repository.active_collection(
                    embedding_version("ollama", "fixture", 2), "missing"
                )
                == rebuilt_collection
            )
            rebuilt_matches = await raw_index.query(
                rebuilt_collection,
                EmbeddingVector.validated((0.4, 0.6), 2),
                tenant_id=tenant_id,
                assistant_id=assistant_id,
                knowledge_base_ids=(base_id,),
                embedding_version=embedding_version("ollama", "fixture", 2),
                index_schema_version="knowledge-index-v1",
                limit=20,
                minimum_score=None,
            )
            assert [item.chunk_id for item in rebuilt_matches] == [chunk_id]
            async with database.session_factory() as session, session.begin():
                document = await session.get(
                    KnowledgeDocumentModel, document_id, with_for_update=True
                )
                assert document is not None
                await repository.delete_document(
                    session, document, expected_revision=document.revision
                )
            # The point still exists until the delete worker runs, but PostgreSQL
            # has already made it incapable of yielding content.
            assert await raw_index.count(rebuilt_collection) == 1
            assert (
                await repository.revalidate_candidates(
                    (chunk_id,),
                    tenant_id=tenant_id,
                    assistant_id=assistant_id,
                    eligible_base_ids=enabled,
                    scores={chunk_id: 1.0},
                    embedding_version=embedding_version("ollama", "fixture", 2),
                    index_schema_version="knowledge-index-v1",
                )
                == ()
            )
            assert (
                await consume_once(
                    settings,
                    database,
                    provider=GuardedProvider(),
                    index=GuardedIndex(),
                    owner="guarded-delete-worker",
                )
                == 2
            )
            assert await raw_index.count(rebuilt_collection) == 0
        finally:
            async with httpx.AsyncClient(base_url=settings.qdrant_url) as client:
                await client.delete(f"/collections/{collection}")
                if "rebuilt_collection" in locals():
                    await client.delete(f"/collections/{rebuilt_collection}")
            await raw_index.aclose()
            await database.stop()

    asyncio.run(scenario())
