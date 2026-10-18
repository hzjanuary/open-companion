"""Authenticated, tenant-scoped SPEC-021 control-plane API."""

# FastAPI dependencies are intentionally declared at route boundaries.
# ruff: noqa: B008

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import UUID, uuid4

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.telemetry import MetricsRecorder, NoOpMetricsRecorder
from app.core.config import Settings
from app.domain.governance import (
    DEPLOYMENT_EXPORT_CATEGORIES,
    GOVERNANCE_EXPORT_SCHEMA_VERSION,
    GovernanceScope,
)
from app.domain.persistence import (
    AssistantStatus,
    Platform,
    PlatformConnectionStatus,
    TenantStatus,
)
from app.domain.safety import ReviewAction
from app.domain.tenancy import (
    assistant_transition_allowed,
    connection_transition_allowed,
    tenant_transition_allowed,
)
from app.infrastructure.database.database import Database
from app.infrastructure.database.deployment_authority import (
    DeploymentAuthorityIdempotencyConflict,
    SqlAlchemyDeploymentAuthorityRepository,
    has_deployment_authority,
)
from app.infrastructure.database.governance import SqlAlchemyGovernanceRepository
from app.infrastructure.database.models import (
    AssistantModel,
    ControlAssistantBindingModel,
    ControlAuditEventModel,
    ControlConnectionBindingModel,
    ControlGroupBindingModel,
    ControlGroupRevisionModel,
    ControlOperatorIdentityModel,
    ControlOperatorMembershipModel,
    ControlTenantModel,
    ConversationModel,
    ParticipantModel,
    PlatformConnectionModel,
    SafetyReviewItemModel,
)
from app.infrastructure.database.personality import ensure_assistant_default
from app.infrastructure.database.safety_protection import (
    SqlAlchemySafetyModerationRepository,
)
from app.infrastructure.database.tenancy import (
    assistant_for_tenant,
    connection_for_tenant,
)
from app.interface.http.dependencies import database_session

Role = Literal["tenant_owner", "tenant_admin", "operator", "auditor", "viewer"]
WRITE_ROLES: set[str] = {"tenant_owner", "tenant_admin"}
ADMIN_ROLES: set[str] = {"tenant_owner", "tenant_admin"}
RESOURCE_READ_ROLES: set[str] = ADMIN_ROLES | {"operator", "auditor"}


class ControlError(BaseModel):
    error_type: str
    message: str
    request_id: str


class TenantInput(BaseModel):
    slug: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=160)


class TenantPatch(BaseModel):
    expected_revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    status: TenantStatus | None = None


class MembershipInput(BaseModel):
    issuer: str = Field(min_length=1, max_length=255)
    subject: str = Field(min_length=1, max_length=255)
    role: Role
    display_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=320)


class AssistantInput(BaseModel):
    slug: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=100)


class AssistantPatch(BaseModel):
    expected_revision: int = Field(ge=1)
    slug: str | None = Field(
        default=None, min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*$"
    )
    name: str | None = Field(default=None, min_length=1, max_length=100)
    status: AssistantStatus | None = None


class ConnectionInput(BaseModel):
    assistant_id: UUID
    platform: str = Field(min_length=1, max_length=32)
    external_bot_id: str = Field(min_length=1, max_length=255)
    credential_reference: str | None = Field(default=None, max_length=255)


class ConnectionPatch(BaseModel):
    expected_revision: int = Field(ge=1)
    credential_reference: str | None = Field(default=None, max_length=255)
    status: PlatformConnectionStatus | None = None


class GroupPatch(BaseModel):
    settings: dict[str, Any]
    reason: str | None = Field(default=None, max_length=255)
    expected_revision: int = Field(ge=0)


class ReviewActionInput(BaseModel):
    action: ReviewAction
    reason: str | None = Field(default=None, max_length=255)


class ProtectionInput(BaseModel):
    participant_id: UUID
    protected: bool


@dataclass(frozen=True)
class Principal:
    identity: ControlOperatorIdentityModel
    claims: dict[str, Any]


