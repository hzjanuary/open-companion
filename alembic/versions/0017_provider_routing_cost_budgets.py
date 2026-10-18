"""Add SPEC-026 provider routing, usage, pricing, and budgets.

Revision ID: 0017_provider_routing_cost_budgets
Revises: 0016_data_governance
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017_provider_routing_cost_budgets"
down_revision: str | None = "0016_data_governance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    ]


def _scope_columns(uuid: sa.Uuid) -> list[sa.Column[object]]:
    return [
        sa.Column("scope_type", sa.String(32), nullable=False),
        sa.Column("scope_key", sa.String(80), nullable=False),
        sa.Column(
            "tenant_id",
            uuid,
            sa.ForeignKey("control_tenants.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "assistant_id",
            uuid,
            sa.ForeignKey("assistants.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "connection_id",
            uuid,
            sa.ForeignKey("platform_connections.id", ondelete="RESTRICT"),
        ),
    ]


SCOPE_SHAPE = """
(scope_type = 'deployment' AND tenant_id IS NULL AND assistant_id IS NULL
 AND connection_id IS NULL)
OR (scope_type = 'assistant' AND tenant_id IS NOT NULL AND assistant_id IS NOT NULL
 AND connection_id IS NULL)
OR (scope_type = 'platform_connection' AND tenant_id IS NOT NULL
 AND assistant_id IS NULL AND connection_id IS NOT NULL)
