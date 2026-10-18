"""Pure SPEC-030 tenant/resource identity and lifecycle rules."""

import re
from uuid import UUID

from app.domain.persistence import (
    AssistantStatus,
    PlatformConnectionStatus,
    TenantStatus,
)

ASSISTANT_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
LEGACY_TENANT_ID = UUID("00000000-0000-4000-8000-000000000030")


def valid_assistant_slug(value: str) -> bool:
    return bool(ASSISTANT_SLUG_PATTERN.fullmatch(value))


def tenant_transition_allowed(current: TenantStatus, target: TenantStatus) -> bool:
    if current == TenantStatus.RETIRED:
        return target == TenantStatus.RETIRED
    return True


def assistant_transition_allowed(
    current: AssistantStatus, target: AssistantStatus
) -> bool:
    if current == AssistantStatus.RETIRED:
        return target == AssistantStatus.RETIRED
    return True


def connection_transition_allowed(
    current: PlatformConnectionStatus, target: PlatformConnectionStatus
) -> bool:
    if current == PlatformConnectionStatus.RETIRED:
        return target == PlatformConnectionStatus.RETIRED
    return True
