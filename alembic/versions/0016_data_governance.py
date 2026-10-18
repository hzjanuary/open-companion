"""Add SPEC-025 data governance surfaces.

Creates content-free export/erasure request tables, the temporary single-use
export package table, and the content-safe governance audit trail.

Revision ID: 0016_data_governance
Revises: 0015_safety_moderation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_data_governance"
down_revision: str | None = "0015_safety_moderation"
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


def upgrade() -> None:
    uuid = sa.Uuid()

    op.create_table(
        "control_deployment_authorities",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "identity_id",
            uuid,
            sa.ForeignKey("control_operator_identities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "authority",
            sa.String(32),
            nullable=False,
            server_default="deployment_operator",
        ),
        sa.Column(
            "granted_by_identity_id",
            uuid,
            sa.ForeignKey("control_operator_identities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "revoked_by_identity_id",
            uuid,
            sa.ForeignKey("control_operator_identities.id", ondelete="RESTRICT"),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.UniqueConstraint(
            "identity_id",
            "authority",
            name="uq_control_deployment_authorities_identity_authority",
        ),
        sa.CheckConstraint(
            "authority = 'deployment_operator'",
            name="control_deployment_authority_value",
        ),
    )
    op.create_index(
        "ix_control_deployment_authorities_identity",
        "control_deployment_authorities",
        ["identity_id"],
    )
    op.create_table(
        "control_deployment_authority_operations",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "actor_identity_id",
            uuid,
            sa.ForeignKey("control_operator_identities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "target_identity_id",
            uuid,
            sa.ForeignKey("control_operator_identities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("changed", sa.Boolean(), nullable=False),
        sa.Column("resulting_active", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "actor_identity_id",
            "operation",
            "request_id",
            name="uq_control_deployment_authority_operations_request",
        ),
        sa.CheckConstraint(
            "operation IN ('grant', 'revoke')",
            name="control_deployment_authority_operation_value",
        ),
    )
    op.create_index(
        "ix_control_deployment_authority_operations_actor",
        "control_deployment_authority_operations",
        ["actor_identity_id"],
    )
    op.alter_column(
        "control_audit_events",
        "tenant_id",
        existing_type=uuid,
        nullable=True,
    )
    op.alter_column(
        "control_audit_events",
        "request_id",
        existing_type=sa.String(100),
        type_=sa.String(128),
        existing_nullable=False,
    )

    op.create_table(
        "governance_export_requests",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column(
            "conversation_id",
            uuid,
            sa.ForeignKey("conversations.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "participant_id",
            uuid,
            sa.ForeignKey("participants.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "tenant_id",
            uuid,
            sa.ForeignKey("control_tenants.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="requested",
        ),
        sa.Column(
            "categories",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("single_use_token_hash", sa.String(64)),
        sa.Column(
            "source_command_job_id",
            uuid,
            sa.ForeignKey("telegram_command_jobs.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "source_control_identity_id",
            uuid,
            sa.ForeignKey("control_operator_identities.id", ondelete="RESTRICT"),
        ),
        sa.Column("source_control_request_id", sa.String(128)),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_owner", sa.String(255)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("retrieved_at", sa.DateTime(timezone=True)),
        sa.Column("failure_reason", sa.String(64)),
        *_timestamps(),
        sa.CheckConstraint(
            "(source_control_identity_id IS NULL) = "
            "(source_control_request_id IS NULL)",
            name="governance_export_control_source_pair",
        ),
        sa.CheckConstraint(
            "NOT (source_command_job_id IS NOT NULL AND "
            "source_control_identity_id IS NOT NULL)",
            name="governance_export_single_source",
        ),
    )
    op.create_unique_constraint(
        "uq_governance_export_requests_token",
        "governance_export_requests",
        ["single_use_token_hash"],
    )
    op.create_unique_constraint(
        "uq_governance_export_requests_source_command",
        "governance_export_requests",
        ["source_command_job_id"],
    )
    op.create_unique_constraint(
        "uq_governance_export_requests_source_control",
        "governance_export_requests",
        ["source_control_identity_id", "source_control_request_id"],
    )
    op.create_index(
        "ix_governance_export_requests_status_available",
        "governance_export_requests",
        ["status", "available_at"],
    )
    op.create_index(
        "ix_governance_export_requests_scope_subject",
        "governance_export_requests",
        ["scope", "conversation_id", "participant_id"],
    )

    op.create_table(
        "governance_export_packages",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "export_request_id",
            uuid,
            sa.ForeignKey("governance_export_requests.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column(
            "manifest",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "package",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True)),
        sa.Column("cleared_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_index(
        "ix_governance_export_packages_request",
        "governance_export_packages",
        ["export_request_id"],
    )

    op.create_table(
        "governance_erasure_requests",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("scope", sa.String(16), nullable=False, server_default="subject"),
        sa.Column(
            "conversation_id",
            uuid,
            sa.ForeignKey("conversations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "participant_id",
            uuid,
            sa.ForeignKey("participants.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="requested",
        ),
        sa.Column("partial_reason", sa.String(64)),
        sa.Column(
            "source_command_job_id",
            uuid,
            sa.ForeignKey("telegram_command_jobs.id", ondelete="RESTRICT"),
        ),
        sa.Column("lease_owner", sa.String(255)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "requested_via",
            sa.String(32),
            nullable=False,
            server_default="telegram_command",
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_index(
        "ix_governance_erasure_requests_scope_subject",
        "governance_erasure_requests",
        ["scope", "conversation_id", "participant_id"],
    )
    op.create_unique_constraint(
        "uq_governance_erasure_requests_source_command",
        "governance_erasure_requests",
        ["source_command_job_id"],
    )

    op.create_table(
        "governance_audit_events",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("request_id", sa.String(100)),
        sa.Column(
            "conversation_id",
            uuid,
            sa.ForeignKey("conversations.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "participant_id",
            uuid,
            sa.ForeignKey("participants.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "tenant_id",
            uuid,
            sa.ForeignKey("control_tenants.id", ondelete="RESTRICT"),
        ),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("detail", sa.String(128)),
        sa.Column(
            "metadata",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        *_timestamps(),
    )
    op.create_index(
        "ix_governance_audit_events_conversation",
        "governance_audit_events",
        ["conversation_id"],
    )
    op.create_unique_constraint(
        "uq_governance_audit_events_request_event",
        "governance_audit_events",
        ["request_id", "event_type"],
    )

    op.add_column(
        "outbound_actions",
        sa.Column(
            "governance_export_request_id",
            uuid,
            sa.ForeignKey("governance_export_requests.id", ondelete="RESTRICT"),
        ),
    )
    op.create_unique_constraint(
        "uq_outbound_actions_governance_export_request",
        "outbound_actions",
        ["governance_export_request_id"],
    )
    op.create_index(
        "ix_governance_audit_events_tenant",
        "governance_audit_events",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_outbound_actions_governance_export_request",
        "outbound_actions",
        type_="unique",
    )
    op.drop_column("outbound_actions", "governance_export_request_id")
    op.drop_constraint(
        "uq_governance_audit_events_request_event",
        "governance_audit_events",
        type_="unique",
    )
    op.drop_index(
        "ix_governance_audit_events_tenant", table_name="governance_audit_events"
    )
    op.drop_index(
        "ix_governance_audit_events_conversation",
        table_name="governance_audit_events",
    )
    op.drop_table("governance_audit_events")
    op.drop_index(
        "ix_governance_erasure_requests_scope_subject",
        table_name="governance_erasure_requests",
    )
    op.drop_constraint(
        "uq_governance_erasure_requests_source_command",
        "governance_erasure_requests",
        type_="unique",
    )
    op.drop_table("governance_erasure_requests")
    op.drop_index(
        "ix_governance_export_packages_request",
        table_name="governance_export_packages",
    )
    op.drop_table("governance_export_packages")
    op.drop_index(
        "ix_governance_export_requests_scope_subject",
        table_name="governance_export_requests",
    )
    op.drop_index(
        "ix_governance_export_requests_status_available",
        table_name="governance_export_requests",
    )
    op.drop_constraint(
        "uq_governance_export_requests_source_command",
        "governance_export_requests",
        type_="unique",
    )
    op.drop_constraint(
        "uq_governance_export_requests_source_control",
        "governance_export_requests",
        type_="unique",
    )
    op.drop_constraint(
        "uq_governance_export_requests_token",
        "governance_export_requests",
        type_="unique",
    )
    op.drop_table("governance_export_requests")
    op.execute("DELETE FROM control_audit_events WHERE tenant_id IS NULL")
    op.alter_column(
        "control_audit_events",
        "tenant_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
    op.alter_column(
        "control_audit_events",
        "request_id",
        existing_type=sa.String(128),
        type_=sa.String(100),
        existing_nullable=False,
        postgresql_using="left(request_id, 100)",
    )
    op.drop_index(
        "ix_control_deployment_authority_operations_actor",
        table_name="control_deployment_authority_operations",
    )
    op.drop_table("control_deployment_authority_operations")
    op.drop_index(
        "ix_control_deployment_authorities_identity",
        table_name="control_deployment_authorities",
    )
    op.drop_table("control_deployment_authorities")
