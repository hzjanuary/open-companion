"""Platform-independent data-governance vocabulary (SPEC-025).

Content-safe by construction: this module carries closed classes, opaque
references, and bounded counts only. The one exception is subject export
packages (FR-02), which by definition contain the requesting subject's own
data (NFR-01).
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

GOVERNANCE_EXPORT_SCHEMA_VERSION: Final = "governance-export-v1"
GOVERNANCE_AUDIT_SCHEMA_VERSION: Final = "spec-025-v1"


class GovernanceScope(StrEnum):
    SUBJECT = "subject"
    GROUP = "group"
    DEPLOYMENT = "deployment"


class DeploymentAuthority(StrEnum):
    """Explicit deployment-wide authority, independent of tenant membership."""

    DEPLOYMENT_OPERATOR = "deployment_operator"


class ExportRequestStatus(StrEnum):
    REQUESTED = "requested"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    DELIVERED = "delivered"
    RETRIEVED = "retrieved"
    FAILED = "failed"
    EXPIRED = "expired"


class ErasureRequestStatus(StrEnum):
    REQUESTED = "requested"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


class ErasurePartialReason(StrEnum):
    """Closed set of reasons a partial outcome is reported (FR-06)."""

    SEMANTIC_INDEX_UNAVAILABLE = "semantic_index_unavailable"
    REPOSITORY_ERROR = "repository_error"
    ALREADY_DELETED = "already_deleted"
    WORKER_RESTART = "worker_restart"


class GovernanceAuditEventType(StrEnum):
    EXPORT_REQUEST = "export_request"
    EXPORT_COMPLETE = "export_complete"
    EXPORT_RETRIEVED = "export_retrieved"
    EXPORT_EXPIRED = "export_expired"
    EXPORT_FAILED = "export_failed"
    ERASURE_REQUEST = "erasure_request"
    ERASURE_IN_PROGRESS = "erasure_in_progress"
    ERASURE_COMPLETE = "erasure_complete"
    ERASURE_PARTIAL = "erasure_partial"
    ERASURE_FAILED = "erasure_failed"


@dataclass(frozen=True, slots=True)
class ExportManifest:
    schema_version: str
    scope: str
    request_id: str
    generated_at: str
    categories: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "scope": self.scope,
            "request_id": self.request_id,
            "generated_at": self.generated_at,
            "categories": list(self.categories),
        }


@dataclass(frozen=True, slots=True)
class DataCategory:
    """One register row of the versioned data inventory (FR-01)."""

    name: str
    purpose: str
    surface: str
    retention_basis: str
    user_control: str

    def to_dict(self) -> dict[str, str]:
        return {
            "category": self.name,
            "purpose": self.purpose,
            "storage_surface": self.surface,
            "retention_basis": self.retention_basis,
            "user_control": self.user_control,
        }


DATA_INVENTORY_VERSION: Final = "data-inventory-v6"

# The authoritative register. Storage-surface values are the closed classes the
# product recognizes: primary database, derived index, coordination layer,
# operational telemetry, or audit. The register is the input for the
# deployment snapshot (FR-04) and the written inventory document (FR-01).
DATA_INVENTORY: Final[tuple[DataCategory, ...]] = (
    DataCategory(
        "conversations",
        "Conversation identity, membership, and configuration state",
        "primary database",
        "Persists for the life of the conversation; configuration is immutable "
        "and revisioned",
        "group administrator / operating owner",
    ),
    DataCategory(
        "participants",
        "Member identity, preferences, opt-out and protection state",
        "primary database",
        "Persists; erasure leaves a content-free tombstone (privacy_deleted_at)",
        "subject",
    ),
    DataCategory(
        "messages",
        "Message text, derived voice/audio transcript and provenance metadata",
        "primary database",
        "Bounded; automatically redacted after raw_content_retention_days (max 30)",
        "subject",
    ),
    DataCategory(
        "message_media",
        "Source-scoped media references, caption and recovery metadata; no raw bytes",
        "primary database",
        "Cleared with original message content; raw bytes are ephemeral memory only",
        "subject",
    ),
    DataCategory(
        "incoming_platform_updates",
        "Raw platform update payloads",
        "primary database",
        "Bounded; automatically redacted after raw_content_retention_days (max 30)",
        "subject",
    ),
    DataCategory(
        "response_plans",
        "Planned assistant responses and command replies",
        "primary database",
        "Bounded; automatically redacted after raw_content_retention_days (max 30)",
        "subject",
    ),
    DataCategory(
        "outbound_actions",
        "Outbound delivery actions and their payloads",
        "primary database",
        "Bounded; automatically redacted after raw_content_retention_days (max 30)",
        "subject",
    ),
    DataCategory(
        "telegram_command_jobs",
        "Command jobs and their arguments",
        "primary database",
        "Bounded; arguments automatically redacted after "
        "raw_content_retention_days (max 30)",
        "subject",
    ),
    DataCategory(
        "conversation_feedback",
        "Explicit helpful/unhelpful current state and immutable revision events",
        "primary database",
        "Follows target response retention and subject privacy erasure",
        "subject only",
    ),
    DataCategory(
        "proactive_schedules",
        "Private reminders, timezone/quiet-hours preferences, and opted-in check-ins",
        "primary database",
        "Active through the bounded schedule horizon; content is erased on subject "
        "deletion and terminal history is redacted after the configured schedule "
        "period",
        "subject only",
    ),
    DataCategory(
        "proactive_schedule_occurrences",
        "Content-free durable schedule delivery and recovery state",
        "coordination layer",
        "Terminal records are reduced to bounded history after schedule retention",
        "subject / operating owner",
    ),
    DataCategory(
        "explicit_memory_items",
        "Explicit memory stored by members",
        "primary database",
        "Persists until deleted, expired, erased, or reset; group reset or "
        "erasure clears content",
        "subject / group administrator",
    ),
    DataCategory(
        "personal_context_items",
        "Explicit creator-private context in an exact private conversation",
        "primary database",
        "Persists until deleted, cleared, expired, or erased",
        "subject only",
    ),
    DataCategory(
        "memory_recall_policies",
        "Content-free exact-conversation participant recall state",
        "primary database",
        "Persists as revisioned authority/tombstone history",
        "subject / operating owner",
    ),
    DataCategory(
        "memory_control_operations",
        "Content-free idempotency results for memory-control commands",
        "audit",
        "Persists as content-free operation history",
        "operating owner",
    ),
    DataCategory(
        "memory_events",
        "Content-free memory mutation audit",
        "audit",
        "Persists as content-free tombstone history",
        "operating owner",
    ),
    DataCategory(
        "conversation_summaries",
        "Derived conversation summaries",
        "primary database",
        "Expire at the earliest source-message deadline or on erasure/reset",
        "subject / group administrator",
    ),
    DataCategory(
        "semantic_index_jobs",
        "Coordination jobs for the derived semantic index",
        "coordination layer",
        "Ephemeral; content-free; rebuilt from explicit memory",
        "operating owner",
    ),
    DataCategory(
        "semantic_index_collections",
        "Derived-index collection registry",
        "derived index",
        "Rebuildable; content-free opaque points only",
        "operating owner",
    ),
    DataCategory(
        "conversation_configuration_revisions",
        "Immutable configuration and personality snapshots",
        "primary database",
        "Persists as immutable revision history",
        "group administrator / operating owner",
    ),
    DataCategory(
        "safety_policy_decisions",
        "Content-free safety decision records",
        "audit",
        "Bounded; governed separately from product-content retention",
        "operating owner",
    ),
    DataCategory(
        "rate_limit_events",
        "Content-free rate-limit event records",
        "audit",
        "Bounded; governed separately from product-content retention",
        "operating owner",
    ),
    DataCategory(
        "safety_review_items",
        "Content-free moderation review queue",
        "audit",
        "Bounded by safety_review_retention_days (operator-configurable)",
        "operating owner",
    ),
    DataCategory(
        "control_tenants_and_operators",
        "Control-plane tenants, identities, memberships, bindings",
        "audit",
        "Persists until operator-managed",
        "operating owner",
    ),
    DataCategory(
        "control_deployment_authorities",
        "Tenant-independent deployment-operator grants and revocations",
        "audit",
        "Persists until operator-managed",
        "operating owner",
    ),
    DataCategory(
        "control_deployment_authority_operations",
        "Content-free idempotency history for deployment-authority mutations",
        "audit",
        "Persists until operator-managed",
        "operating owner",
    ),
    DataCategory(
        "control_group_revisions",
        "Control-plane group configuration revisions",
        "audit",
        "Persists as immutable revision history",
        "operating owner",
    ),
    DataCategory(
        "control_audit_events",
        "Content-free control-plane audit trail",
        "audit",
        "Bounded by governance_audit_retention_days",
        "operating owner",
    ),
    DataCategory(
        "governance_export_requests",
        "Export request lifecycle (content-free)",
        "audit",
        "Persists as content-free request history",
        "operating owner",
    ),
    DataCategory(
        "governance_export_packages",
        "Temporary single-use export packages (subject/group content)",
        "primary database",
        "Expire after governance_export_ttl_days; single-use and cleared on retrieval",
        "subject / group administrator",
    ),
    DataCategory(
        "governance_erasure_requests",
        "Erasure request lifecycle and status (content-free)",
        "audit",
        "Persists as content-free request history",
        "operating owner",
    ),
    DataCategory(
        "governance_audit_events",
        "Content-free governance audit trail",
        "audit",
        "Bounded by governance_audit_retention_days",
        "operating owner",
    ),
    DataCategory(
        "provider_governance_configuration",
        "Provider registry, routing, health, price, and budget revisions",
        "primary database",
        "Content-free operating history; duration requires operating-owner approval",
        "deployment operator / tenant resource administrator",
    ),
    DataCategory(
        "provider_usage_and_budget_ledger",
        "Provider-I/O attribution, usage quality, estimates, and budget reservations",
        "primary database",
        "Content-free operating history; duration requires operating-owner approval",
        "deployment operator / tenant resource administrator",
    ),
    DataCategory(
        "operational_telemetry",
        "Aggregated operational metrics",
        "operational telemetry",
        "Content-free aggregated counters",
        "operating owner",
    ),
)

SUBJECT_EXPORT_CATEGORIES: Final = (
    "participant",
    "preferences",
    "protection",
    "messages",
    "memories",
    "memory_recall",
    "scheduling",
    "feedback",
)
GROUP_EXPORT_CATEGORIES: Final = (
    "configuration",
    "personality",
    "safety",
    "revision_history",
    "memories",
)
DEPLOYMENT_EXPORT_CATEGORIES: Final = (
    "data_inventory",
    "data_volumes",
    "retention_configuration",
    "governance_state",
)
