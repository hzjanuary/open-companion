"""Authenticated, content-safe SPEC-026 provider governance API."""

# FastAPI dependencies are intentionally declared at route boundaries.
# ruff: noqa: B008

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal, Never
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.provider_governance import ResolvedProviderRoute
from app.application.provider_governance import (
    capability_matches,
    validate_requirements,
)
from app.core.config import Settings
from app.domain.planning import ProviderId
from app.domain.provider_governance import (
    MAX_BIGINT,
    BudgetMeasurement,
    BudgetMode,
    BudgetScope,
    BudgetWindowKind,
    EstimateQuality,
    ProviderDataClass,
    ProviderHealth,
    ProviderLifecycle,
    WorkloadClass,
)
from app.infrastructure.database.deployment_authority import has_deployment_authority
from app.infrastructure.database.models import (
    ControlAuditEventModel,
    ProviderBudgetHeadModel,
    ProviderBudgetModel,
    ProviderBudgetRevisionModel,
    ProviderCapabilityModel,
    ProviderCapabilityStateModel,
    ProviderHealthEventModel,
    ProviderHealthPolicyRevisionModel,
    ProviderPriceRevisionModel,
    ProviderRoutingFallbackReasonModel,
    ProviderRoutingPolicyHeadModel,
    ProviderRoutingPolicyRevisionModel,
    ProviderRoutingPolicyRouteModel,
    ProviderUsageAttemptModel,
)
from app.infrastructure.database.tenancy import (
    assistant_for_tenant,
    connection_for_tenant,
)
from app.interface.http.control_plane import (
    ADMIN_ROLES,
    Principal,
    membership_for,
    principal_for,
    request_id_for,
    telemetry_for,
)
from app.interface.http.dependencies import database_session


class CapabilityInput(BaseModel):
    provider_id: ProviderId
    adapter_key: ProviderId
    workload_class: WorkloadClass
    model: str = Field(min_length=1, max_length=255)
    capability_metadata: dict[str, Any]
    data_class: ProviderDataClass
    credential_slot: Literal["openai", "gemini", "groq", "openrouter", "ollama"]
    credential_configured: bool
    reservation_strategy: Literal[
        "provider_tokenizer", "utf8_byte_upper_bound", "fixed_max", "request_count"
    ]

    @model_validator(mode="after")
    def safe_capability_contract(self) -> CapabilityInput:
        if self.provider_id != self.adapter_key:
            raise ValueError("provider must match the approved adapter")
        if self.credential_slot != self.adapter_key.value:
            raise ValueError("credential slot must match the approved adapter")
        allowed = {
            WorkloadClass.CHAT_GENERATION: {
                "json_schema",
                "json_object",
                "maximum_output_tokens",
                "image_input",
                "maximum_image_input_tokens",
            },
            WorkloadClass.EMBEDDING: {"embedding_dimension", "embedding_version"},
            WorkloadClass.TRANSCRIPTION: {
                "speech_to_text",
                "audio_formats",
                "maximum_audio_bytes",
                "maximum_audio_duration_seconds",
            },
            WorkloadClass.TEXT_TO_SPEECH: {
                "text_to_speech",
                "voice_format",
                "maximum_input_characters",
                "maximum_output_bytes",
            },
        }[self.workload_class]
        if set(self.capability_metadata) - allowed:
            raise ValueError("unknown capability metadata key")
        if self.workload_class == WorkloadClass.EMBEDDING:
            if self.adapter_key != ProviderId.OLLAMA:
                raise ValueError("only Ollama embedding is currently authorized")
            if self.data_class != ProviderDataClass.LOCAL:
                raise ValueError("Ollama embedding must retain the local data boundary")
            dimension = self.capability_metadata.get("embedding_dimension")
            version = self.capability_metadata.get("embedding_version")
            if (
                not isinstance(dimension, int)
                or isinstance(dimension, bool)
                or not 1 <= dimension <= 65_536
                or not isinstance(version, str)
                or not 1 <= len(version) <= 128
            ):
                raise ValueError("invalid embedding capability metadata")
        elif self.workload_class == WorkloadClass.TRANSCRIPTION:
            if self.adapter_key != ProviderId.GROQ:
                raise ValueError(
                    "only the existing Groq adapter supports transcription"
                )
            if self.capability_metadata.get("speech_to_text") is not True:
                raise ValueError("speech_to_text capability is required")
            formats = self.capability_metadata.get("audio_formats")
            if (
                not isinstance(formats, list)
                or not formats
                or len(formats) > 2
                or any(value not in ("audio/ogg", "audio/mpeg") for value in formats)
                or len(set(formats)) != len(formats)
            ):
                raise ValueError("invalid transcription audio formats")
            for key, cap in (
                ("maximum_audio_bytes", 10 * 1024 * 1024),
                ("maximum_audio_duration_seconds", 300),
            ):
                value = self.capability_metadata.get(key)
                if type(value) is not int or not 1 <= value <= cap:
                    raise ValueError("bounded transcription limits are required")
            if self.reservation_strategy not in {"fixed_max", "request_count"}:
                raise ValueError("transcription requires request-based reservation")
        elif self.workload_class == WorkloadClass.TEXT_TO_SPEECH:
            if self.adapter_key != ProviderId.OPENAI:
                raise ValueError("only the OpenAI adapter supports text to speech")
            if self.capability_metadata.get("text_to_speech") is not True:
                raise ValueError("text_to_speech capability is required")
            if self.capability_metadata.get("voice_format") != "ogg_opus":
                raise ValueError("native OGG/Opus capability is required")
            if self.capability_metadata.get("maximum_input_characters") != 4000:
                raise ValueError("TTS input capability must match the product bound")
            if self.capability_metadata.get("maximum_output_bytes") != 5 * 1024 * 1024:
                raise ValueError("TTS output capability must match the product bound")
            if self.reservation_strategy not in {"fixed_max", "request_count"}:
                raise ValueError("TTS requires request-based reservation")
        else:
            maximum = self.capability_metadata.get("maximum_output_tokens")
            if (
                not isinstance(maximum, int)
                or isinstance(maximum, bool)
                or not 1 <= maximum <= 1_000_000
            ):
                raise ValueError("generation maximum output tokens is required")
            for key in ("json_schema", "json_object", "image_input"):
                if key in self.capability_metadata and not isinstance(
                    self.capability_metadata[key], bool
                ):
                    raise ValueError("generation capability flags must be boolean")
            image_bound = self.capability_metadata.get("maximum_image_input_tokens")
            if self.capability_metadata.get("image_input") is True:
                if (
                    self.adapter_key
                    not in {
                        ProviderId.OPENAI,
                        ProviderId.GROQ,
                        ProviderId.OPENROUTER,
                    }
                    or type(image_bound) is not int
                    or not 1 <= image_bound <= 1_000_000
                ):
                    raise ValueError(
                        "image input requires an implemented adapter "
                        "and bounded reservation"
                    )
            elif image_bound is not None:
                raise ValueError("image reservation requires image input capability")
        return self


