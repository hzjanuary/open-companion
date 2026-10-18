"""Add explicit personal context, recall policy, and mutation revisions.

Revision ID: 0018_user_controlled_memory
Revises: 0017_provider_routing_cost_budgets
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_user_controlled_memory"
down_revision: str | None = "0017_provider_routing_cost_budgets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM memory_items m
            JOIN participants p ON p.id = m.creator_participant_id
            WHERE p.conversation_id <> m.conversation_id
          ) THEN
            RAISE EXCEPTION 'cross-conversation memory creator blocks SPEC-027';
          END IF;
        END $$;
        """
    )
    op.create_unique_constraint(
        "uq_participants_id_conversation",
        "participants",
        ["id", "conversation_id"],
    )
    op.add_column("memory_items", sa.Column("context_key", sa.String(32)))
    op.add_column(
        "memory_items",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.drop_constraint("memory_explicit_scope", "memory_items", type_="check")
    op.create_check_constraint(
        "memory_kind_shape",
        "memory_items",
        "(kind = 'explicit_fact' AND context_key IS NULL "
        "AND visibility = 'same_conversation') OR "
        "(kind = 'personal_context' AND context_key IS NOT NULL "
        "AND context_key IN ('preferred_name','preferred_language',"
        "'response_preference','accessibility_preference','personal_note') "
        "AND visibility = 'creator_only' AND scope = 'private_conversation')",
    )
    op.create_check_constraint(
        "memory_revision_positive", "memory_items", "revision > 0"
    )
    op.create_foreign_key(
        "fk_memory_items_creator_conversation",
        "memory_items",
        "participants",
        ["creator_participant_id", "conversation_id"],
        ["id", "conversation_id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "uq_memory_items_active_personal_context_key",
        "memory_items",
        ["creator_participant_id", "conversation_id", "context_key"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND kind = 'personal_context'"),
    )
    op.create_index(
        "ix_memory_items_owner_scope",
        "memory_items",
        ["creator_participant_id", "conversation_id", "status"],
    )

    op.create_table(
        "memory_recall_policies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("assistant_id", sa.Uuid(), nullable=False),
        sa.Column("platform_connection_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("participant_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source_command_job_id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["assistant_id"], ["assistants.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["platform_connection_id"],
            ["platform_connections.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["participant_id"], ["participants.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["participant_id", "conversation_id"],
            ["participants.id", "participants.conversation_id"],
            name="fk_memory_recall_participant_conversation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_command_job_id"],
            ["telegram_command_jobs.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("participant_id", "conversation_id"),
        sa.CheckConstraint("revision > 0", name="memory_recall_revision_positive"),
    )
    op.create_index(
        "ix_memory_recall_policies_assistant_id",
        "memory_recall_policies",
        ["assistant_id"],
    )
    op.create_index(
        "ix_memory_recall_policies_platform_connection_id",
        "memory_recall_policies",
        ["platform_connection_id"],
    )
    op.create_index(
        "ix_memory_recall_policies_conversation_id",
        "memory_recall_policies",
        ["conversation_id"],
    )
    op.create_index(
        "ix_memory_recall_policies_participant_id",
        "memory_recall_policies",
        ["participant_id"],
    )

    op.create_table(
        "memory_control_operations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("command_job_id", sa.Uuid(), nullable=False),
        sa.Column("actor_participant_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("memory_id", sa.Uuid()),
        sa.Column("resulting_revision", sa.Integer()),
        sa.Column("affected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recall_enabled", sa.Boolean()),
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
        sa.ForeignKeyConstraint(
            ["command_job_id"], ["telegram_command_jobs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["actor_participant_id"], ["participants.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["memory_id"], ["memory_items.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("command_job_id"),
        sa.CheckConstraint(
            "operation IN ('remember','context_create','update','delete',"
            "'clear','recall_disable','recall_enable')",
            name="memory_control_operation_value",
        ),
        sa.CheckConstraint(
            "status IN ('in_progress','complete')",
            name="memory_control_operation_status",
        ),
        sa.CheckConstraint(
            "outcome IN ('created','updated','deleted','cleared','enabled',"
            "'disabled','unchanged','conflict','missing','denied',"
            "'scope_denied','limit_reached')",
            name="memory_control_operation_outcome",
        ),
        sa.CheckConstraint(
            "affected_count >= 0", name="memory_control_affected_nonnegative"
        ),
        sa.CheckConstraint(
            "resulting_revision IS NULL OR resulting_revision > 0",
            name="memory_control_revision_positive",
        ),
    )
    op.create_index(
        "ix_memory_control_operations_actor_participant_id",
        "memory_control_operations",
        ["actor_participant_id"],
    )
    op.create_index(
        "ix_memory_control_operations_conversation_id",
        "memory_control_operations",
        ["conversation_id"],
    )
    op.create_index(
        "ix_memory_control_operations_memory_id",
        "memory_control_operations",
        ["memory_id"],
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM memory_items WHERE kind = 'personal_context')
             OR EXISTS (SELECT 1 FROM memory_recall_policies)
             OR EXISTS (SELECT 1 FROM memory_control_operations) THEN
            RAISE EXCEPTION
              'SPEC-027 state exists; destructive downgrade is refused';
          END IF;
        END $$;
        """
    )
    op.drop_index(
        "ix_memory_control_operations_memory_id",
        table_name="memory_control_operations",
    )
    op.drop_index(
        "ix_memory_control_operations_conversation_id",
        table_name="memory_control_operations",
    )
    op.drop_index(
        "ix_memory_control_operations_actor_participant_id",
        table_name="memory_control_operations",
    )
    op.drop_table("memory_control_operations")
    op.drop_index(
        "ix_memory_recall_policies_participant_id",
        table_name="memory_recall_policies",
    )
    op.drop_index(
        "ix_memory_recall_policies_conversation_id",
        table_name="memory_recall_policies",
    )
    op.drop_index(
        "ix_memory_recall_policies_platform_connection_id",
        table_name="memory_recall_policies",
    )
    op.drop_index(
        "ix_memory_recall_policies_assistant_id",
        table_name="memory_recall_policies",
    )
    op.drop_table("memory_recall_policies")
    op.drop_index("ix_memory_items_owner_scope", table_name="memory_items")
    op.drop_index(
        "uq_memory_items_active_personal_context_key", table_name="memory_items"
    )
    op.drop_constraint(
        "fk_memory_items_creator_conversation", "memory_items", type_="foreignkey"
    )
    op.drop_constraint("memory_revision_positive", "memory_items", type_="check")
    op.drop_constraint("memory_kind_shape", "memory_items", type_="check")
    op.create_check_constraint(
        "memory_explicit_scope",
        "memory_items",
        "kind = 'explicit_fact' AND visibility = 'same_conversation'",
    )
    op.drop_column("memory_items", "revision")
    op.drop_column("memory_items", "context_key")
    op.drop_constraint(
        "uq_participants_id_conversation", "participants", type_="unique"
    )