"""


def upgrade() -> None:
    uuid = sa.Uuid()
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT assistant_id FROM control_assistant_bindings
            GROUP BY assistant_id HAVING count(*) > 1
          ) THEN
            RAISE EXCEPTION 'ambiguous Assistant control ownership blocks SPEC-026';
          END IF;
          IF EXISTS (
            SELECT connection_id FROM control_connection_bindings
            GROUP BY connection_id HAVING count(*) > 1
          ) THEN
            RAISE EXCEPTION 'ambiguous connection control ownership blocks SPEC-026';
          END IF;
        END $$;
        """
    )

    op.create_unique_constraint(
        "uq_control_assistant_bindings_assistant",
        "control_assistant_bindings",
        ["assistant_id"],
    )
    op.create_unique_constraint(
        "uq_control_connection_bindings_connection",
        "control_connection_bindings",
        ["connection_id"],
    )

    op.create_table(
        "provider_capabilities",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("provider_id", sa.String(32), nullable=False),
        sa.Column("adapter_key", sa.String(32), nullable=False),
        sa.Column("workload_class", sa.String(32), nullable=False),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column(
            "capability_schema_version",
            sa.String(64),
            nullable=False,
            server_default="provider-capability-v1",
        ),
        sa.Column(
            "capability_metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("data_class", sa.String(32), nullable=False),
        sa.Column("credential_slot", sa.String(64), nullable=False),
        sa.Column("credential_configured", sa.Boolean(), nullable=False),
        sa.Column("reservation_strategy", sa.String(32), nullable=False),
        sa.Column(
            "created_by_identity_id",
            uuid,
            sa.ForeignKey("control_operator_identities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        *_timestamps(),
        sa.UniqueConstraint(
            "provider_id",
            "model",
            "workload_class",
            "capability_schema_version",
            name="uq_provider_capabilities_contract",
        ),
        sa.CheckConstraint(
            "provider_id IN ('openai','gemini','groq','openrouter','ollama')",
            name="provider_capability_provider",
        ),
        sa.CheckConstraint(
            "adapter_key IN ('openai','gemini','groq','openrouter','ollama')",
            name="provider_capability_adapter",
        ),
        sa.CheckConstraint(
            "provider_id = adapter_key AND credential_slot = adapter_key",
            name="provider_capability_adapter_identity",
        ),
        sa.CheckConstraint(
            "workload_class IN ('chat_generation','embedding')",
            name="provider_capability_workload",
        ),
        sa.CheckConstraint(
            "capability_schema_version = 'provider-capability-v1'",
            name="provider_capability_schema_version",
        ),
        sa.CheckConstraint(
            "data_class IN ('local','approved_external')",
            name="provider_capability_data_class",
        ),
        sa.CheckConstraint(
            "workload_class <> 'embedding' OR "
            "(provider_id = 'ollama' AND data_class = 'local')",
            name="provider_capability_embedding_boundary",
        ),
        sa.CheckConstraint(
            "reservation_strategy IN ('provider_tokenizer','utf8_byte_upper_bound',"
            "'fixed_max','request_count')",
            name="provider_capability_reservation_strategy",
        ),
    )

    op.create_table(
        "provider_health_policy_revisions",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "capability_id",
            uuid,
            sa.ForeignKey("provider_capabilities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("observation_window_seconds", sa.Integer(), nullable=False),
        sa.Column("degraded_threshold", sa.Integer(), nullable=False),
        sa.Column("unavailable_threshold", sa.Integer(), nullable=False),
        sa.Column("recovery_success_threshold", sa.Integer(), nullable=False),
        sa.Column("stale_after_seconds", sa.Integer(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_by_identity_id",
            uuid,
            sa.ForeignKey("control_operator_identities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        *_timestamps(),
        sa.UniqueConstraint(
            "capability_id", "version", name="uq_provider_health_policy_version"
        ),
        sa.CheckConstraint(
            "version > 0", name="provider_health_policy_version_positive"
        ),
        sa.CheckConstraint(
            "observation_window_seconds > 0 AND degraded_threshold > 0 AND "
            "unavailable_threshold >= degraded_threshold AND "
            "recovery_success_threshold > 0 AND stale_after_seconds > 0",
            name="provider_health_policy_bounds",
        ),
    )

    op.create_table(
        "provider_capability_states",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "capability_id",
            uuid,
            sa.ForeignKey("provider_capabilities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("lifecycle", sa.String(32), nullable=False),
        sa.Column("health", sa.String(32)),
        sa.Column(
            "health_policy_revision_id",
            uuid,
            sa.ForeignKey("provider_health_policy_revisions.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "consecutive_successes", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "consecutive_failures", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_failure_at", sa.DateTime(timezone=True)),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
        sa.UniqueConstraint(
            "capability_id", name="uq_provider_capability_states_capability"
        ),
        sa.CheckConstraint(
            "lifecycle IN ('enabled','draining','disabled')",
            name="provider_capability_lifecycle",
        ),
        sa.CheckConstraint(
            "health IS NULL OR health IN ('ready','degraded','unavailable')",
            name="provider_capability_health",
        ),
        sa.CheckConstraint(
            "consecutive_successes >= 0 AND consecutive_failures >= 0 "
            "AND lock_version > 0",
            name="provider_capability_state_bounds",
        ),
    )

    op.create_table(
        "provider_health_events",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "capability_id",
            uuid,
            sa.ForeignKey("provider_capabilities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("from_state", sa.String(32)),
        sa.Column("to_state", sa.String(32)),
        sa.Column("reason", sa.String(64), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "from_state IS NULL OR from_state IN ('ready','degraded','unavailable')",
            name="provider_health_event_from",
        ),
        sa.CheckConstraint(
            "to_state IS NULL OR to_state IN ('ready','degraded','unavailable')",
            name="provider_health_event_to",
        ),
    )
    op.create_index(
        "ix_provider_health_events_capability_created",
        "provider_health_events",
        ["capability_id", "created_at"],
    )

    op.create_table(
        "provider_routing_policy_revisions",
        sa.Column("id", uuid, primary_key=True),
        *_scope_columns(uuid),
        sa.Column("workload_class", sa.String(32), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "requirements",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_by_identity_id",
            uuid,
            sa.ForeignKey("control_operator_identities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        *_timestamps(),
        sa.UniqueConstraint(
            "scope_key",
            "workload_class",
            "version",
            name="uq_provider_routing_scope_workload_version",
        ),
        sa.CheckConstraint(SCOPE_SHAPE, name="provider_routing_scope_shape"),
        sa.CheckConstraint(
            "workload_class IN ('chat_generation','embedding')",
            name="provider_routing_workload",
        ),
        sa.CheckConstraint(
            "schema_version = 'provider-routing-v1'",
            name="provider_routing_schema_version",
        ),
        sa.CheckConstraint("version > 0", name="provider_routing_version_positive"),
    )

    op.create_table(
        "provider_routing_policy_routes",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "policy_revision_id",
            uuid,
            sa.ForeignKey("provider_routing_policy_revisions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "capability_id",
            uuid,
            sa.ForeignKey("provider_capabilities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "policy_revision_id", "position", name="uq_provider_route_position"
        ),
        sa.UniqueConstraint(
            "policy_revision_id", "capability_id", name="uq_provider_route_capability"
        ),
        sa.CheckConstraint("position >= 0", name="provider_route_position_nonnegative"),
    )

    op.create_table(
        "provider_routing_fallback_reasons",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "policy_revision_id",
            uuid,
            sa.ForeignKey("provider_routing_policy_revisions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(64), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "policy_revision_id", "reason", name="uq_provider_routing_fallback_reason"
        ),
        sa.CheckConstraint(
            "reason IN ('rate_limited','timeout','transport','provider_unavailable',"
            "'malformed_response','structured_output')",
            name="provider_routing_fallback_reason_value",
        ),
    )

    op.create_table(
        "provider_routing_policy_heads",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("scope_key", sa.String(80), nullable=False),
        sa.Column("workload_class", sa.String(32), nullable=False),
        sa.Column(
            "policy_revision_id",
            uuid,
            sa.ForeignKey("provider_routing_policy_revisions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
        sa.UniqueConstraint(
            "scope_key", "workload_class", name="uq_provider_routing_head_scope"
        ),
        sa.CheckConstraint(
            "workload_class IN ('chat_generation','embedding')",
            name="provider_routing_head_workload",
        ),
        sa.CheckConstraint(
            "lock_version > 0", name="provider_routing_head_lock_version"
        ),
    )

    op.create_table(
        "provider_work_policy_snapshots",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("source_key", sa.String(96), nullable=False),
        sa.Column(
            "planning_job_id",
            uuid,
            sa.ForeignKey("response_planning_jobs.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "summary_job_id",
            uuid,
            sa.ForeignKey("conversation_summary_jobs.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "semantic_index_job_id",
            uuid,
            sa.ForeignKey(
                "explicit_memory_semantic_index_jobs.id", ondelete="RESTRICT"
            ),
        ),
        sa.Column("workload_class", sa.String(32), nullable=False),
        sa.Column(
            "policy_revision_id",
            uuid,
            sa.ForeignKey("provider_routing_policy_revisions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            uuid,
            sa.ForeignKey("control_tenants.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "assistant_id", uuid, sa.ForeignKey("assistants.id", ondelete="RESTRICT")
        ),
        sa.Column(
            "connection_id",
            uuid,
            sa.ForeignKey("platform_connections.id", ondelete="RESTRICT"),
        ),
        *_timestamps(),
        sa.UniqueConstraint(
            "source_key", "workload_class", name="uq_provider_work_snapshot_source"
        ),
        sa.CheckConstraint(
            "num_nonnulls(planning_job_id, summary_job_id, semantic_index_job_id) = 1",
            name="provider_work_snapshot_one_source",
        ),
        sa.CheckConstraint(
            "workload_class IN ('chat_generation','embedding')",
            name="provider_work_snapshot_workload",
        ),
    )

    op.create_table(
        "provider_price_revisions",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "capability_id",
            uuid,
            sa.ForeignKey("provider_capabilities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("unit_basis", sa.String(32), nullable=False),
        sa.Column("input_rate", sa.BigInteger()),
        sa.Column("output_rate", sa.BigInteger()),
        sa.Column("request_rate", sa.BigInteger()),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True)),
        sa.Column(
            "created_by_identity_id",
            uuid,
            sa.ForeignKey("control_operator_identities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        *_timestamps(),
        sa.UniqueConstraint(
            "capability_id",
            "currency",
            "unit_basis",
            "effective_from",
            name="uq_provider_price_effective",
        ),
        sa.CheckConstraint("currency = 'USD'", name="provider_price_currency"),
        sa.CheckConstraint(
            "unit_basis IN ('generation_tokens','embedding_request')",
            name="provider_price_unit_basis",
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="provider_price_effective_range",
        ),
        sa.CheckConstraint(
            "input_rate IS NULL OR input_rate >= 0", name="provider_price_input_rate"
        ),
        sa.CheckConstraint(
            "output_rate IS NULL OR output_rate >= 0", name="provider_price_output_rate"
        ),
        sa.CheckConstraint(
            "request_rate IS NULL OR request_rate >= 0",
            name="provider_price_request_rate",
        ),
        sa.CheckConstraint(
            "(unit_basis = 'generation_tokens' AND input_rate IS NOT NULL AND "
            "output_rate IS NOT NULL AND request_rate IS NULL) OR "
            "(unit_basis = 'embedding_request' AND input_rate IS NULL AND "
            "output_rate IS NULL AND request_rate IS NOT NULL)",
            name="provider_price_shape",
        ),
    )
    op.execute(
        "ALTER TABLE provider_price_revisions ADD CONSTRAINT "
        "provider_price_no_overlap EXCLUDE USING gist "
        "(capability_id WITH =, currency WITH =, unit_basis WITH =, "
        "tstzrange(effective_from, effective_to, '[)') WITH &&)"
    )

    op.create_table(
        "provider_budgets",
        sa.Column("id", uuid, primary_key=True),
        *_scope_columns(uuid),
        sa.Column("workload_class", sa.String(32), nullable=False),
        sa.Column("measurement", sa.String(32), nullable=False),
        sa.Column("window_kind", sa.String(32), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "scope_key",
            "workload_class",
            "measurement",
            "window_kind",
            name="uq_provider_budget_identity",
        ),
        sa.CheckConstraint(SCOPE_SHAPE, name="provider_budget_scope_shape"),
        sa.CheckConstraint(
            "workload_class IN ('chat_generation','embedding')",
            name="provider_budget_workload",
        ),
        sa.CheckConstraint(
            "measurement IN ('estimated_cost_microusd','input_tokens','output_tokens',"
            "'total_tokens','requests')",
            name="provider_budget_measurement",
        ),
        sa.CheckConstraint(
            "window_kind IN ('daily_utc','monthly_utc')",
            name="provider_budget_window_kind",
        ),
    )

    op.create_table(
        "provider_budget_revisions",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "budget_id",
            uuid,
            sa.ForeignKey("provider_budgets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("alert_threshold_bps", sa.Integer(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_by_identity_id",
            uuid,
            sa.ForeignKey("control_operator_identities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        *_timestamps(),
        sa.UniqueConstraint(
            "budget_id", "version", name="uq_provider_budget_revision_version"
        ),
        sa.CheckConstraint("version > 0", name="provider_budget_version_positive"),
        sa.CheckConstraint("amount > 0", name="provider_budget_amount_positive"),
        sa.CheckConstraint("mode IN ('hard','soft')", name="provider_budget_mode"),
        sa.CheckConstraint(
            "alert_threshold_bps BETWEEN 0 AND 10000",
            name="provider_budget_alert_threshold",
        ),
    )

    op.create_table(
        "provider_budget_heads",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "budget_id",
            uuid,
            sa.ForeignKey("provider_budgets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "budget_revision_id",
            uuid,
            sa.ForeignKey("provider_budget_revisions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
        sa.UniqueConstraint("budget_id", name="uq_provider_budget_heads_budget"),
        sa.CheckConstraint(
            "lock_version > 0", name="provider_budget_head_lock_version"
        ),
    )

    op.create_table(
        "provider_budget_windows",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "budget_id",
            uuid,
            sa.ForeignKey("provider_budgets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "reserved_amount", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "consumed_amount", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
        sa.UniqueConstraint(
            "budget_id", "window_start", name="uq_provider_budget_windows_start"
        ),
        sa.CheckConstraint(
            "window_end > window_start", name="provider_budget_window_range"
        ),
        sa.CheckConstraint(
            "reserved_amount >= 0 AND consumed_amount >= 0",
            name="provider_budget_window_nonnegative",
        ),
    )

    op.create_table(
        "provider_usage_attempts",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("attempt_key", sa.String(96), nullable=False),
        sa.Column("source_key", sa.String(96), nullable=False),
        sa.Column("record_origin", sa.String(32), nullable=False),
        sa.Column(
            "planning_job_id",
            uuid,
            sa.ForeignKey("response_planning_jobs.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "summary_job_id",
            uuid,
            sa.ForeignKey("conversation_summary_jobs.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "semantic_index_job_id",
            uuid,
            sa.ForeignKey(
                "explicit_memory_semantic_index_jobs.id", ondelete="RESTRICT"
            ),
        ),
        sa.Column("workload_class", sa.String(32), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("attempt_ordinal", sa.Integer(), nullable=False),
        sa.Column("route_role", sa.String(32), nullable=False),
        sa.Column(
            "capability_id",
            uuid,
            sa.ForeignKey("provider_capabilities.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "policy_snapshot_id",
            uuid,
            sa.ForeignKey("provider_work_policy_snapshots.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "price_revision_id",
            uuid,
            sa.ForeignKey("provider_price_revisions.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "health_policy_revision_id",
            uuid,
            sa.ForeignKey("provider_health_policy_revisions.id", ondelete="RESTRICT"),
        ),
        sa.Column("provider_id", sa.String(32), nullable=False),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column(
            "tenant_id",
            uuid,
            sa.ForeignKey("control_tenants.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "assistant_id", uuid, sa.ForeignKey("assistants.id", ondelete="RESTRICT")
        ),
        sa.Column(
            "connection_id",
            uuid,
            sa.ForeignKey("platform_connections.id", ondelete="RESTRICT"),
        ),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("provider_outcome", sa.String(32), nullable=False),
        sa.Column("application_outcome", sa.String(64)),
        sa.Column("error_category", sa.String(64)),
        sa.Column("retryable", sa.Boolean()),
        sa.Column("provider_request_id", sa.String(255)),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_tokens", sa.BigInteger()),
        sa.Column("output_tokens", sa.BigInteger()),
        sa.Column("total_tokens", sa.BigInteger()),
        sa.Column("usage_quality", sa.String(16), nullable=False),
        sa.Column("estimate_quality", sa.String(32), nullable=False),
        sa.Column("estimated_cost_microusd", sa.BigInteger()),
        sa.Column("reserved_at", sa.DateTime(timezone=True)),
        sa.Column("reservation_owner", sa.String(255)),
        sa.Column("reservation_expires_at", sa.DateTime(timezone=True)),
        sa.Column("io_started_at", sa.DateTime(timezone=True)),
        sa.Column("io_completed_at", sa.DateTime(timezone=True)),
        sa.Column("finalized_at", sa.DateTime(timezone=True)),
        sa.Column("recovery_reason", sa.String(64)),
        *_timestamps(),
        sa.UniqueConstraint("attempt_key", name="uq_provider_usage_attempt_key"),
        sa.UniqueConstraint(
            "source_key",
            "operation",
            "attempt_ordinal",
            name="uq_provider_usage_source_operation_ordinal",
        ),
        sa.CheckConstraint(
            "num_nonnulls(planning_job_id, summary_job_id, semantic_index_job_id) = 1",
            name="provider_usage_attempt_one_source",
        ),
        sa.CheckConstraint(
            "record_origin IN ('legacy_backfill','governed')",
            name="provider_usage_record_origin",
        ),
        sa.CheckConstraint(
            "record_origin = 'legacy_backfill' OR "
            "(capability_id IS NOT NULL AND policy_snapshot_id IS NOT NULL)",
            name="provider_usage_governed_references",
        ),
        sa.CheckConstraint(
            "state IN ('no_io') OR record_origin = 'legacy_backfill' OR "
            "health_policy_revision_id IS NOT NULL",
            name="provider_usage_health_policy_reference",
        ),
        sa.CheckConstraint(
            "workload_class IN ('chat_generation','embedding')",
            name="provider_usage_workload",
        ),
        sa.CheckConstraint(
            "provider_id IN ('openai','gemini','groq','openrouter','ollama')",
            name="provider_usage_provider",
        ),
        sa.CheckConstraint(
            "operation IN ('response_planning','summary_generation','semantic_query',"
            "'semantic_index','semantic_rebuild')",
            name="provider_usage_operation",
        ),
        sa.CheckConstraint(
            "route_role IN ('primary','retry','correction','fallback')",
            name="provider_usage_route_role",
        ),
        sa.CheckConstraint(
            "state IN ('reserved','io_started','io_complete','no_io','io_possible')",
            name="provider_attempt_state",
        ),
        sa.CheckConstraint(
            "provider_outcome IN ('pending','success','refused','provider_error',"
            "'invalid_output','budget_denied','rate_limited','concurrency_limited',"
            "'no_eligible_route','governance_unavailable','recovered_no_io',"
            "'recovered_io_possible')",
            name="provider_attempt_outcome",
        ),
        sa.CheckConstraint(
            "usage_quality IN ('complete','partial','missing','invalid')",
            name="provider_usage_quality",
        ),
        sa.CheckConstraint(
            "(usage_quality IN ('missing','invalid') AND input_tokens IS NULL "
            "AND output_tokens IS NULL AND total_tokens IS NULL) OR "
            "(usage_quality = 'complete' AND input_tokens IS NOT NULL "
            "AND output_tokens IS NOT NULL AND (total_tokens IS NULL OR "
            "total_tokens = input_tokens + output_tokens)) OR "
            "(usage_quality = 'partial' "
            "AND num_nonnulls(input_tokens, output_tokens, total_tokens) > 0 "
            "AND NOT (input_tokens IS NOT NULL AND output_tokens IS NOT NULL))",
            name="provider_usage_quality_shape",
        ),
        sa.CheckConstraint(
            "estimate_quality IN "
            "('estimated','partial','reservation_estimate','unavailable')",
            name="provider_estimate_quality",
        ),
        sa.CheckConstraint(
            "application_outcome IS NULL OR application_outcome IN "
            "('accepted','refused','invalid_output')",
            name="provider_application_outcome",
        ),
        sa.CheckConstraint(
            "attempt_ordinal > 0", name="provider_attempt_ordinal_positive"
        ),
        sa.CheckConstraint(
            "request_count BETWEEN 0 AND 1", name="provider_attempt_request_count"
        ),
        sa.CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0", name="provider_usage_input"
        ),
        sa.CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0", name="provider_usage_output"
        ),
        sa.CheckConstraint(
            "total_tokens IS NULL OR total_tokens >= 0", name="provider_usage_total"
        ),
        sa.CheckConstraint(
            "estimated_cost_microusd IS NULL OR estimated_cost_microusd >= 0",
            name="provider_usage_cost",
        ),
        sa.CheckConstraint(
            "(estimate_quality = 'unavailable' "
            "AND estimated_cost_microusd IS NULL) OR "
            "(estimate_quality <> 'unavailable' "
            "AND estimated_cost_microusd IS NOT NULL)",
            name="provider_estimate_quality_shape",
        ),
        sa.CheckConstraint(
            "state <> 'no_io' OR (estimate_quality = 'unavailable' "
            "AND estimated_cost_microusd IS NULL)",
            name="provider_no_io_has_no_cost",
        ),
        sa.CheckConstraint(
            "(state IN ('reserved','io_started') AND provider_outcome = 'pending') OR "
            "(state = 'io_complete' AND provider_outcome IN "
            "('success','refused','provider_error','invalid_output')) OR "
            "(state = 'no_io' AND provider_outcome IN "
            "('budget_denied','rate_limited','concurrency_limited',"
            "'no_eligible_route','governance_unavailable','recovered_no_io')) OR "
            "(state = 'io_possible' "
            "AND provider_outcome = 'recovered_io_possible')",
            name="provider_attempt_state_outcome_shape",
        ),
        sa.CheckConstraint(
            "state <> 'reserved' OR "
            "(reserved_at IS NOT NULL AND reservation_owner IS NOT NULL "
            "AND reservation_expires_at IS NOT NULL AND request_count = 0 "
            "AND io_started_at IS NULL AND io_completed_at IS NULL)",
            name="provider_usage_reserved_lease_shape",
        ),
        sa.CheckConstraint(
            "(state IN ('reserved','no_io') AND request_count = 0) OR "
            "(state IN ('io_started','io_complete','io_possible') "
            "AND request_count = 1)",
            name="provider_usage_io_count_shape",
        ),
    )
    op.create_index(
        "ix_provider_usage_attempts_recovery",
        "provider_usage_attempts",
        ["state", "reservation_expires_at", "created_at", "id"],
    )
    op.create_index(
        "ix_provider_usage_attempts_aggregate",
        "provider_usage_attempts",
        ["workload_class", "created_at"],
    )

    op.create_table(
        "provider_budget_evaluations",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "attempt_id",
            uuid,
            sa.ForeignKey("provider_usage_attempts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "budget_id",
            uuid,
            sa.ForeignKey("provider_budgets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "budget_revision_id",
            uuid,
            sa.ForeignKey("provider_budget_revisions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "window_id",
            uuid,
            sa.ForeignKey("provider_budget_windows.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("limit_amount", sa.BigInteger(), nullable=False),
        sa.Column("reserved_before", sa.BigInteger(), nullable=False),
        sa.Column("consumed_before", sa.BigInteger(), nullable=False),
        sa.Column("requested_amount", sa.BigInteger()),
        *_timestamps(),
        sa.UniqueConstraint(
            "attempt_id", "budget_id", name="uq_provider_budget_evaluation_attempt"
        ),
        sa.CheckConstraint(
            "decision IN ('within','exceeded','denied','unavailable')",
            name="provider_budget_decision",
        ),
        sa.CheckConstraint(
            "limit_amount > 0 AND reserved_before >= 0 AND consumed_before >= 0 "
            "AND (requested_amount IS NULL OR requested_amount >= 0)",
            name="provider_budget_evaluation_amounts",
        ),
        sa.CheckConstraint(
            "(decision = 'unavailable' AND requested_amount IS NULL) OR "
            "(decision <> 'unavailable' AND requested_amount IS NOT NULL)",
            name="provider_budget_evaluation_unknown_shape",
        ),
    )

    op.create_table(
        "provider_budget_reservations",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "attempt_id",
            uuid,
            sa.ForeignKey("provider_usage_attempts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "budget_id",
            uuid,
            sa.ForeignKey("provider_budgets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "window_id",
            uuid,
            sa.ForeignKey("provider_budget_windows.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("reserved_amount", sa.BigInteger(), nullable=False),
        sa.Column(
            "reconciled_amount", sa.BigInteger(), nullable=False, server_default="0"
        ),
        *_timestamps(),
        sa.UniqueConstraint(
            "attempt_id", "budget_id", name="uq_provider_budget_reservation_attempt"
        ),
        sa.CheckConstraint(
            "state IN ('reserved','released','consumed','ambiguous')",
            name="provider_reservation_state",
        ),
        sa.CheckConstraint(
            "reserved_amount >= 0 AND reconciled_amount >= 0",
            name="provider_reservation_nonnegative",
        ),
    )

    op.execute(
        """
        WITH source AS (
          SELECT model_generation_attempts.*,
            CASE
              WHEN input_tokens IS NULL AND output_tokens IS NULL
                AND total_tokens IS NULL THEN 'missing'
              WHEN input_tokens < 0 OR output_tokens < 0 OR total_tokens < 0
                THEN 'invalid'
              WHEN input_tokens IS NOT NULL AND output_tokens IS NOT NULL
                AND total_tokens IS NOT NULL
                AND total_tokens <> input_tokens + output_tokens THEN 'invalid'
              WHEN input_tokens IS NOT NULL AND output_tokens IS NOT NULL
                THEN 'complete'
              ELSE 'partial'
            END AS normalized_usage_quality
          FROM model_generation_attempts
        )
        INSERT INTO provider_usage_attempts (
          id, attempt_key, source_key, record_origin, planning_job_id,
          workload_class, operation, attempt_ordinal, route_role,
          provider_id, model, state, provider_outcome, error_category, retryable,
          provider_request_id, request_count, input_tokens, output_tokens,
          total_tokens, usage_quality, estimate_quality, io_started_at,
          io_completed_at, finalized_at, created_at, updated_at
        )
        SELECT
          id, 'legacy:' || id::text, 'planning:' || planning_job_id::text,
          'legacy_backfill', planning_job_id, 'chat_generation',
          'response_planning', attempt_number, attempt_kind, provider, model,
          'io_complete',
          CASE status WHEN 'succeeded' THEN 'success' WHEN 'refused' THEN 'refused'
            ELSE 'provider_error' END,
          error_category, retryable, provider_request_id, 1,
          CASE WHEN normalized_usage_quality <> 'invalid' AND input_tokens >= 0
            THEN input_tokens ELSE NULL END,
          CASE WHEN normalized_usage_quality <> 'invalid' AND output_tokens >= 0
            THEN output_tokens ELSE NULL END,
          CASE WHEN normalized_usage_quality <> 'invalid' AND total_tokens >= 0
            THEN total_tokens ELSE NULL END,
          normalized_usage_quality,
          'unavailable', created_at, created_at, created_at, created_at, updated_at
        FROM source
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM provider_usage_attempts WHERE record_origin = 'governed'
          ) THEN
            RAISE EXCEPTION 'cannot downgrade SPEC-026 after governed provider I/O';
          END IF;
        END $$
        """
    )
    op.drop_table("provider_budget_reservations")
    op.drop_table("provider_budget_evaluations")
    op.drop_index(
        "ix_provider_usage_attempts_aggregate", table_name="provider_usage_attempts"
    )
    op.drop_index(
        "ix_provider_usage_attempts_recovery", table_name="provider_usage_attempts"
    )
    op.drop_table("provider_usage_attempts")
    op.drop_table("provider_budget_windows")
    op.drop_table("provider_budget_heads")
    op.drop_table("provider_budget_revisions")
    op.drop_table("provider_budgets")
    op.drop_table("provider_price_revisions")
    op.drop_table("provider_work_policy_snapshots")
    op.drop_table("provider_routing_policy_heads")
    op.drop_table("provider_routing_fallback_reasons")
    op.drop_table("provider_routing_policy_routes")
    op.drop_table("provider_routing_policy_revisions")
    op.drop_index(
        "ix_provider_health_events_capability_created",
        table_name="provider_health_events",
    )
    op.drop_table("provider_health_events")
    op.drop_table("provider_capability_states")
    op.drop_table("provider_health_policy_revisions")
    op.drop_table("provider_capabilities")
    op.drop_constraint(
        "uq_control_connection_bindings_connection",
        "control_connection_bindings",
        type_="unique",
    )
    op.drop_constraint(
        "uq_control_assistant_bindings_assistant",
        "control_assistant_bindings",
        type_="unique",
    )