class CapabilityStateInput(BaseModel):
    lifecycle: ProviderLifecycle
    health: ProviderHealth | None = None
    health_policy_revision_id: UUID | None = None
    reason: Literal["administrative", "credential_status", "operating_owner"]


class HealthPolicyInput(BaseModel):
    capability_id: UUID
    observation_window_seconds: int = Field(ge=1, le=2_592_000)
    degraded_threshold: int = Field(ge=1, le=10_000)
    unavailable_threshold: int = Field(ge=1, le=10_000)
    recovery_success_threshold: int = Field(ge=1, le=10_000)
    stale_after_seconds: int = Field(ge=1, le=2_592_000)
    effective_at: datetime

    @model_validator(mode="after")
    def threshold_order(self) -> HealthPolicyInput:
        if self.unavailable_threshold < self.degraded_threshold:
            raise ValueError("invalid threshold order")
        return self


class RoutingInput(BaseModel):
    schema_version: Literal["provider-routing-v1"] = "provider-routing-v1"
    requirements: dict[str, Any]
    capability_ids: list[UUID] = Field(min_length=1, max_length=8)
    fallback_reasons: list[
        Literal[
            "rate_limited",
            "timeout",
            "transport",
            "provider_unavailable",
            "malformed_response",
            "structured_output",
        ]
    ] = Field(default_factory=list, max_length=8)
    effective_at: datetime

    @model_validator(mode="after")
    def contract(self) -> RoutingInput:
        validate_requirements(self.requirements)
        if len(set(self.capability_ids)) != len(self.capability_ids):
            raise ValueError("duplicate capability route")
        return self


class PriceInput(BaseModel):
    capability_id: UUID
    currency: Literal["USD"] = "USD"
    unit_basis: Literal[
        "generation_tokens", "embedding_request", "transcription_request", "tts_request"
    ]
    input_rate: int | None = Field(default=None, ge=0, le=MAX_BIGINT)
    output_rate: int | None = Field(default=None, ge=0, le=MAX_BIGINT)
    request_rate: int | None = Field(default=None, ge=0, le=MAX_BIGINT)
    effective_from: datetime
    effective_to: datetime | None = None

    @model_validator(mode="after")
    def shape(self) -> PriceInput:
        generation = self.unit_basis == "generation_tokens"
        if self.effective_to and self.effective_to <= self.effective_from:
            raise ValueError("invalid effective interval")
        if generation and (
            self.input_rate is None
            or self.output_rate is None
            or self.request_rate is not None
        ):
            raise ValueError("generation price requires input/output rates only")
        if not generation and (
            self.request_rate is None
            or self.input_rate is not None
            or self.output_rate is not None
        ):
            raise ValueError("embedding price requires request rate only")
        return self


class BudgetInput(BaseModel):
    workload_class: WorkloadClass
    measurement: BudgetMeasurement
    window_kind: BudgetWindowKind
    enabled: bool = True
    amount: int = Field(gt=0, le=MAX_BIGINT)
    mode: BudgetMode
    alert_threshold_bps: int = Field(ge=0, le=10_000)
    effective_at: datetime

    @model_validator(mode="after")
    def supported_measurement(self) -> BudgetInput:
        if self.workload_class in {
            WorkloadClass.EMBEDDING,
            WorkloadClass.TRANSCRIPTION,
            WorkloadClass.TEXT_TO_SPEECH,
        } and self.measurement not in {
            BudgetMeasurement.REQUESTS,
            BudgetMeasurement.ESTIMATED_COST_MICROUSD,
        }:
            raise ValueError(
                "embedding, transcription, and TTS budgets support "
                "request or estimated cost units"
            )
        return self


def _expected(value: str | None) -> int:
    if value is None:
        raise HTTPException(status_code=428, detail="If-Match required")
    try:
        result = int(value.strip('"'))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid If-Match") from exc
    if result < 0:
        raise HTTPException(status_code=400, detail="Invalid If-Match")
    return result


def _payload_hash(payload: BaseModel) -> str:
    return hashlib.sha256(
        json.dumps(
            payload.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _mutation_hash(payload: BaseModel, *scope: object) -> str:
    material = "|".join([*(str(item) for item in scope), _payload_hash(payload)])
    return hashlib.sha256(material.encode()).hexdigest()


async def _replay(
    session: AsyncSession,
    request: Request,
    principal: Principal,
    action: str,
    fingerprint: str,
) -> dict[str, Any] | None:
    event = await session.scalar(
        select(ControlAuditEventModel)
        .where(
            ControlAuditEventModel.actor_identity_id == principal.identity.id,
            ControlAuditEventModel.action == action,
            ControlAuditEventModel.request_id == request_id_for(request),
            ControlAuditEventModel.outcome == "success",
        )
        .order_by(ControlAuditEventModel.created_at.desc())
        .limit(1)
    )
    if event is None:
        return None
    if event.metadata_.get("fingerprint") != fingerprint:
        await _reject_mutation(
            session,
            request,
            principal,
            action,
            "request_id_conflict",
            fingerprint,
        )
    response = event.metadata_.get("response")
    if not isinstance(response, dict):
        await _reject_mutation(
            session,
            request,
            principal,
            action,
            "request_replay_unavailable",
            fingerprint,
        )
    return response


async def _lock_mutation(
    session: AsyncSession, request: Request, principal: Principal, action: str
) -> None:
    key = f"{principal.identity.id}|{action}|{request_id_for(request)}"
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": key}
    )


async def _lock_resource(session: AsyncSession, key: str) -> None:
    """Serialize first publication for one immutable resource head."""

    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"spec026|{key}"},
    )


