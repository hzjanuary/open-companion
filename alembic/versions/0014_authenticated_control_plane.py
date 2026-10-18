"""Add the SPEC-021 authenticated operator control-plane state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0014_authenticated_control_plane"
down_revision: str | None = "0013_semantic_memory_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    uuid = sa.Uuid()

    def timestamps() -> list[sa.Column[object]]:
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

    op.create_table(
        "control_tenants",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        *timestamps(),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "control_operator_identities",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("issuer", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255)),
        sa.Column("email", sa.String(320)),
        sa.Column("disabled_at", sa.DateTime(timezone=True)),
        *timestamps(),
        sa.UniqueConstraint("issuer", "subject"),
    )
    op.create_table(
        "control_operator_memberships",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "tenant_id",
            uuid,
            sa.ForeignKey("control_tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "identity_id",
            uuid,
            sa.ForeignKey("control_operator_identities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True)),
        *timestamps(),
        sa.UniqueConstraint("tenant_id", "identity_id"),
    )
    op.create_table(
        "control_assistant_bindings",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "tenant_id",
            uuid,
            sa.ForeignKey("control_tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "assistant_id",
            uuid,
            sa.ForeignKey("assistants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        *timestamps(),
        sa.UniqueConstraint("tenant_id", "assistant_id"),
    )
    op.create_table(
        "control_connection_bindings",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "tenant_id",
            uuid,
            sa.ForeignKey("control_tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "connection_id",
            uuid,
            sa.ForeignKey("platform_connections.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        *timestamps(),
        sa.UniqueConstraint("tenant_id", "connection_id"),
    )
    op.create_table(
        "control_group_bindings",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "tenant_id",
            uuid,
            sa.ForeignKey("control_tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "connection_id",
            uuid,
            sa.ForeignKey("platform_connections.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("external_group_id", sa.String(255), nullable=False),
        sa.Column("title", sa.String(255)),
        sa.Column(
            "settings", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("current_revision", sa.Integer(), nullable=False, server_default="0"),
        *timestamps(),
        sa.UniqueConstraint("tenant_id", "connection_id", "external_group_id"),
    )
    op.create_table(
        "control_group_configuration_revisions",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "group_id",
            uuid,
            sa.ForeignKey("control_group_bindings.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("parent_revision", sa.Integer()),
        sa.Column("settings", JSONB, nullable=False),
        sa.Column(
            "actor_identity_id",
            uuid,
            sa.ForeignKey("control_operator_identities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(255)),
        *timestamps(),
        sa.UniqueConstraint("group_id", "revision"),
    )
    op.create_table(
        "control_audit_events",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "tenant_id",
            uuid,
            sa.ForeignKey("control_tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "actor_identity_id",
            uuid,
            sa.ForeignKey("control_operator_identities.id", ondelete="RESTRICT"),
        ),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("resource_type", sa.String(80), nullable=False),
        sa.Column("resource_id", sa.String(255)),
        sa.Column("request_id", sa.String(100), nullable=False),
        sa.Column(
            "metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        *timestamps(),
    )
    op.create_table(
        "control_idempotency_keys",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "tenant_id",
            uuid,
            sa.ForeignKey("control_tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "identity_id",
            uuid,
            sa.ForeignKey("control_operator_identities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("operation", sa.String(120), nullable=False),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("response_body", JSONB, nullable=False),
        *timestamps(),
        sa.UniqueConstraint("tenant_id", "identity_id", "operation", "key"),
    )
    for table, columns in (
        ("control_operator_memberships", ["tenant_id", "identity_id"]),
        ("control_assistant_bindings", ["tenant_id", "assistant_id"]),
        ("control_connection_bindings", ["tenant_id", "connection_id"]),
        ("control_group_bindings", ["tenant_id", "connection_id", "external_group_id"]),
        ("control_group_configuration_revisions", ["group_id"]),
        ("control_audit_events", ["tenant_id"]),
        ("control_idempotency_keys", ["tenant_id", "identity_id"]),
    ):
        op.create_index(f"ix_{table}_{columns[0]}", table, columns)


def downgrade() -> None:
    for table in (
        "control_idempotency_keys",
        "control_audit_events",
        "control_group_configuration_revisions",
        "control_group_bindings",
        "control_connection_bindings",
        "control_assistant_bindings",
        "control_operator_memberships",
        "control_operator_identities",
        "control_tenants",
    ):
        op.drop_table(table)
