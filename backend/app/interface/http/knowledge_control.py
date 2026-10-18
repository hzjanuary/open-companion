"""Authenticated tenant-scoped control plane for Assistant knowledge."""

# FastAPI dependencies are intentionally declared at route boundaries.
# ruff: noqa: B008

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.knowledge import knowledge_collection_name
from app.application.semantic_memory import embedding_version
from app.core.config import Settings
from app.domain.knowledge import KnowledgeBaseStatus, KnowledgeContentType
from app.infrastructure.database.knowledge import (
    KnowledgeConflict,
    KnowledgeLimitExceeded,
    SqlAlchemyKnowledgeRepository,
)
from app.infrastructure.database.models import (
    AssistantModel,
    KnowledgeBaseModel,
    KnowledgeDocumentModel,
    KnowledgeDocumentRevisionModel,
    KnowledgeIndexJobModel,
)
from app.infrastructure.database.tenancy import assistant_for_tenant
from app.interface.http.control_plane import (
    ADMIN_ROLES,
    Principal,
    audit,
    membership_for,
    principal_for,
)
from app.interface.http.dependencies import database_session


class KnowledgeEnablePatch(BaseModel):
    expected_revision: int = Field(ge=1)
    enabled: bool


class KnowledgeBaseInput(BaseModel):
    slug: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=160)


class KnowledgeBasePatch(BaseModel):
    expected_revision: int = Field(ge=1)
    status: KnowledgeBaseStatus | None = None
    name: str | None = Field(default=None, min_length=1, max_length=160)

    @model_validator(mode="after")
    def require_change(self) -> "KnowledgeBasePatch":
        if self.status is None and self.name is None:
            raise ValueError("a knowledge base change is required")
        return self


class KnowledgeDocumentInput(BaseModel):
    slug: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*$")
    title: str = Field(min_length=1, max_length=160)
    source_label: str | None = Field(default=None, max_length=160)
    source_reference: str | None = Field(default=None, max_length=2048)
    content_type: KnowledgeContentType


class KnowledgeRevisionInput(BaseModel):
    expected_revision: int = Field(ge=1)
    content: str = Field(min_length=1, max_length=200_000)


def _require_admin(role: str) -> None:
    if role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Forbidden")


def _require_audit_read(role: str) -> None:
    if role not in ADMIN_ROLES | {"auditor"}:
        raise HTTPException(status_code=403, detail="Forbidden")


def _base_body(
    row: KnowledgeBaseModel, *, content_free: bool = False
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "assistant_id": str(row.assistant_id),
        "slug": row.slug,
        "name": row.name,
        "status": row.status.value,
        "revision": row.revision,
    }
    if content_free:
        body["slug"] = None
        body["name"] = None
    return body


def _document_body(row: KnowledgeDocumentModel) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "knowledge_base_id": str(row.knowledge_base_id),
        "slug": row.slug,
        "title": row.title,
        "source_label": row.source_label,
        "source_reference": row.source_reference,
        "content_type": row.content_type.value,
        "status": row.status.value,
        "latest_revision_number": row.latest_revision_number,
        "current_revision_id": str(row.current_revision_id)
        if row.current_revision_id
        else None,
        "revision": row.revision,
    }


def _content_free_document_body(row: KnowledgeDocumentModel) -> dict[str, Any]:
    body = _document_body(row)
    for field in ("slug", "title", "source_label", "source_reference"):
        body[field] = None
    return body