async def _reject_mutation(
    session: AsyncSession,
    request: Request,
    principal: Principal,
    action: str,
    reason: str,
    fingerprint: str,
    *,
    tenant_id: UUID | None = None,
    resource_id: UUID | None = None,
) -> Never:
    """Persist a bounded conflict result before returning a controlled 409."""

    session.add(
        ControlAuditEventModel(
            tenant_id=tenant_id,
            actor_identity_id=principal.identity.id,
            action=action,
            outcome="failed",
            resource_type="provider_governance",
            resource_id=str(resource_id) if resource_id is not None else None,
            request_id=request_id_for(request),
            metadata_={
                "schema_version": "spec-026-v1",
                "reason": reason,
                "fingerprint": fingerprint,
            },
        )
    )
    await session.commit()
    raise HTTPException(status_code=409, detail="Revision conflict")


async def _deployment(session: AsyncSession, principal: Principal) -> None:
    if not await has_deployment_authority(session, principal.identity.id):
        raise HTTPException(status_code=403, detail="Forbidden")


async def _deployment_write(
    session: AsyncSession, principal: Principal, request: Request, action: str
) -> None:
    if await has_deployment_authority(session, principal.identity.id):
        return
    session.add(
        ControlAuditEventModel(
            tenant_id=None,
            actor_identity_id=principal.identity.id,
            action=action,
            outcome="denied",
            resource_type="provider_governance",
            resource_id=None,
            request_id=request_id_for(request),
            metadata_={"schema_version": "spec-026-v1"},
        )
    )
    await session.commit()
    raise HTTPException(status_code=403, detail="Forbidden")


async def _resource(
    session: AsyncSession,
    principal: Principal,
    tenant_id: UUID,
    scope: BudgetScope,
    resource_id: UUID,
    write: bool,
    request: Request | None = None,
    action: str | None = None,
) -> None:
    member = await membership_for(session, principal, tenant_id)
    if member.role not in (ADMIN_ROLES if write else ADMIN_ROLES | {"auditor"}):
        if write and request is not None and action is not None:
            session.add(
                ControlAuditEventModel(
                    tenant_id=tenant_id,
                    actor_identity_id=principal.identity.id,
                    action=action,
                    outcome="denied",
                    resource_type="provider_governance",
                    resource_id=str(resource_id),
                    request_id=request_id_for(request),
                    metadata_={"schema_version": "spec-026-v1"},
                )
            )
            await session.commit()
        raise HTTPException(status_code=403, detail="Forbidden")
    if scope == BudgetScope.ASSISTANT:
        if await assistant_for_tenant(session, tenant_id, resource_id) is None:
            raise HTTPException(status_code=404, detail="Not found")
    elif await connection_for_tenant(session, tenant_id, resource_id) is None:
        raise HTTPException(status_code=404, detail="Not found")


def _scope_values(
    scope: BudgetScope, tenant_id: UUID | None, resource_id: UUID | None
) -> tuple[str, UUID | None, UUID | None]:
    if scope == BudgetScope.DEPLOYMENT:
        return "deployment", None, None
    if tenant_id is None or resource_id is None:
        raise ValueError("resource scope is incomplete")
    if scope == BudgetScope.ASSISTANT:
        return f"assistant:{resource_id}", resource_id, None
    return f"platform_connection:{resource_id}", None, resource_id


async def _audit(
    session: AsyncSession,
    request: Request,
    principal: Principal,
    action: str,
    tenant_id: UUID | None,
    resource_type: str,
    resource_id: UUID,
    metadata: dict[str, Any],
) -> None:
    session.add(
        ControlAuditEventModel(
            tenant_id=tenant_id,
            actor_identity_id=principal.identity.id,
            action=action,
            outcome="success",
            resource_type=resource_type,
            resource_id=str(resource_id),
            request_id=request_id_for(request),
            metadata_={"schema_version": "spec-026-v1", **metadata},
        )
    )


def _capability(
    item: ProviderCapabilityModel, state: ProviderCapabilityStateModel | None
) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "provider": item.provider_id.value,
        "adapter": item.adapter_key.value,
        "workload": item.workload_class.value,
        "model": item.model,
        "schema_version": item.capability_schema_version,
        "capabilities": item.capability_metadata,
        "data_class": item.data_class.value,
        "credential_slot": item.credential_slot,
        "credential_configured": item.credential_configured,
        "reservation_strategy": item.reservation_strategy,
        "lifecycle": state.lifecycle.value if state else None,
        "health": state.health.value if state and state.health else None,
        "state_version": state.lock_version if state else None,
    }