def settings_for(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def request_id_for(request: Request) -> str:
    return cast(str, getattr(request.state, "request_id", "unknown"))


def telemetry_for(request: Request) -> MetricsRecorder:
    return cast(
        MetricsRecorder,
        getattr(request.app.state, "telemetry", NoOpMetricsRecorder()),
    )


async def _conversation_for_group(
    session: AsyncSession, tenant_id: UUID, group_id: UUID
) -> ConversationModel | None:
    """Resolve the runtime conversation bound to a control-plane group."""

    group = await session.scalar(
        select(ControlGroupBindingModel).where(
            ControlGroupBindingModel.id == group_id,
            ControlGroupBindingModel.tenant_id == tenant_id,
        )
    )
    if group is None:
        return None
    conversation: ConversationModel | None = await session.scalar(
        select(ConversationModel).where(
            ConversationModel.platform_connection_id == group.connection_id,
            ConversationModel.platform_conversation_id == group.external_group_id,
        )
    )
    return conversation


def _safety_repository(request: Request) -> SqlAlchemySafetyModerationRepository:
    database = cast(Database, request.app.state.database)
    return SqlAlchemySafetyModerationRepository(database.session_factory)


async def principal_for(
    request: Request,
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(database_session),
) -> Principal:
    settings = settings_for(request)
    if not settings.control_plane_enabled:
        raise HTTPException(status_code=404, detail="Not found")
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        claims = jwt.decode(
            token,
            settings.control_plane_jwt_secret.get_secret_value()
            if settings.control_plane_jwt_secret
            else "",
            algorithms=["HS256"],
            issuer=settings.control_plane_jwt_issuer,
            audience=settings.control_plane_jwt_audience,
            options={"require": ["iss", "sub", "aud", "exp"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Authentication required") from exc
    issuer = cast(str, claims["iss"])
    subject = cast(str, claims["sub"])
    identity = await session.scalar(
        select(ControlOperatorIdentityModel).where(
            ControlOperatorIdentityModel.issuer == issuer,
            ControlOperatorIdentityModel.subject == subject,
        )
    )
    if identity is None:
        await session.execute(
            insert(ControlOperatorIdentityModel)
            .values(
                id=uuid4(),
                issuer=issuer,
                subject=subject,
                display_name=claims.get("name"),
                email=claims.get("email"),
            )
            .on_conflict_do_nothing(index_elements=["issuer", "subject"])
        )
        await session.commit()
        identity = await session.scalar(
            select(ControlOperatorIdentityModel).where(
                ControlOperatorIdentityModel.issuer == issuer,
                ControlOperatorIdentityModel.subject == subject,
            )
        )
        if identity is None:
            raise HTTPException(status_code=503, detail="Identity unavailable")
    if identity.disabled_at is not None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return Principal(identity=identity, claims=claims)


async def membership_for(
    session: AsyncSession, principal: Principal, tenant_id: UUID
) -> ControlOperatorMembershipModel:
    membership = await session.scalar(
        select(ControlOperatorMembershipModel).where(
            ControlOperatorMembershipModel.tenant_id == tenant_id,
            ControlOperatorMembershipModel.identity_id == principal.identity.id,
            ControlOperatorMembershipModel.disabled_at.is_(None),
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Not found")
    return membership


def require_resource_read(membership: ControlOperatorMembershipModel) -> None:
    if membership.role not in RESOURCE_READ_ROLES:
        raise HTTPException(status_code=403, detail="Forbidden")


async def audit(
    session: AsyncSession,
    request: Request,
    tenant_id: UUID | None,
    principal: Principal,
    action: str,
    outcome: str,
    resource_type: str,
    resource_id: UUID | None = None,
    schema_version: str = "spec-021-v1",
) -> None:
    session.add(
        ControlAuditEventModel(
            tenant_id=tenant_id,
            actor_identity_id=principal.identity.id,
            action=action,
            outcome=outcome,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            request_id=request_id_for(request),
            metadata_={"schema_version": schema_version},
        )
    )


def tenant_body(tenant: ControlTenantModel) -> dict[str, Any]:
    return {
        "id": str(tenant.id),
        "slug": tenant.slug,
        "name": tenant.name,
        "status": tenant.status.value,
        "revision": tenant.revision,
    }


def assistant_body(assistant: AssistantModel) -> dict[str, Any]:
    return {
        "id": str(assistant.id),
        "tenant_id": str(assistant.tenant_id),
        "slug": assistant.slug,
        "name": assistant.name,
        "status": assistant.status.value,
        "revision": assistant.revision,
        "knowledge_enabled": assistant.knowledge_enabled,
    }


def connection_body(connection: PlatformConnectionModel) -> dict[str, Any]:
    return {
        "id": str(connection.id),
        "tenant_id": str(connection.tenant_id),
        "assistant_id": str(connection.assistant_id),
        "platform": connection.platform.value,
        "external_bot_id": connection.external_bot_id,
        "status": connection.status.value,
        "revision": connection.revision,
        "credential_configured": connection.credential_reference is not None,
    }


def create_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/control/v1", tags=["control-plane"])

    @router.get("/session")
    async def session_info(
        request: Request, principal: Principal = Depends(principal_for)
    ) -> dict[str, Any]:
        return {
            "authenticated": True,
            "issuer": principal.identity.issuer,
            "subject": principal.identity.subject,
        }

    @router.post("/session/logout", status_code=status.HTTP_204_NO_CONTENT)
    async def logout(_: Principal = Depends(principal_for)) -> None:
        return None

    @router.get("/me")
    async def me(
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        memberships = (
            await session.scalars(
                select(ControlOperatorMembershipModel).where(
                    ControlOperatorMembershipModel.identity_id == principal.identity.id,
                    ControlOperatorMembershipModel.disabled_at.is_(None),
                )
            )
        ).all()
        return {
            "identity_id": str(principal.identity.id),
            "issuer": principal.identity.issuer,
            "subject": principal.identity.subject,
            "display_name": principal.identity.display_name,
            "email": principal.identity.email,
            "memberships": [
                {"tenant_id": str(item.tenant_id), "role": item.role}
                for item in memberships
            ],
            "deployment_operator": await has_deployment_authority(
                session, principal.identity.id
            ),
        }

    @router.put("/deployment/authorities/{identity_id}")
    async def grant_deployment_authority(
        identity_id: UUID,
        request: Request,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        authorized = await has_deployment_authority(session, principal.identity.id)
        bootstrap_candidate = (
            principal.identity.id == identity_id
            and principal.identity.subject
            in settings.control_plane_deployment_bootstrap_subjects
        )
        if not (authorized or bootstrap_candidate):
            await audit(
                session,
                request,
                None,
                principal,
                "deployment_authority.grant",
                "denied",
                "deployment_authority",
                identity_id,
                "spec-025-v1",
            )
            await session.commit()
            raise HTTPException(status_code=403, detail="Forbidden")
        await session.commit()
        database = cast(Database, request.app.state.database)
        repository = SqlAlchemyDeploymentAuthorityRepository(database.session_factory)
        try:
            if authorized:
                result = await repository.grant(
                    identity_id=identity_id,
                    actor_identity_id=principal.identity.id,
                    request_id=request_id_for(request),
                )
            else:
                result = await repository.bootstrap_self_grant(
                    identity_id=identity_id,
                    request_id=request_id_for(request),
                )
        except PermissionError as exc:
            async with database.session_factory() as denied_session:
                await audit(
                    denied_session,
                    request,
                    None,
                    principal,
                    "deployment_authority.grant",
                    "denied",
                    "deployment_authority",
                    identity_id,
                    "spec-025-v1",
                )
                await denied_session.commit()
            raise HTTPException(status_code=403, detail="Forbidden") from exc
        except DeploymentAuthorityIdempotencyConflict as exc:
            async with database.session_factory() as failed_session:
                await audit(
                    failed_session,
                    request,
                    None,
                    principal,
                    "deployment_authority.grant",
                    "failed",
                    "deployment_authority",
                    identity_id,
                    "spec-025-v1",
                )
                await failed_session.commit()
            raise HTTPException(status_code=409, detail="Request ID conflict") from exc
        except ValueError as exc:
            async with database.session_factory() as failed_session:
                await audit(
                    failed_session,
                    request,
                    None,
                    principal,
                    "deployment_authority.grant",
                    "failed",
                    "deployment_authority",
                    identity_id,
                    "spec-025-v1",
                )
                await failed_session.commit()
            raise HTTPException(status_code=404, detail="Not found") from exc
        return {
            "identity_id": str(result.identity_id),
            "authority": "deployment_operator",
            "active": result.active,
            "changed": result.changed,
        }

    @router.delete("/deployment/authorities/{identity_id}", status_code=204)
    async def revoke_deployment_authority(
        identity_id: UUID,
        request: Request,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> None:
        if not await has_deployment_authority(session, principal.identity.id):
            await audit(
                session,
                request,
                None,
                principal,
                "deployment_authority.revoke",
                "denied",
                "deployment_authority",
                identity_id,
                "spec-025-v1",
            )
            await session.commit()
            raise HTTPException(status_code=403, detail="Forbidden")
        database = cast(Database, request.app.state.database)
        try:
            await SqlAlchemyDeploymentAuthorityRepository(
                database.session_factory
            ).revoke(
                identity_id=identity_id,
                actor_identity_id=principal.identity.id,
                request_id=request_id_for(request),
            )
        except DeploymentAuthorityIdempotencyConflict as exc:
            async with database.session_factory() as failed_session:
                await audit(
                    failed_session,
                    request,
                    None,
                    principal,
                    "deployment_authority.revoke",
                    "failed",
                    "deployment_authority",
                    identity_id,
                    "spec-025-v1",
                )
                await failed_session.commit()
            raise HTTPException(status_code=409, detail="Request ID conflict") from exc

    @router.post("/governance/deployment/export")
    async def deployment_export(
        request: Request,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> JSONResponse:
        if not settings.data_governance_enabled:
            raise HTTPException(status_code=404, detail="Not found")
        if not await has_deployment_authority(session, principal.identity.id):
            await audit(
                session,
                request,
                None,
                principal,
                "governance.deployment_export",
                "denied",
                "deployment_export",
                schema_version="spec-025-v1",
            )
            await session.commit()
            raise HTTPException(status_code=403, detail="Forbidden")
        await session.commit()
        database = cast(Database, request.app.state.database)
        governance = SqlAlchemyGovernanceRepository(database.session_factory)
        try:
            export = await governance.create_export_request(
                scope=GovernanceScope.DEPLOYMENT,
                conversation_id=None,
                participant_id=None,
                tenant_id=None,
                token_hash=None,
                categories=DEPLOYMENT_EXPORT_CATEGORIES,
                ttl_days=settings.governance_export_ttl_days,
                source_control_identity_id=principal.identity.id,
                source_control_request_id=request_id_for(request),
            )
        except Exception as exc:
            telemetry_for(request).increment(
                "january_governance_export_requests_total",
                scope="deployment",
                outcome="failed",
            )
            raise HTTPException(status_code=503, detail="Export unavailable") from exc
        if export.created:
            telemetry_for(request).increment(
                "january_governance_export_requests_total",
                scope="deployment",
                outcome="requested",
            )
        if export.single_use_token_hash is not None:
            raise HTTPException(status_code=409, detail="Export already issued")
        if export.status in {"requested", "in_progress"}:
            return JSONResponse(
                status_code=status.HTTP_202_ACCEPTED,
                content={
                    "request_id": str(export.id),
                    "schema_version": GOVERNANCE_EXPORT_SCHEMA_VERSION,
                    "status": export.status,
                    "expires_at": export.expires_at.isoformat()
                    if export.expires_at is not None
                    else None,
                },
                headers={"Cache-Control": "no-store", "Retry-After": "1"},
            )
        if export.status not in {"complete", "delivered"}:
            raise HTTPException(status_code=409, detail="Export is unavailable")
        credential = secrets.token_urlsafe(32)
        if not await governance.issue_export_token(
            export.id,
            hashlib.sha256(credential.encode("ascii")).hexdigest(),
            control_actor_identity_id=principal.identity.id,
            control_request_id=request_id_for(request),
        ):
            raise HTTPException(status_code=409, detail="Export is unavailable")
        return JSONResponse(
            content={
                "request_id": str(export.id),
                "schema_version": GOVERNANCE_EXPORT_SCHEMA_VERSION,
                "retrieval_credential": credential,
                "expires_at": export.expires_at.isoformat()
                if export.expires_at is not None
                else None,
            },
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/tenants")
    async def list_tenants(
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        rows = await session.execute(
            select(ControlTenantModel, ControlOperatorMembershipModel.role)
            .join(
                ControlOperatorMembershipModel,
                ControlOperatorMembershipModel.tenant_id == ControlTenantModel.id,
            )
            .where(
                ControlOperatorMembershipModel.identity_id == principal.identity.id,
                ControlOperatorMembershipModel.disabled_at.is_(None),
            )
        )
        return {
            "items": [
                {**tenant_body(tenant), "role": role} for tenant, role in rows.all()
            ]
        }

    @router.post("/tenants", status_code=201)
    async def create_tenant(
        payload: TenantInput,
        request: Request,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        if not await has_deployment_authority(session, principal.identity.id):
            raise HTTPException(status_code=403, detail="Forbidden")
        tenant = ControlTenantModel(
            slug=payload.slug,
            name=payload.name,
            status=TenantStatus.ACTIVE,
            revision=1,
        )
        session.add(tenant)
        try:
            await session.flush()
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(
                status_code=409, detail="Tenant slug already exists"
            ) from exc
        session.add(
            ControlOperatorMembershipModel(
                tenant_id=tenant.id,
                identity_id=principal.identity.id,
                role="tenant_owner",
            )
        )
        await audit(
            session,
            request,
            tenant.id,
            principal,
            "tenant.create",
            "success",
            "tenant",
            tenant.id,
        )
        await session.commit()
        return tenant_body(tenant)

    @router.get("/tenants/{tenant_id}")
    async def get_tenant(
        tenant_id: UUID,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        await membership_for(session, principal, tenant_id)
        tenant = await session.get(ControlTenantModel, tenant_id)
        if tenant is None:
            raise HTTPException(status_code=404, detail="Not found")
        return tenant_body(tenant)

    @router.patch("/tenants/{tenant_id}")
    async def update_tenant(
        tenant_id: UUID,
        payload: TenantPatch,
        request: Request,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        member = await membership_for(session, principal, tenant_id)
        if member.role not in ADMIN_ROLES:
            raise HTTPException(status_code=403, detail="Forbidden")
        if payload.status is not None and member.role != "tenant_owner":
            raise HTTPException(status_code=403, detail="Forbidden")
        tenant = await session.scalar(
            select(ControlTenantModel)
            .where(ControlTenantModel.id == tenant_id)
            .with_for_update()
        )
        if tenant is None:
            raise HTTPException(status_code=404, detail="Not found")
        if tenant.revision != payload.expected_revision:
            raise HTTPException(status_code=409, detail="Revision conflict")
        if payload.name is None and payload.status is None:
            raise HTTPException(status_code=422, detail="No mutation requested")
        if tenant.status == TenantStatus.RETIRED:
            raise HTTPException(status_code=409, detail="Retired tenant is immutable")
        if payload.status is not None and not tenant_transition_allowed(
            tenant.status, payload.status
        ):
            raise HTTPException(status_code=409, detail="Retired tenant is immutable")
        if payload.name is not None:
            tenant.name = payload.name
        if payload.status is not None:
            tenant.status = payload.status
        tenant.revision += 1
        await audit(
            session,
            request,
            tenant_id,
            principal,
            "tenant.update",
            "success",
            "tenant",
            tenant.id,
            schema_version="spec-030-v1",
        )
        await session.commit()
        return tenant_body(tenant)

    @router.get("/tenants/{tenant_id}/members")
    async def list_members(
        tenant_id: UUID,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        member = await membership_for(session, principal, tenant_id)
        require_resource_read(member)
        rows = await session.execute(
            select(ControlOperatorMembershipModel, ControlOperatorIdentityModel)
            .join(
                ControlOperatorIdentityModel,
                ControlOperatorIdentityModel.id
                == ControlOperatorMembershipModel.identity_id,
            )
            .where(
                ControlOperatorMembershipModel.tenant_id == tenant_id,
                ControlOperatorMembershipModel.disabled_at.is_(None),
            )
        )
        return {
            "items": [
                {
                    "id": str(identity.id),
                    "issuer": identity.issuer,
                    "subject": identity.subject,
                    "display_name": identity.display_name,
                    "email": identity.email,
                    "role": membership.role,
                }
                for membership, identity in rows.all()
            ]
        }

    @router.post("/tenants/{tenant_id}/members", status_code=201)
    async def add_member(
        tenant_id: UUID,
        payload: MembershipInput,
        request: Request,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        actor = await membership_for(session, principal, tenant_id)
        if actor.role not in ADMIN_ROLES or (
            payload.role == "tenant_owner" and actor.role != "tenant_owner"
        ):
            raise HTTPException(status_code=403, detail="Forbidden")
        identity = await session.scalar(
            select(ControlOperatorIdentityModel).where(
                ControlOperatorIdentityModel.issuer == payload.issuer,
                ControlOperatorIdentityModel.subject == payload.subject,
            )
        )
        if identity is None:
            identity = ControlOperatorIdentityModel(
                issuer=payload.issuer,
                subject=payload.subject,
                display_name=payload.display_name,
                email=payload.email,
            )
            session.add(identity)
            await session.flush()
        member = ControlOperatorMembershipModel(
            tenant_id=tenant_id, identity_id=identity.id, role=payload.role
        )
        session.add(member)
        await audit(
            session,
            request,
            tenant_id,
            principal,
            "member.add",
            "success",
            "membership",
            identity.id,
        )
        await session.commit()
        return {
            "id": str(identity.id),
            "issuer": identity.issuer,
            "subject": identity.subject,
            "role": member.role,
        }

    @router.delete("/tenants/{tenant_id}/members/{identity_id}", status_code=204)
    async def remove_member(
        tenant_id: UUID,
        identity_id: UUID,
        request: Request,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> None:
        actor = await membership_for(session, principal, tenant_id)
        if actor.role not in ADMIN_ROLES:
            raise HTTPException(status_code=403, detail="Forbidden")
        member = await session.scalar(
            select(ControlOperatorMembershipModel).where(
                ControlOperatorMembershipModel.tenant_id == tenant_id,
                ControlOperatorMembershipModel.identity_id == identity_id,
                ControlOperatorMembershipModel.disabled_at.is_(None),
            )
        )
        if member is None:
            raise HTTPException(status_code=404, detail="Not found")
        if member.role == "tenant_owner":
            owners = await session.scalar(
                select(func.count())
                .select_from(ControlOperatorMembershipModel)
                .where(
                    ControlOperatorMembershipModel.tenant_id == tenant_id,
                    ControlOperatorMembershipModel.role == "tenant_owner",
                    ControlOperatorMembershipModel.disabled_at.is_(None),
                )
            )
            if owners == 1:
                raise HTTPException(
                    status_code=409, detail="Last owner cannot be removed"
                )
        member.disabled_at = datetime.now(UTC)
        await audit(
            session,
            request,
            tenant_id,
            principal,
            "member.remove",
            "success",
            "membership",
            identity_id,
        )
        await session.commit()

    @router.get("/tenants/{tenant_id}/assistants")
    async def list_assistants(
        tenant_id: UUID,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        member = await membership_for(session, principal, tenant_id)
        require_resource_read(member)
        assistants = (
            await session.scalars(
                select(AssistantModel).where(AssistantModel.tenant_id == tenant_id)
            )
        ).all()
        return {"items": [assistant_body(assistant) for assistant in assistants]}

    @router.get("/tenants/{tenant_id}/assistants/{assistant_id}")
    async def get_assistant(
        tenant_id: UUID,
        assistant_id: UUID,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        member = await membership_for(session, principal, tenant_id)
        require_resource_read(member)
        assistant = await assistant_for_tenant(session, tenant_id, assistant_id)
        if assistant is None:
            raise HTTPException(status_code=404, detail="Not found")
        return assistant_body(assistant)

    @router.post("/tenants/{tenant_id}/assistants", status_code=201)
    async def create_assistant(
        tenant_id: UUID,
        payload: AssistantInput,
        request: Request,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        member = await membership_for(session, principal, tenant_id)
        if member.role not in WRITE_ROLES:
            raise HTTPException(status_code=403, detail="Forbidden")
        tenant = await session.get(ControlTenantModel, tenant_id)
        if tenant is None:
            raise HTTPException(status_code=404, detail="Not found")
        if tenant.status == TenantStatus.RETIRED:
            raise HTTPException(status_code=409, detail="Retired tenant is immutable")
        assistant = AssistantModel(
            tenant_id=tenant_id,
            slug=payload.slug,
            name=payload.name,
            status=AssistantStatus.DISABLED,
            revision=1,
        )
        session.add(assistant)
        try:
            await session.flush()
            await ensure_assistant_default(session, assistant)
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(
                status_code=409, detail="Assistant slug already exists"
            ) from exc
        session.add(
            ControlAssistantBindingModel(tenant_id=tenant_id, assistant_id=assistant.id)
        )
        await audit(
            session,
            request,
            tenant_id,
            principal,
            "assistant.create",
            "success",
            "assistant",
            assistant.id,
            schema_version="spec-030-v1",
        )
        await session.commit()
        return assistant_body(assistant)

    @router.patch("/tenants/{tenant_id}/assistants/{assistant_id}")
    async def update_assistant(
        tenant_id: UUID,
        assistant_id: UUID,
        payload: AssistantPatch,
        request: Request,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        member = await membership_for(session, principal, tenant_id)
        if member.role not in WRITE_ROLES:
            raise HTTPException(status_code=403, detail="Forbidden")
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
        if assistant.revision != payload.expected_revision:
            raise HTTPException(status_code=409, detail="Revision conflict")
        if payload.slug is None and payload.name is None and payload.status is None:
            raise HTTPException(status_code=422, detail="No mutation requested")
        if assistant.status == AssistantStatus.RETIRED:
            raise HTTPException(
                status_code=409, detail="Retired assistant is immutable"
            )
        if payload.status is not None and not assistant_transition_allowed(
            assistant.status, payload.status
        ):
            raise HTTPException(
                status_code=409, detail="Retired assistant is immutable"
            )
        if payload.status == AssistantStatus.ACTIVE:
            tenant = await session.get(ControlTenantModel, tenant_id)
            if tenant is None or tenant.status != TenantStatus.ACTIVE:
                raise HTTPException(status_code=409, detail="Tenant is not active")
            await ensure_assistant_default(session, assistant)
        if payload.slug is not None:
            assistant.slug = payload.slug
        if payload.name is not None:
            assistant.name = payload.name
        if payload.status is not None:
            assistant.status = payload.status
        assistant.revision += 1
        await audit(
            session,
            request,
            tenant_id,
            principal,
            "assistant.update",
            "success",
            "assistant",
            assistant.id,
            schema_version="spec-030-v1",
        )
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(
                status_code=409, detail="Assistant slug already exists"
            ) from exc
        return assistant_body(assistant)

    @router.get("/tenants/{tenant_id}/assistants/{assistant_id}/status")
    async def assistant_status(
        tenant_id: UUID,
        assistant_id: UUID,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        member = await membership_for(session, principal, tenant_id)
        require_resource_read(member)
        assistant = await assistant_for_tenant(session, tenant_id, assistant_id)
        if assistant is None:
            raise HTTPException(status_code=404, detail="Not found")
        return {
            "assistant_id": str(assistant.id),
            "status": assistant.status.value,
            "revision": assistant.revision,
        }

    @router.delete("/tenants/{tenant_id}/assistants/{assistant_id}", status_code=204)
    async def disable_assistant(
        tenant_id: UUID,
        assistant_id: UUID,
        request: Request,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> None:
        member = await membership_for(session, principal, tenant_id)
        if member.role not in ADMIN_ROLES:
            raise HTTPException(status_code=403, detail="Forbidden")
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
        if assistant.status == AssistantStatus.RETIRED:
            raise HTTPException(
                status_code=409, detail="Retired assistant is immutable"
            )
        assistant.status = AssistantStatus.DISABLED
        assistant.revision += 1
        await audit(
            session,
            request,
            tenant_id,
            principal,
            "assistant.disable",
            "success",
            "assistant",
            assistant.id,
            schema_version="spec-030-v1",
        )
        await session.commit()

    @router.delete("/tenants/{tenant_id}/connections/{connection_id}", status_code=204)
    async def disable_connection(
        tenant_id: UUID,
        connection_id: UUID,
        request: Request,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> None:
        member = await membership_for(session, principal, tenant_id)
        if member.role not in ADMIN_ROLES:
            raise HTTPException(status_code=403, detail="Forbidden")
        connection = await session.scalar(
            select(PlatformConnectionModel)
            .where(
                PlatformConnectionModel.id == connection_id,
                PlatformConnectionModel.tenant_id == tenant_id,
            )
            .with_for_update()
        )
        if connection is None:
            raise HTTPException(status_code=404, detail="Not found")
        if connection.status == PlatformConnectionStatus.RETIRED:
            raise HTTPException(
                status_code=409, detail="Retired connection is immutable"
            )
        connection.status = PlatformConnectionStatus.DISABLED
        connection.revision += 1
        await audit(
            session,
            request,
            tenant_id,
            principal,
            "connection.disable",
            "success",
            "connection",
            connection.id,
            schema_version="spec-030-v1",
        )
        await session.commit()

    @router.get("/tenants/{tenant_id}/connections")
    async def list_connections(
        tenant_id: UUID,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        member = await membership_for(session, principal, tenant_id)
        require_resource_read(member)
        connections = (
            await session.scalars(
                select(PlatformConnectionModel).where(
                    PlatformConnectionModel.tenant_id == tenant_id
                )
            )
        ).all()
        return {"items": [connection_body(connection) for connection in connections]}

    @router.get("/tenants/{tenant_id}/connections/{connection_id}")
    async def get_connection(
        tenant_id: UUID,
        connection_id: UUID,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        member = await membership_for(session, principal, tenant_id)
        require_resource_read(member)
        connection = await connection_for_tenant(session, tenant_id, connection_id)
        if connection is None:
            raise HTTPException(status_code=404, detail="Not found")
        return connection_body(connection)

    @router.post("/tenants/{tenant_id}/connections", status_code=201)
    async def create_connection(
        tenant_id: UUID,
        payload: ConnectionInput,
        request: Request,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        member = await membership_for(session, principal, tenant_id)
        if member.role not in WRITE_ROLES:
            raise HTTPException(status_code=403, detail="Forbidden")
        tenant = await session.get(ControlTenantModel, tenant_id)
        assistant = await assistant_for_tenant(session, tenant_id, payload.assistant_id)
        if tenant is None or assistant is None:
            raise HTTPException(status_code=404, detail="Not found")
        if (
            tenant.status == TenantStatus.RETIRED
            or assistant.status == AssistantStatus.RETIRED
        ):
            raise HTTPException(status_code=409, detail="Retired resource is immutable")
        try:
            platform = Platform(payload.platform)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid platform") from exc
        connection = PlatformConnectionModel(
            tenant_id=tenant_id,
            assistant_id=payload.assistant_id,
            platform=platform,
            external_bot_id=payload.external_bot_id,
            status=PlatformConnectionStatus.DISABLED,
            revision=1,
            credential_reference=payload.credential_reference,
        )
        session.add(connection)
        try:
            await session.flush()
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(
                status_code=409, detail="Platform connection already exists"
            ) from exc
        session.add(
            ControlConnectionBindingModel(
                tenant_id=tenant_id, connection_id=connection.id
            )
        )
        await audit(
            session,
            request,
            tenant_id,
            principal,
            "connection.create",
            "success",
            "connection",
            connection.id,
            schema_version="spec-030-v1",
        )
        await session.commit()
        return connection_body(connection)

    @router.patch("/tenants/{tenant_id}/connections/{connection_id}")
    async def update_connection(
        tenant_id: UUID,
        connection_id: UUID,
        payload: ConnectionPatch,
        request: Request,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        member = await membership_for(session, principal, tenant_id)
        if member.role not in WRITE_ROLES:
            raise HTTPException(status_code=403, detail="Forbidden")
        connection = await session.scalar(
            select(PlatformConnectionModel)
            .where(
                PlatformConnectionModel.id == connection_id,
                PlatformConnectionModel.tenant_id == tenant_id,
            )
            .with_for_update()
        )
        if connection is None:
            raise HTTPException(status_code=404, detail="Not found")
        if connection.revision != payload.expected_revision:
            raise HTTPException(status_code=409, detail="Revision conflict")
        if payload.credential_reference is None and payload.status is None:
            raise HTTPException(status_code=422, detail="No mutation requested")
        if connection.status == PlatformConnectionStatus.RETIRED:
            raise HTTPException(
                status_code=409, detail="Retired connection is immutable"
            )
        if payload.status is not None and not connection_transition_allowed(
            connection.status, payload.status
        ):
            raise HTTPException(
                status_code=409, detail="Retired connection is immutable"
            )
        if payload.status == PlatformConnectionStatus.ACTIVE:
            assistant = await assistant_for_tenant(
                session, tenant_id, connection.assistant_id
            )
            tenant = await session.get(ControlTenantModel, tenant_id)
            if (
                tenant is None
                or tenant.status != TenantStatus.ACTIVE
                or assistant is None
                or assistant.status != AssistantStatus.ACTIVE
            ):
                raise HTTPException(
                    status_code=409, detail="Parent resource is not active"
                )
        if payload.credential_reference is not None:
            connection.credential_reference = payload.credential_reference
        if payload.status is not None:
            connection.status = payload.status
        connection.revision += 1
        await audit(
            session,
            request,
            tenant_id,
            principal,
            "connection.update",
            "success",
            "connection",
            connection.id,
            schema_version="spec-030-v1",
        )
        await session.commit()
        return connection_body(connection)

    @router.post("/tenants/{tenant_id}/connections/{connection_id}/rotate")
    async def rotate_connection(
        tenant_id: UUID,
        connection_id: UUID,
        request: Request,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        member = await membership_for(session, principal, tenant_id)
        if member.role not in ADMIN_ROLES:
            raise HTTPException(status_code=403, detail="Forbidden")
        connection = await connection_for_tenant(session, tenant_id, connection_id)
        if connection is None:
            raise HTTPException(status_code=404, detail="Not found")
        if connection.status == PlatformConnectionStatus.RETIRED:
            raise HTTPException(
                status_code=409, detail="Retired connection is immutable"
            )
        await audit(
            session,
            request,
            tenant_id,
            principal,
            "connection.rotate",
            "pending",
            "connection",
            connection.id,
        )
        await session.commit()
        return {"operation": "pending", "connection_id": str(connection.id)}

    @router.get("/tenants/{tenant_id}/connections/{connection_id}/status")
    async def connection_status(
        tenant_id: UUID,
        connection_id: UUID,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        member = await membership_for(session, principal, tenant_id)
        require_resource_read(member)
        connection = await connection_for_tenant(session, tenant_id, connection_id)
        if connection is None:
            raise HTTPException(status_code=404, detail="Not found")
        return {
            "connection_id": str(connection.id),
            "status": connection.status.value,
            "revision": connection.revision,
        }

    @router.post("/tenants/{tenant_id}/groups/{group_id}/restore/{revision}")
    async def restore_group(
        tenant_id: UUID,
        group_id: UUID,
        revision: int,
        request: Request,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        member = await membership_for(session, principal, tenant_id)
        if member.role not in WRITE_ROLES:
            raise HTTPException(status_code=403, detail="Forbidden")
        group = await session.scalar(
            select(ControlGroupBindingModel).where(
                ControlGroupBindingModel.id == group_id,
                ControlGroupBindingModel.tenant_id == tenant_id,
            )
        )
        source = await session.scalar(
            select(ControlGroupRevisionModel).where(
                ControlGroupRevisionModel.group_id == group_id,
                ControlGroupRevisionModel.revision == revision,
            )
        )
        if group is None or source is None:
            raise HTTPException(status_code=404, detail="Not found")
        next_revision = group.current_revision + 1
        session.add(
            ControlGroupRevisionModel(
                group_id=group.id,
                revision=next_revision,
                parent_revision=group.current_revision or None,
                settings=source.settings,
                actor_identity_id=principal.identity.id,
                reason=f"restore:{revision}",
            )
        )
        group.settings = source.settings
        group.current_revision = next_revision
        await audit(
            session,
            request,
            tenant_id,
            principal,
            "group.configuration.restore",
            "success",
            "group",
            group.id,
        )
        await session.commit()
        return {
            "id": str(group.id),
            "revision": next_revision,
            "settings": group.settings,
        }

    @router.get("/tenants/{tenant_id}/groups/{group_id}/revisions")
    async def group_revisions(
        tenant_id: UUID,
        group_id: UUID,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        member = await membership_for(session, principal, tenant_id)
        require_resource_read(member)
        group = await session.scalar(
            select(ControlGroupBindingModel).where(
                ControlGroupBindingModel.id == group_id,
                ControlGroupBindingModel.tenant_id == tenant_id,
            )
        )
        if group is None:
            raise HTTPException(status_code=404, detail="Not found")
        revisions = (
            await session.scalars(
                select(ControlGroupRevisionModel)
                .where(ControlGroupRevisionModel.group_id == group_id)
                .order_by(ControlGroupRevisionModel.revision.desc())
            )
        ).all()
        return {
            "items": [
                {
                    "id": str(item.id),
                    "revision": item.revision,
                    "parent_revision": item.parent_revision,
                    "settings": item.settings,
                    "reason": item.reason,
                }
                for item in revisions
            ]
        }

    @router.get("/tenants/{tenant_id}/groups")
    async def list_groups(
        tenant_id: UUID,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        member = await membership_for(session, principal, tenant_id)
        require_resource_read(member)
        groups = (
            await session.scalars(
                select(ControlGroupBindingModel).where(
                    ControlGroupBindingModel.tenant_id == tenant_id
                )
            )
        ).all()
        return {
            "items": [
                {
                    "id": str(group.id),
                    "connection_id": str(group.connection_id),
                    "external_group_id": group.external_group_id,
                    "title": group.title,
                    "revision": group.current_revision,
                    "settings": group.settings,
                }
                for group in groups
            ]
        }

    @router.get("/tenants/{tenant_id}/groups/{group_id}")
    async def get_group(
        tenant_id: UUID,
        group_id: UUID,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        member = await membership_for(session, principal, tenant_id)
        require_resource_read(member)
        group = await session.scalar(
            select(ControlGroupBindingModel).where(
                ControlGroupBindingModel.id == group_id,
                ControlGroupBindingModel.tenant_id == tenant_id,
            )
        )
        if group is None:
            raise HTTPException(status_code=404, detail="Not found")
        return {
            "id": str(group.id),
            "connection_id": str(group.connection_id),
            "external_group_id": group.external_group_id,
            "title": group.title,
            "revision": group.current_revision,
            "settings": group.settings,
        }

    @router.patch("/tenants/{tenant_id}/groups/{group_id}")
    async def update_group(
        tenant_id: UUID,
        group_id: UUID,
        payload: GroupPatch,
        request: Request,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        member = await membership_for(session, principal, tenant_id)
        if member.role not in WRITE_ROLES:
            raise HTTPException(status_code=403, detail="Forbidden")
        group = await session.scalar(
            select(ControlGroupBindingModel).where(
                ControlGroupBindingModel.id == group_id,
                ControlGroupBindingModel.tenant_id == tenant_id,
            )
        )
        if group is None:
            raise HTTPException(status_code=404, detail="Not found")
        if payload.expected_revision != group.current_revision:
            raise HTTPException(status_code=409, detail="Revision conflict")
        revision = group.current_revision + 1
        session.add(
            ControlGroupRevisionModel(
                group_id=group.id,
                revision=revision,
                parent_revision=group.current_revision or None,
                settings=payload.settings,
                actor_identity_id=principal.identity.id,
                reason=payload.reason,
            )
        )
        group.settings = payload.settings
        group.current_revision = revision
        await audit(
            session,
            request,
            tenant_id,
            principal,
            "group.configuration.update",
            "success",
            "group",
            group.id,
        )
        await session.commit()
        return {"id": str(group.id), "revision": revision, "settings": group.settings}

    @router.get("/tenants/{tenant_id}/groups/{group_id}/safety/aggregates")
    async def safety_aggregates(
        tenant_id: UUID,
        group_id: UUID,
        request: Request,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        member = await membership_for(session, principal, tenant_id)
        require_resource_read(member)
        conversation = await _conversation_for_group(session, tenant_id, group_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Not found")
        repository = _safety_repository(request)
        from app.application.safety import SafetyModerationService, signal_counts_view

        service = SafetyModerationService(settings_for(request), repository)
        signals = await service.aggregate(
            conversation_id=conversation.id,
            participant_id=None,
        )
        return signal_counts_view(signals)

    @router.get("/tenants/{tenant_id}/groups/{group_id}/safety/review-items")
    async def safety_review_items(
        tenant_id: UUID,
        group_id: UUID,
        request: Request,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        member = await membership_for(session, principal, tenant_id)
        require_resource_read(member)
        conversation = await _conversation_for_group(session, tenant_id, group_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Not found")
        repository = _safety_repository(request)
        items = await repository.list_review_items(conversation_id=conversation.id)
        return {
            "items": [
                {
                    "id": str(item.item_id),
                    "category": item.category.value,
                    "stage": item.stage,
                    "status": item.status.value,
                    "outcome_counts": item.outcome_counts,
                    "protection_state": item.protection_state,
                    "created_at": item.created_at.isoformat(),
                }
                for item in items
            ]
        }

    @router.post(
        "/tenants/{tenant_id}/groups/{group_id}/safety/review-items/{item_id}/actions"
    )
    async def safety_review_action(
        tenant_id: UUID,
        group_id: UUID,
        item_id: UUID,
        payload: ReviewActionInput,
        request: Request,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        member = await membership_for(session, principal, tenant_id)
        if member.role not in WRITE_ROLES:
            raise HTTPException(status_code=403, detail="Forbidden")
        conversation = await _conversation_for_group(session, tenant_id, group_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Not found")
        item = await session.scalar(
            select(SafetyReviewItemModel).where(
                SafetyReviewItemModel.id == item_id,
                SafetyReviewItemModel.conversation_id == conversation.id,
            )
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Not found")
        repository = _safety_repository(request)
        changed = await repository.apply_review_action(
            item_id=item_id,
            action=payload.action,
            actor_participant_id=None,
            source=f"control_plane:{payload.action.value}",
        )
        await audit(
            session,
            request,
            tenant_id,
            principal,
            "safety.review.action",
            "success" if changed else "unchanged",
            "safety_review_item",
            item_id,
        )
        await session.commit()
        return {"item_id": str(item_id), "changed": changed}

    @router.post("/tenants/{tenant_id}/groups/{group_id}/safety/protection")
    async def safety_protection(
        tenant_id: UUID,
        group_id: UUID,
        payload: ProtectionInput,
        request: Request,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        member = await membership_for(session, principal, tenant_id)
        if member.role not in WRITE_ROLES:
            raise HTTPException(status_code=403, detail="Forbidden")
        conversation = await _conversation_for_group(session, tenant_id, group_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Not found")
        participant = await session.scalar(
            select(ParticipantModel).where(
                ParticipantModel.id == payload.participant_id,
                ParticipantModel.conversation_id == conversation.id,
            )
        )
        if participant is None:
            raise HTTPException(status_code=404, detail="Not found")
        repository = _safety_repository(request)
        if payload.protected:
            await repository.protect(
                conversation_id=conversation.id,
                participant_id=participant.id,
                actor_participant_id=None,
                source="control_plane",
            )
        else:
            await repository.restore_targeting(
                conversation_id=conversation.id,
                participant_id=participant.id,
                actor_participant_id=None,
                source="control_plane",
            )
        await audit(
            session,
            request,
            tenant_id,
            principal,
            "safety.protection.set",
            "success",
            "participant",
            participant.id,
        )
        await session.commit()
        return {
            "participant_id": str(participant.id),
            "protected": payload.protected,
        }

    @router.get("/tenants/{tenant_id}/audit-events")
    async def audit_events(
        tenant_id: UUID,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        member = await membership_for(session, principal, tenant_id)
        if member.role not in ADMIN_ROLES | {"auditor"}:
            raise HTTPException(status_code=403, detail="Forbidden")
        events = (
            await session.scalars(
                select(ControlAuditEventModel)
                .where(ControlAuditEventModel.tenant_id == tenant_id)
                .order_by(ControlAuditEventModel.created_at.desc())
                .limit(100)
            )
        ).all()
        return {
            "items": [
                {
                    "id": str(event.id),
                    "action": event.action,
                    "outcome": event.outcome,
                    "resource_type": event.resource_type,
                    "resource_id": event.resource_id,
                    "request_id": event.request_id,
                    "metadata": event.metadata_,
                }
                for event in events
            ]
        }

    return router