async def _base_for(
    session: AsyncSession, tenant_id: UUID, assistant_id: UUID, base_id: UUID
) -> KnowledgeBaseModel:
    row = await session.scalar(
        select(KnowledgeBaseModel).where(
            KnowledgeBaseModel.id == base_id,
            KnowledgeBaseModel.tenant_id == tenant_id,
            KnowledgeBaseModel.assistant_id == assistant_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    return row


async def _document_for(
    session: AsyncSession,
    tenant_id: UUID,
    assistant_id: UUID,
    base_id: UUID,
    document_id: UUID,
) -> KnowledgeDocumentModel:
    row = await session.scalar(
        select(KnowledgeDocumentModel).where(
            KnowledgeDocumentModel.id == document_id,
            KnowledgeDocumentModel.tenant_id == tenant_id,
            KnowledgeDocumentModel.assistant_id == assistant_id,
            KnowledgeDocumentModel.knowledge_base_id == base_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    return row


def create_knowledge_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/control/v1", tags=["knowledge"])

    @router.patch("/tenants/{tenant_id}/assistants/{assistant_id}/knowledge")
    async def set_knowledge_enabled(
        tenant_id: UUID,
        assistant_id: UUID,
        body: KnowledgeEnablePatch,
        request: Request,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        member = await membership_for(session, principal, tenant_id)
        _require_admin(member.role)
        assistant = await session.scalar(
            select(AssistantModel)
            .where(
                AssistantModel.id == assistant_id,
                AssistantModel.tenant_id == tenant_id,
            )
            .with_for_update()
        )
        if assistant is None:
            raise HTTPException(status_code=404, detail="Not found")
        if assistant.revision != body.expected_revision:
            raise HTTPException(status_code=409, detail="Assistant revision conflict")
        assistant.knowledge_enabled = body.enabled
        assistant.revision += 1
        await audit(
            session,
            request,
            tenant_id,
            principal,
            "knowledge.enablement.update",
            "succeeded",
            "assistant",
            assistant.id,
            "spec-033-v1",
        )
        await session.commit()
        return {
            "assistant_id": str(assistant.id),
            "knowledge_enabled": assistant.knowledge_enabled,
            "revision": assistant.revision,
        }

    @router.get("/tenants/{tenant_id}/assistants/{assistant_id}/knowledge-bases")
    async def list_bases(
        tenant_id: UUID,
        assistant_id: UUID,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> list[dict[str, Any]]:
        member = await membership_for(session, principal, tenant_id)
        _require_audit_read(member.role)
        if await assistant_for_tenant(session, tenant_id, assistant_id) is None:
            raise HTTPException(status_code=404, detail="Not found")
        rows = await session.scalars(
            select(KnowledgeBaseModel)
            .where(
                KnowledgeBaseModel.tenant_id == tenant_id,
                KnowledgeBaseModel.assistant_id == assistant_id,
            )
            .order_by(KnowledgeBaseModel.slug)
        )
        return [_base_body(row, content_free=member.role == "auditor") for row in rows]

    @router.get(
        "/tenants/{tenant_id}/assistants/{assistant_id}/knowledge-bases/{base_id}"
    )
    async def get_base(
        tenant_id: UUID,
        assistant_id: UUID,
        base_id: UUID,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        member = await membership_for(session, principal, tenant_id)
        _require_audit_read(member.role)
        row = await _base_for(session, tenant_id, assistant_id, base_id)
        return _base_body(row, content_free=member.role == "auditor")

    @router.post(
        "/tenants/{tenant_id}/assistants/{assistant_id}/knowledge-bases",
        status_code=201,
    )
    async def create_base(
        tenant_id: UUID,
        assistant_id: UUID,
        body: KnowledgeBaseInput,
        request: Request,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        member = await membership_for(session, principal, tenant_id)
        _require_admin(member.role)
        if await assistant_for_tenant(session, tenant_id, assistant_id) is None:
            raise HTTPException(status_code=404, detail="Not found")
        try:
            row = await SqlAlchemyKnowledgeRepository.create_base(
                session,
                tenant_id=tenant_id,
                assistant_id=assistant_id,
                slug=body.slug,
                name=body.name,
            )
            await audit(
                session,
                request,
                tenant_id,
                principal,
                "knowledge_base.create",
                "succeeded",
                "knowledge_base",
                row.id,
                "spec-033-v1",
            )
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(
                status_code=409, detail="Knowledge base conflicts"
            ) from exc
        except KnowledgeLimitExceeded as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _base_body(row)

    @router.patch(
        "/tenants/{tenant_id}/assistants/{assistant_id}/knowledge-bases/{base_id}"
    )
    async def transition_base(
        tenant_id: UUID,
        assistant_id: UUID,
        base_id: UUID,
        body: KnowledgeBasePatch,
        request: Request,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        member = await membership_for(session, principal, tenant_id)
        _require_admin(member.role)
        row = await _base_for(session, tenant_id, assistant_id, base_id)
        try:
            if row.revision != body.expected_revision:
                raise KnowledgeConflict("knowledge base revision conflict")
            if body.status is not None:
                await SqlAlchemyKnowledgeRepository.transition_base(
                    session,
                    row,
                    expected_revision=body.expected_revision,
                    target=body.status,
                )
            if body.name is not None:
                if body.status is None:
                    row.revision += 1
                if row.status == KnowledgeBaseStatus.RETIRED:
                    raise KnowledgeConflict("retired knowledge base is immutable")
                row.name = body.name
        except KnowledgeConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        await audit(
            session,
            request,
            tenant_id,
            principal,
            "knowledge_base.transition",
            "succeeded",
            "knowledge_base",
            row.id,
            "spec-033-v1",
        )
        await session.commit()
        return _base_body(row)

    @router.get(
        "/tenants/{tenant_id}/assistants/{assistant_id}/knowledge-bases/{base_id}/documents"
    )
    async def list_documents(
        tenant_id: UUID,
        assistant_id: UUID,
        base_id: UUID,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> list[dict[str, Any]]:
        member = await membership_for(session, principal, tenant_id)
        _require_audit_read(member.role)
        await _base_for(session, tenant_id, assistant_id, base_id)
        rows = await session.scalars(
            select(KnowledgeDocumentModel)
            .where(KnowledgeDocumentModel.knowledge_base_id == base_id)
            .order_by(KnowledgeDocumentModel.slug)
        )
        return [
            _content_free_document_body(row)
            if member.role == "auditor"
            else _document_body(row)
            for row in rows
        ]

    @router.get(
        "/tenants/{tenant_id}/assistants/{assistant_id}/knowledge-bases/{base_id}/documents/{document_id}"
    )
    async def get_document(
        tenant_id: UUID,
        assistant_id: UUID,
        base_id: UUID,
        document_id: UUID,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        member = await membership_for(session, principal, tenant_id)
        _require_audit_read(member.role)
        row = await _document_for(
            session, tenant_id, assistant_id, base_id, document_id
        )
        return (
            _content_free_document_body(row)
            if member.role == "auditor"
            else _document_body(row)
        )

    @router.post(
        "/tenants/{tenant_id}/assistants/{assistant_id}/knowledge-bases/{base_id}/documents",
        status_code=201,
    )
    async def create_document(
        tenant_id: UUID,
        assistant_id: UUID,
        base_id: UUID,
        body: KnowledgeDocumentInput,
        request: Request,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        member = await membership_for(session, principal, tenant_id)
        _require_admin(member.role)
        base = await _base_for(session, tenant_id, assistant_id, base_id)
        try:
            row = await SqlAlchemyKnowledgeRepository.create_document(
                session,
                knowledge_base=base,
                slug=body.slug,
                title=body.title,
                source_label=body.source_label,
                source_reference=body.source_reference,
                content_type=body.content_type,
            )
            await audit(
                session,
                request,
                tenant_id,
                principal,
                "knowledge_document.create",
                "succeeded",
                "knowledge_document",
                row.id,
                "spec-033-v1",
            )
            await session.commit()
        except (KnowledgeConflict, KnowledgeLimitExceeded) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(
                status_code=409, detail="Knowledge document conflicts"
            ) from exc
        return _document_body(row)

    @router.post(
        "/tenants/{tenant_id}/assistants/{assistant_id}/knowledge-bases/{base_id}/documents/{document_id}/revisions",
        status_code=202,
    )
    async def create_revision(
        tenant_id: UUID,
        assistant_id: UUID,
        base_id: UUID,
        document_id: UUID,
        body: KnowledgeRevisionInput,
        request: Request,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        member = await membership_for(session, principal, tenant_id)
        _require_admin(member.role)
        document = await _document_for(
            session, tenant_id, assistant_id, base_id, document_id
        )
        await session.refresh(document, with_for_update=True)
        if not settings.embedding_provider or not settings.embedding_model:
            raise HTTPException(
                status_code=409, detail="Knowledge embedding is not configured"
            )
        version = embedding_version(
            settings.embedding_provider,
            settings.embedding_model,
            settings.embedding_dimension,
        )
        collection = knowledge_collection_name(
            settings.knowledge_qdrant_collection_prefix, version
        )
        try:
            revision = await SqlAlchemyKnowledgeRepository.create_revision(
                session,
                document=document,
                expected_revision=body.expected_revision,
                content=body.content,
                actor_id=principal.identity.id,
                embedding_version=version,
                target_collection=collection,
            )
            await audit(
                session,
                request,
                tenant_id,
                principal,
                "knowledge_revision.create",
                "accepted",
                "knowledge_revision",
                revision.id,
                "spec-033-v1",
            )
            await session.commit()
        except (KnowledgeConflict, KnowledgeLimitExceeded, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "id": str(revision.id),
            "document_id": str(document.id),
            "revision_number": revision.revision_number,
            "index_state": revision.index_state.value,
            "character_count": revision.character_count,
            "byte_count": revision.byte_count,
            "chunking_version": revision.chunking_version,
        }

    @router.get(
        "/tenants/{tenant_id}/assistants/{assistant_id}/knowledge-bases/{base_id}/documents/{document_id}/revisions/{revision_id}"
    )
    async def get_revision(
        tenant_id: UUID,
        assistant_id: UUID,
        base_id: UUID,
        document_id: UUID,
        revision_id: UUID,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        member = await membership_for(session, principal, tenant_id)
        _require_audit_read(member.role)
        await _document_for(session, tenant_id, assistant_id, base_id, document_id)
        row = await session.scalar(
            select(KnowledgeDocumentRevisionModel).where(
                KnowledgeDocumentRevisionModel.id == revision_id,
                KnowledgeDocumentRevisionModel.document_id == document_id,
                KnowledgeDocumentRevisionModel.knowledge_base_id == base_id,
                KnowledgeDocumentRevisionModel.tenant_id == tenant_id,
                KnowledgeDocumentRevisionModel.assistant_id == assistant_id,
            )
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Not found")
        result: dict[str, Any] = {
            "id": str(row.id),
            "revision_number": row.revision_number,
            "index_state": row.index_state.value,
            "character_count": row.character_count,
            "byte_count": row.byte_count,
            "content_checksum": row.content_checksum,
        }
        if member.role == "auditor":
            result["content_checksum"] = None
        return result

    @router.delete(
        "/tenants/{tenant_id}/assistants/{assistant_id}/knowledge-bases/{base_id}/documents/{document_id}",
        status_code=204,
    )
    async def delete_document(
        tenant_id: UUID,
        assistant_id: UUID,
        base_id: UUID,
        document_id: UUID,
        request: Request,
        expected_revision: int = Query(ge=1),
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> None:
        member = await membership_for(session, principal, tenant_id)
        _require_admin(member.role)
        document = await _document_for(
            session, tenant_id, assistant_id, base_id, document_id
        )
        await session.refresh(document, with_for_update=True)
        try:
            await SqlAlchemyKnowledgeRepository.delete_document(
                session, document, expected_revision=expected_revision
            )
        except KnowledgeConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        await audit(
            session,
            request,
            tenant_id,
            principal,
            "knowledge_document.delete",
            "succeeded",
            "knowledge_document",
            document.id,
            "spec-033-v1",
        )
        await session.commit()

    @router.get("/tenants/{tenant_id}/assistants/{assistant_id}/knowledge-index/status")
    async def index_status(
        tenant_id: UUID,
        assistant_id: UUID,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        member = await membership_for(session, principal, tenant_id)
        _require_audit_read(member.role)
        if await assistant_for_tenant(session, tenant_id, assistant_id) is None:
            raise HTTPException(status_code=404, detail="Not found")
        rows = await session.execute(
            select(KnowledgeIndexJobModel.status, func.count(KnowledgeIndexJobModel.id))
            .where(
                KnowledgeIndexJobModel.tenant_id == tenant_id,
                KnowledgeIndexJobModel.assistant_id == assistant_id,
            )
            .group_by(KnowledgeIndexJobModel.status)
        )
        return {
            "assistant_id": str(assistant_id),
            "jobs": {status.value: int(count) for status, count in rows},
        }

    @router.post(
        "/tenants/{tenant_id}/assistants/{assistant_id}/knowledge-index/reindex",
        status_code=202,
    )
    async def request_reindex(
        tenant_id: UUID,
        assistant_id: UUID,
        request: Request,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        member = await membership_for(session, principal, tenant_id)
        _require_admin(member.role)
        if await assistant_for_tenant(session, tenant_id, assistant_id) is None:
            raise HTTPException(status_code=404, detail="Not found")
        if not settings.embedding_provider or not settings.embedding_model:
            raise HTTPException(
                status_code=409, detail="Knowledge embedding is not configured"
            )
        version = embedding_version(
            settings.embedding_provider,
            settings.embedding_model,
            settings.embedding_dimension,
        )
        repository = SqlAlchemyKnowledgeRepository(
            request.app.state.database.session_factory
        )
        await session.commit()
        collection = await repository.active_collection(
            version,
            knowledge_collection_name(
                settings.knowledge_qdrant_collection_prefix, version
            ),
        )
        scheduled = await repository.schedule_rebuild(
            version,
            collection,
            tenant_id=tenant_id,
            assistant_id=assistant_id,
            include_nonretrievable_bases=True,
        )
        async with request.app.state.database.session_factory() as audit_session:
            await audit(
                audit_session,
                request,
                tenant_id,
                principal,
                "knowledge_index.reindex",
                "accepted",
                "assistant",
                assistant_id,
                "spec-033-v1",
            )
            await audit_session.commit()
        return {"assistant_id": str(assistant_id), "scheduled": scheduled}

    return router