async def _publish_route(
    session: AsyncSession,
    request: Request,
    principal: Principal,
    workload: WorkloadClass,
    payload: RoutingInput,
    expected: int,
    scope: BudgetScope,
    tenant_id: UUID | None,
    resource_id: UUID | None,
) -> dict[str, Any]:
    fingerprint = _mutation_hash(
        payload, scope.value, tenant_id, resource_id, workload.value
    )
    await _lock_mutation(session, request, principal, "provider_routing.publish")
    replay = await _replay(
        session, request, principal, "provider_routing.publish", fingerprint
    )
    if replay is not None:
        return replay
    scope_key, assistant_id, connection_id = _scope_values(
        scope, tenant_id, resource_id
    )
    await _lock_resource(session, f"route|{scope_key}|{workload.value}")
    head = await session.scalar(
        select(ProviderRoutingPolicyHeadModel)
        .where(
            ProviderRoutingPolicyHeadModel.scope_key == scope_key,
            ProviderRoutingPolicyHeadModel.workload_class == workload,
        )
        .with_for_update()
    )
    current = head.lock_version if head else 0
    if current != expected:
        await _reject_mutation(
            session,
            request,
            principal,
            "provider_routing.publish",
            "revision_conflict",
            fingerprint,
            tenant_id=tenant_id,
            resource_id=resource_id,
        )
    capabilities = list(
        await session.scalars(
            select(ProviderCapabilityModel).where(
                ProviderCapabilityModel.id.in_(payload.capability_ids),
                ProviderCapabilityModel.workload_class == workload,
            )
        )
    )
    if len(capabilities) != len(payload.capability_ids):
        raise HTTPException(status_code=400, detail="Incompatible capability route")
    for capability in capabilities:
        candidate = ResolvedProviderRoute(
            snapshot_id=capability.id,
            policy_revision_id=capability.id,
            capability_id=capability.id,
            provider_id=capability.provider_id,
            model=capability.model,
            adapter_key=capability.adapter_key,
            position=0,
            data_class=capability.data_class,
            credential_slot=capability.credential_slot,
            reservation_strategy=capability.reservation_strategy,
            capability_metadata=dict(capability.capability_metadata),
            allowed_fallback_reasons=frozenset(payload.fallback_reasons),
        )
        if not capability_matches(candidate, workload, payload.requirements).eligible:
            raise HTTPException(status_code=400, detail="Incompatible capability route")
    revision = ProviderRoutingPolicyRevisionModel(
        scope_type=scope,
        scope_key=scope_key,
        tenant_id=tenant_id,
        assistant_id=assistant_id,
        connection_id=connection_id,
        workload_class=workload,
        schema_version=payload.schema_version,
        version=current + 1,
        requirements=payload.requirements,
        effective_at=payload.effective_at.astimezone(UTC),
        created_by_identity_id=principal.identity.id,
    )
    session.add(revision)
    await session.flush()
    for position, capability_id in enumerate(payload.capability_ids):
        session.add(
            ProviderRoutingPolicyRouteModel(
                policy_revision_id=revision.id,
                capability_id=capability_id,
                position=position,
            )
        )
    for reason in sorted(set(payload.fallback_reasons)):
        session.add(
            ProviderRoutingFallbackReasonModel(
                policy_revision_id=revision.id, reason=reason
            )
        )
    if head is None:
        head = ProviderRoutingPolicyHeadModel(
            scope_key=scope_key,
            workload_class=workload,
            policy_revision_id=revision.id,
            lock_version=1,
        )
        session.add(head)
    else:
        head.policy_revision_id = revision.id
        head.lock_version += 1
    result = {
        "revision_id": str(revision.id),
        "schema_version": revision.schema_version,
        "version": revision.version,
        "head_version": head.lock_version,
        "scope": scope.value,
        "workload": workload.value,
    }
    await _audit(
        session,
        request,
        principal,
        "provider_routing.publish",
        tenant_id,
        "provider_routing_policy",
        revision.id,
        {
            "scope": scope.value,
            "workload": workload.value,
            "fingerprint": fingerprint,
            "response": result,
        },
    )
    await session.commit()
    return result


async def _route_view(
    session: AsyncSession,
    workload: WorkloadClass,
    scope: BudgetScope,
    tenant_id: UUID | None,
    resource_id: UUID | None,
) -> dict[str, Any]:
    scope_key, _, _ = _scope_values(scope, tenant_id, resource_id)
    head = await session.scalar(
        select(ProviderRoutingPolicyHeadModel).where(
            ProviderRoutingPolicyHeadModel.scope_key == scope_key,
            ProviderRoutingPolicyHeadModel.workload_class == workload,
        )
    )
    if head is None:
        return {"scope": scope.value, "workload": workload.value, "head": None}
    revision = await session.get(
        ProviderRoutingPolicyRevisionModel, head.policy_revision_id
    )
    assert revision is not None
    routes = list(
        await session.scalars(
            select(ProviderRoutingPolicyRouteModel)
            .where(ProviderRoutingPolicyRouteModel.policy_revision_id == revision.id)
            .order_by(ProviderRoutingPolicyRouteModel.position)
        )
    )
    reasons = list(
        await session.scalars(
            select(ProviderRoutingFallbackReasonModel.reason)
            .where(ProviderRoutingFallbackReasonModel.policy_revision_id == revision.id)
            .order_by(ProviderRoutingFallbackReasonModel.reason)
        )
    )
    return {
        "scope": scope.value,
        "workload": workload.value,
        "head_version": head.lock_version,
        "revision_id": str(revision.id),
        "schema_version": revision.schema_version,
        "version": revision.version,
        "requirements": revision.requirements,
        "capability_ids": [str(item.capability_id) for item in routes],
        "fallback_reasons": reasons,
        "effective_at": revision.effective_at.isoformat(),
    }


