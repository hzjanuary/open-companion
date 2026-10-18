"""Platform-independent durable ingress contracts."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.persistence import IngressSource, Platform


@dataclass(frozen=True, slots=True)
class IngressEnvelope:
    """Validated update metadata; raw provider data stays at infrastructure."""

    platform: Platform
    platform_connection_id: UUID
    platform_update_id: str
    update_type: str
    supported: bool
    ingress_source: IngressSource
    received_at: datetime
    raw_payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class AcceptedIngressUpdate:
    incoming_update_id: UUID
    duplicate: bool


@dataclass(frozen=True, slots=True)
class IngressQueueEvent:
    schema_version: int
    incoming_update_id: UUID
    platform: Platform
    platform_connection_id: UUID
    platform_update_id: str
    update_type: str
    received_at: datetime


class DurableIngressPort(Protocol):
    async def accept(self, envelope: IngressEnvelope) -> AcceptedIngressUpdate: ...