async def _publish_budget(
    session: AsyncSession,
    request: Request,
    principal: Principal,
    payload: BudgetInput,
    expected: int,
    scope: BudgetScope,
    tenant_id: UUID | None,
    resource_id: UUID | None,
) -> dict[str, Any]:
    fingerprint = _mutation_hash(payload, scope.value, tenant_id, resource_id)
    await _lock_mutation(session, request, principal, "provider_budget.publish")
    replay = await _replay(
        session, request, principal, "provider_budget.publish", fingerprint
    )
    if replay is not None:
        return replay
    scope_key, assistant_id, connection_id = _scope_values(
        scope, tenant_id, resource_id
    )
    await _lock_resource(
        session,
        "budget|"
        f"{scope_key}|{payload.workload_class.value}|"
        f"{payload.measurement.value}|{payload.window_kind.value}",
    )
    budget = await session.scalar(
        select(ProviderBudgetModel).where(
            ProviderBudgetModel.scope_key == scope_key,
            ProviderBudgetModel.workload_class == payload.workload_class,
            ProviderBudgetModel.measurement == payload.measurement,
            ProviderBudgetModel.window_kind == payload.window_kind,
        )
    )
    head = None
    if budget is None:
        if expected != 0:
            await _reject_mutation(
                session,
                request,
                principal,
                "provider_budget.publish",
                "revision_conflict",
                fingerprint,
                tenant_id=tenant_id,
                resource_id=resource_id,
            )
        budget = ProviderBudgetModel(
            scope_type=scope,
            scope_key=scope_key,
            tenant_id=tenant_id,
            assistant_id=assistant_id,
            connection_id=connection_id,
            workload_class=payload.workload_class,
            measurement=payload.measurement,
            window_kind=payload.window_kind,
        )
        session.add(budget)
        await session.flush()
    else:
        head = await session.scalar(
            select(ProviderBudgetHeadModel)
            .where(ProviderBudgetHeadModel.budget_id == budget.id)
            .with_for_update()
        )
        if head is None or head.lock_version != expected:
            await _reject_mutation(
                session,
                request,
                principal,
                "provider_budget.publish",
                "revision_conflict",
                fingerprint,
                tenant_id=tenant_id,
                resource_id=resource_id,
            )
    current = head.lock_version if head else 0
    revision = ProviderBudgetRevisionModel(
        budget_id=budget.id,
        version=current + 1,
        amount=payload.amount,
        mode=payload.mode,
        alert_threshold_bps=payload.alert_threshold_bps,
        effective_at=payload.effective_at.astimezone(UTC),
        created_by_identity_id=principal.identity.id,
    )
    session.add(revision)
    await session.flush()
    if head is None:
        head = ProviderBudgetHeadModel(
            budget_id=budget.id, budget_revision_id=revision.id, lock_version=1
        )
        session.add(head)
    else:
        head.budget_revision_id = revision.id
        head.lock_version += 1
    result = {
        "budget_id": str(budget.id),
        "revision_id": str(revision.id),
        "version": revision.version,
        "head_version": head.lock_version,
        "scope": scope.value,
        "workload": payload.workload_class.value,
        "measurement": payload.measurement.value,
        "window": payload.window_kind.value,
        "enabled": payload.enabled,
        "mode": payload.mode.value,
        "amount": payload.amount,
        "estimate_only": payload.measurement
        == BudgetMeasurement.ESTIMATED_COST_MICROUSD,
    }
    await _audit(
        session,
        request,
        principal,
        "provider_budget.publish",
        tenant_id,
        "provider_budget",
        budget.id,
        {
            "scope": scope.value,
            "workload": payload.workload_class.value,
            "measurement": payload.measurement.value,
            "fingerprint": fingerprint,
            "response": result,
        },
    )
    await session.commit()
    return result


async def _budget_view(
    session: AsyncSession,
    scope: BudgetScope,
    tenant_id: UUID | None,
    resource_id: UUID | None,
) -> dict[str, Any]:
    scope_key, _, _ = _scope_values(scope, tenant_id, resource_id)
    rows = (
        await session.execute(
            select(
                ProviderBudgetModel,
                ProviderBudgetRevisionModel,
                ProviderBudgetHeadModel,
            )
            .join(
                ProviderBudgetHeadModel,
                ProviderBudgetHeadModel.budget_id == ProviderBudgetModel.id,
            )
            .join(
                ProviderBudgetRevisionModel,
                ProviderBudgetRevisionModel.id
                == ProviderBudgetHeadModel.budget_revision_id,
            )
            .where(ProviderBudgetModel.scope_key == scope_key)
            .order_by(ProviderBudgetModel.workload_class, ProviderBudgetModel.id)
            .limit(100)
        )
    ).all()
    return {
        "items": [
            {
                "budget_id": str(b.id),
                "revision_id": str(r.id),
                "head_version": h.lock_version,
                "workload": b.workload_class.value,
                "measurement": b.measurement.value,
                "window": b.window_kind.value,
                "enabled": r.enabled,
                "amount": r.amount,
                "mode": r.mode.value,
                "alert_threshold_bps": r.alert_threshold_bps,
            }
            for b, r, h in rows
        ]
    }


async def _usage_view(
    session: AsyncSession,
    scope: BudgetScope,
    tenant_id: UUID | None,
    resource_id: UUID | None,
) -> dict[str, Any]:
    conditions = []
    if scope == BudgetScope.ASSISTANT:
        conditions = [
            ProviderUsageAttemptModel.tenant_id == tenant_id,
            ProviderUsageAttemptModel.assistant_id == resource_id,
        ]
    elif scope == BudgetScope.PLATFORM_CONNECTION:
        conditions = [
            ProviderUsageAttemptModel.tenant_id == tenant_id,
            ProviderUsageAttemptModel.connection_id == resource_id,
        ]
    rows = (
        await session.execute(
            select(
                ProviderUsageAttemptModel.workload_class,
                ProviderUsageAttemptModel.usage_quality,
                func.count(),
                func.sum(ProviderUsageAttemptModel.estimated_cost_microusd),
                func.count(ProviderUsageAttemptModel.estimated_cost_microusd),
                func.count().filter(
                    ProviderUsageAttemptModel.estimate_quality
                    != EstimateQuality.ESTIMATED
                ),
            )
            .where(ProviderUsageAttemptModel.request_count == 1, *conditions)
            .group_by(
                ProviderUsageAttemptModel.workload_class,
                ProviderUsageAttemptModel.usage_quality,
            )
            .order_by(
                ProviderUsageAttemptModel.workload_class,
                ProviderUsageAttemptModel.usage_quality,
            )
        )
    ).all()
    return {
        "schema_version": "provider-usage-summary-v1",
        "scope": scope.value,
        "estimate_currency": "USD",
        "billing_truth": False,
        "items": [
            {
                "workload": w.value,
                "usage_quality": q.value,
                "attempt_count": count,
                "known_estimated_cost_microusd": cost,
                "attempts_with_known_estimate": known,
                "attempts_with_incomplete_estimate": incomplete,
            }
            for w, q, count, cost, known, incomplete in rows
        ],
    }


def create_provider_governance_router(settings: Settings) -> APIRouter:
    del settings
    router = APIRouter(prefix="/control/v1", tags=["provider-governance"])

    @router.get("/deployment/provider-capabilities")
    async def list_capabilities(
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        await _deployment(session, principal)
        rows = (
            await session.execute(
                select(ProviderCapabilityModel, ProviderCapabilityStateModel)
                .outerjoin(
                    ProviderCapabilityStateModel,
                    ProviderCapabilityStateModel.capability_id
                    == ProviderCapabilityModel.id,
                )
                .order_by(
                    ProviderCapabilityModel.provider_id, ProviderCapabilityModel.id
                )
                .limit(100)
            )
        ).all()
        return {"items": [_capability(item, state) for item, state in rows]}

    @router.post("/deployment/provider-capabilities", status_code=201)
    async def create_capability(
        payload: CapabilityInput,
        request: Request,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        await _deployment_write(
            session, principal, request, "provider_capability.create"
        )
        fingerprint = _mutation_hash(payload, "deployment")
        await _lock_mutation(session, request, principal, "provider_capability.create")
        replay = await _replay(
            session, request, principal, "provider_capability.create", fingerprint
        )
        if replay is not None:
            return replay
        await _lock_resource(
            session,
            "capability|"
            f"{payload.provider_id.value}|{payload.model}|{payload.workload_class.value}",
        )
        duplicate = await session.scalar(
            select(ProviderCapabilityModel.id).where(
                ProviderCapabilityModel.provider_id == payload.provider_id,
                ProviderCapabilityModel.model == payload.model,
                ProviderCapabilityModel.workload_class == payload.workload_class,
                ProviderCapabilityModel.capability_schema_version
                == "provider-capability-v1",
            )
        )
        if duplicate is not None:
            await _reject_mutation(
                session,
                request,
                principal,
                "provider_capability.create",
                "capability_conflict",
                fingerprint,
                resource_id=duplicate,
            )
        if (
            payload.workload_class == WorkloadClass.EMBEDDING
            and payload.adapter_key != ProviderId.OLLAMA
        ):
            raise HTTPException(
                status_code=400, detail="Unsupported embedding provider"
            )
        item = ProviderCapabilityModel(
            **payload.model_dump(),
            capability_schema_version="provider-capability-v1",
            created_by_identity_id=principal.identity.id,
        )
        session.add(item)
        await session.flush()
        state = ProviderCapabilityStateModel(
            capability_id=item.id,
            lifecycle=ProviderLifecycle.DISABLED,
            health=None,
            lock_version=1,
        )
        session.add(state)
        result = _capability(item, state)
        await _audit(
            session,
            request,
            principal,
            "provider_capability.create",
            None,
            "provider_capability",
            item.id,
            {
                "workload": item.workload_class.value,
                "fingerprint": fingerprint,
                "response": result,
            },
        )
        await session.commit()
        return result

    @router.get("/deployment/provider-capabilities/{capability_id}/state")
    async def get_state(
        capability_id: UUID,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        await _deployment(session, principal)
        item = await session.get(ProviderCapabilityModel, capability_id)
        state = await session.scalar(
            select(ProviderCapabilityStateModel).where(
                ProviderCapabilityStateModel.capability_id == capability_id
            )
        )
        if item is None or state is None:
            raise HTTPException(status_code=404, detail="Not found")
        return _capability(item, state)

    @router.patch("/deployment/provider-capabilities/{capability_id}/state")
    async def patch_state(
        capability_id: UUID,
        payload: CapabilityStateInput,
        request: Request,
        if_match: str | None = Header(default=None, alias="If-Match"),
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        await _deployment_write(
            session, principal, request, "provider_capability.state"
        )
        fingerprint = _mutation_hash(payload, capability_id)
        await _lock_mutation(session, request, principal, "provider_capability.state")
        replay = await _replay(
            session, request, principal, "provider_capability.state", fingerprint
        )
        if replay is not None:
            return replay
        state = await session.scalar(
            select(ProviderCapabilityStateModel)
            .where(ProviderCapabilityStateModel.capability_id == capability_id)
            .with_for_update()
        )
        if state is None:
            raise HTTPException(status_code=404, detail="Not found")
        if state.lock_version != _expected(if_match):
            await _reject_mutation(
                session,
                request,
                principal,
                "provider_capability.state",
                "revision_conflict",
                fingerprint,
                resource_id=capability_id,
            )
        if payload.health_policy_revision_id is not None:
            policy = await session.get(
                ProviderHealthPolicyRevisionModel,
                payload.health_policy_revision_id,
            )
            if (
                policy is None
                or policy.capability_id != capability_id
                or policy.effective_at > datetime.now(UTC)
            ):
                raise HTTPException(status_code=400, detail="Invalid health policy")
        if payload.health is not None and payload.health_policy_revision_id is None:
            raise HTTPException(
                status_code=400, detail="Observed health requires a health policy"
            )
        previous = state.health
        state.lifecycle, state.health, state.health_policy_revision_id = (
            payload.lifecycle,
            payload.health,
            payload.health_policy_revision_id,
        )
        state.last_evaluated_at = (
            datetime.now(UTC) if payload.health is not None else None
        )
        state.consecutive_successes = 0
        state.consecutive_failures = 0
        state.lock_version += 1
        if previous != state.health:
            session.add(
                ProviderHealthEventModel(
                    capability_id=capability_id,
                    from_state=previous,
                    to_state=state.health,
                    reason=payload.reason,
                    source="control_plane",
                )
            )
        item = await session.get(ProviderCapabilityModel, capability_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Not found")
        result = _capability(item, state)
        await _audit(
            session,
            request,
            principal,
            "provider_capability.state",
            None,
            "provider_capability",
            capability_id,
            {
                "lifecycle": payload.lifecycle.value,
                "reason": payload.reason,
                "fingerprint": fingerprint,
                "response": result,
            },
        )
        if previous != state.health:
            telemetry_for(request).increment(
                "january_provider_health_transitions_total",
                provider=item.provider_id.value,
                from_state=previous.value if previous is not None else "unknown",
                to_state=state.health.value if state.health is not None else "unknown",
                reason=(
                    "administrative"
                    if payload.reason == "administrative"
                    else "configuration"
                ),
            )
        await session.commit()
        return result

    @router.get("/deployment/provider-health-policies")
    async def list_health(
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        await _deployment(session, principal)
        items = list(
            await session.scalars(
                select(ProviderHealthPolicyRevisionModel)
                .order_by(ProviderHealthPolicyRevisionModel.created_at.desc())
                .limit(100)
            )
        )
        return {
            "items": [
                {
                    "id": str(i.id),
                    "capability_id": str(i.capability_id),
                    "version": i.version,
                    "observation_window_seconds": i.observation_window_seconds,
                    "degraded_threshold": i.degraded_threshold,
                    "unavailable_threshold": i.unavailable_threshold,
                    "recovery_success_threshold": i.recovery_success_threshold,
                    "stale_after_seconds": i.stale_after_seconds,
                    "effective_at": i.effective_at.isoformat(),
                }
                for i in items
            ]
        }

    @router.post("/deployment/provider-health-policies", status_code=201)
    async def publish_health(
        payload: HealthPolicyInput,
        request: Request,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        await _deployment_write(
            session, principal, request, "provider_health_policy.publish"
        )
        fingerprint = _mutation_hash(payload, payload.capability_id)
        await _lock_mutation(
            session, request, principal, "provider_health_policy.publish"
        )
        replay = await _replay(
            session,
            request,
            principal,
            "provider_health_policy.publish",
            fingerprint,
        )
        if replay is not None:
            return replay
        await _lock_resource(session, f"health|{payload.capability_id}")
        capability = await session.get(ProviderCapabilityModel, payload.capability_id)
        if capability is None:
            raise HTTPException(status_code=404, detail="Not found")
        latest = await session.scalar(
            select(
                func.coalesce(func.max(ProviderHealthPolicyRevisionModel.version), 0)
            ).where(
                ProviderHealthPolicyRevisionModel.capability_id == payload.capability_id
            )
        )
        item = ProviderHealthPolicyRevisionModel(
            **payload.model_dump(),
            version=int(latest or 0) + 1,
            created_by_identity_id=principal.identity.id,
        )
        session.add(item)
        await session.flush()
        result = {"id": str(item.id), "version": item.version}
        await _audit(
            session,
            request,
            principal,
            "provider_health_policy.publish",
            None,
            "provider_health_policy",
            item.id,
            {
                "capability_id": str(item.capability_id),
                "fingerprint": fingerprint,
                "response": result,
            },
        )
        await session.commit()
        return result

    @router.get("/deployment/provider-routing/{workload}")
    async def deployment_route(
        workload: WorkloadClass,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        await _deployment(session, principal)
        return await _route_view(session, workload, BudgetScope.DEPLOYMENT, None, None)

    @router.post("/deployment/provider-routing/{workload}", status_code=201)
    async def publish_deployment_route(
        workload: WorkloadClass,
        payload: RoutingInput,
        request: Request,
        if_match: str | None = Header(default=None, alias="If-Match"),
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        await _deployment_write(session, principal, request, "provider_routing.publish")
        return await _publish_route(
            session,
            request,
            principal,
            workload,
            payload,
            _expected(if_match),
            BudgetScope.DEPLOYMENT,
            None,
            None,
        )

    @router.get("/deployment/provider-prices")
    async def list_prices(
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        await _deployment(session, principal)
        items = list(
            await session.scalars(
                select(ProviderPriceRevisionModel)
                .order_by(ProviderPriceRevisionModel.effective_from.desc())
                .limit(100)
            )
        )
        return {
            "items": [
                {
                    "id": str(i.id),
                    "capability_id": str(i.capability_id),
                    "currency": i.currency,
                    "unit_basis": i.unit_basis,
                    "input_rate": i.input_rate,
                    "output_rate": i.output_rate,
                    "request_rate": i.request_rate,
                    "effective_from": i.effective_from.isoformat(),
                    "effective_to": i.effective_to.isoformat()
                    if i.effective_to
                    else None,
                    "estimate_only": True,
                }
                for i in items
            ]
        }

    @router.post("/deployment/provider-prices", status_code=201)
    async def publish_price(
        payload: PriceInput,
        request: Request,
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        await _deployment_write(session, principal, request, "provider_price.publish")
        fingerprint = _mutation_hash(payload, payload.capability_id)
        await _lock_mutation(session, request, principal, "provider_price.publish")
        replay = await _replay(
            session, request, principal, "provider_price.publish", fingerprint
        )
        if replay is not None:
            return replay
        await _lock_resource(session, f"price|{payload.capability_id}")
        capability = await session.get(ProviderCapabilityModel, payload.capability_id)
        if capability is None:
            raise HTTPException(status_code=404, detail="Not found")
        expected_basis = {
            WorkloadClass.CHAT_GENERATION: "generation_tokens",
            WorkloadClass.EMBEDDING: "embedding_request",
            WorkloadClass.TRANSCRIPTION: "transcription_request",
            WorkloadClass.TEXT_TO_SPEECH: "tts_request",
        }[capability.workload_class]
        if payload.unit_basis != expected_basis:
            raise HTTPException(status_code=400, detail="Incompatible price basis")
        overlap = await session.scalar(
            select(ProviderPriceRevisionModel.id)
            .where(
                ProviderPriceRevisionModel.capability_id == payload.capability_id,
                ProviderPriceRevisionModel.effective_from
                < (payload.effective_to or datetime.max.replace(tzinfo=UTC)),
                (ProviderPriceRevisionModel.effective_to.is_(None))
                | (ProviderPriceRevisionModel.effective_to > payload.effective_from),
            )
            .limit(1)
        )
        if overlap is not None:
            await _reject_mutation(
                session,
                request,
                principal,
                "provider_price.publish",
                "price_interval_conflict",
                fingerprint,
                resource_id=overlap,
            )
        item = ProviderPriceRevisionModel(
            **payload.model_dump(), created_by_identity_id=principal.identity.id
        )
        session.add(item)
        await session.flush()
        result = {
            "id": str(item.id),
            "currency": item.currency,
            "unit_basis": item.unit_basis,
            "estimate_only": True,
        }
        await _audit(
            session,
            request,
            principal,
            "provider_price.publish",
            None,
            "provider_price",
            item.id,
            {
                "unit_basis": item.unit_basis,
                "fingerprint": fingerprint,
                "response": result,
            },
        )
        await session.commit()
        return result

    @router.get("/deployment/provider-budgets")
    async def deployment_budgets(
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        await _deployment(session, principal)
        return await _budget_view(session, BudgetScope.DEPLOYMENT, None, None)

    @router.post("/deployment/provider-budgets", status_code=201)
    async def publish_deployment_budget(
        payload: BudgetInput,
        request: Request,
        if_match: str | None = Header(default=None, alias="If-Match"),
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        await _deployment_write(session, principal, request, "provider_budget.publish")
        return await _publish_budget(
            session,
            request,
            principal,
            payload,
            _expected(if_match),
            BudgetScope.DEPLOYMENT,
            None,
            None,
        )

    @router.get("/deployment/provider-usage-summary")
    async def deployment_usage(
        principal: Principal = Depends(principal_for),
        session: AsyncSession = Depends(database_session),
    ) -> dict[str, Any]:
        await _deployment(session, principal)
        return await _usage_view(session, BudgetScope.DEPLOYMENT, None, None)

    def add_resource_routes(
        noun: Literal["assistants", "connections"], scope: BudgetScope
    ) -> None:
        prefix = f"/tenants/{{tenant_id}}/{noun}/{{resource_id}}"

        async def get_route(
            tenant_id: UUID,
            resource_id: UUID,
            workload: WorkloadClass,
            principal: Principal = Depends(principal_for),
            session: AsyncSession = Depends(database_session),
        ) -> dict[str, Any]:
            await _resource(session, principal, tenant_id, scope, resource_id, False)
            return await _route_view(session, workload, scope, tenant_id, resource_id)

        async def post_route(
            tenant_id: UUID,
            resource_id: UUID,
            workload: WorkloadClass,
            payload: RoutingInput,
            request: Request,
            if_match: str | None = Header(default=None, alias="If-Match"),
            principal: Principal = Depends(principal_for),
            session: AsyncSession = Depends(database_session),
        ) -> dict[str, Any]:
            await _resource(
                session,
                principal,
                tenant_id,
                scope,
                resource_id,
                True,
                request,
                "provider_routing.publish",
            )
            return await _publish_route(
                session,
                request,
                principal,
                workload,
                payload,
                _expected(if_match),
                scope,
                tenant_id,
                resource_id,
            )

        async def get_budgets(
            tenant_id: UUID,
            resource_id: UUID,
            principal: Principal = Depends(principal_for),
            session: AsyncSession = Depends(database_session),
        ) -> dict[str, Any]:
            await _resource(session, principal, tenant_id, scope, resource_id, False)
            return await _budget_view(session, scope, tenant_id, resource_id)

        async def post_budget(
            tenant_id: UUID,
            resource_id: UUID,
            payload: BudgetInput,
            request: Request,
            if_match: str | None = Header(default=None, alias="If-Match"),
            principal: Principal = Depends(principal_for),
            session: AsyncSession = Depends(database_session),
        ) -> dict[str, Any]:
            await _resource(
                session,
                principal,
                tenant_id,
                scope,
                resource_id,
                True,
                request,
                "provider_budget.publish",
            )
            return await _publish_budget(
                session,
                request,
                principal,
                payload,
                _expected(if_match),
                scope,
                tenant_id,
                resource_id,
            )

        async def usage(
            tenant_id: UUID,
            resource_id: UUID,
            principal: Principal = Depends(principal_for),
            session: AsyncSession = Depends(database_session),
        ) -> dict[str, Any]:
            await _resource(session, principal, tenant_id, scope, resource_id, False)
            return await _usage_view(session, scope, tenant_id, resource_id)

        router.add_api_route(
            f"{prefix}/provider-routing/{{workload}}",
            get_route,
            methods=["GET"],
            name=f"get_{noun}_provider_route",
        )
        router.add_api_route(
            f"{prefix}/provider-routing/{{workload}}",
            post_route,
            methods=["POST"],
            status_code=201,
            name=f"publish_{noun}_provider_route",
        )
        router.add_api_route(
            f"{prefix}/provider-budgets",
            get_budgets,
            methods=["GET"],
            name=f"get_{noun}_provider_budgets",
        )
        router.add_api_route(
            f"{prefix}/provider-budgets",
            post_budget,
            methods=["POST"],
            status_code=201,
            name=f"publish_{noun}_provider_budget",
        )
        router.add_api_route(
            f"{prefix}/provider-usage-summary",
            usage,
            methods=["GET"],
            name=f"get_{noun}_provider_usage",
        )

    add_resource_routes("assistants", BudgetScope.ASSISTANT)
    add_resource_routes("connections", BudgetScope.PLATFORM_CONNECTION)
    return router
