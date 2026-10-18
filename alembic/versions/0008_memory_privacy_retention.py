"""Add explicit conversation-scoped memory storage.

Revision ID: 0008_memory_privacy_retention
Revises: 0007_telegram_commands
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_memory_privacy_retention"
down_revision: str | None = "0007_telegram_commands"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "telegram_command_jobs",
        "arguments",
        existing_type=sa.String(160),
        type_=sa.String(500),
    )
    op.drop_constraint(
        "command_arguments_length",
        "telegram_command_jobs",
        type_="check",
    )
    op.create_check_constraint(
        "command_arguments_length",
        "telegram_command_jobs",
        "length(arguments) <= 500",
    )
    op.add_column(
        "participants", sa.Column("privacy_deleted_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "conversations",
        sa.Column(
            "memory_privacy_revision",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    for table, column in (
        ("messages", "content_redacted_at"),
        ("incoming_platform_updates", "payload_redacted_at"),
        ("telegram_command_jobs", "arguments_redacted_at"),
        ("response_plans", "content_redacted_at"),
        ("outbound_actions", "payload_redacted_at"),
    ):
        op.add_column(table, sa.Column(column, sa.DateTime(timezone=True)))
    op.drop_constraint(
        "outbound_action_payload",
        "outbound_actions",
        type_="check",
    )
    op.create_check_constraint(
        "outbound_action_payload",
        "outbound_actions",
        "(payload_redacted_at IS NOT NULL AND text IS NULL AND sticker_intent IS NULL) "
        "OR (kind = 'text' AND text IS NOT NULL AND btrim(text) <> '' "
        "AND sticker_intent IS NULL) OR (kind = 'sticker' AND text IS NULL "
        "AND sticker_intent IS NOT NULL)",
    )
    op.create_table(
        "memory_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("public_id", sa.String(24), nullable=False),
        sa.Column("assistant_id", sa.Uuid(), nullable=False),
        sa.Column("platform_connection_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("creator_participant_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("visibility", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("content", sa.Text()),
        sa.Column("normalized_content_hash", sa.String(64)),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source_message_id", sa.Uuid(), nullable=False),
        sa.Column("source_command_job_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("deletion_reason", sa.String(32)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["assistant_id"], ["assistants.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["platform_connection_id"], ["platform_connections.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["creator_participant_id"], ["participants.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_message_id"], ["messages.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_command_job_id"], ["telegram_command_jobs.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint("source_command_job_id"),
        sa.CheckConstraint("confidence = 1.0", name="memory_explicit_confidence"),
        sa.CheckConstraint(
            "status <> 'active' OR content IS NOT NULL AND length(content) > 0",
            name="memory_active_content",
        ),
        sa.CheckConstraint(
            "status = 'active' OR content IS NULL AND normalized_content_hash IS NULL",
            name="memory_redacted_content",
        ),
        sa.CheckConstraint(
            "kind = 'explicit_fact' AND visibility = 'same_conversation'",
            name="memory_explicit_scope",
        ),
    )
    op.create_index(
        "ix_memory_items_active_conversation",
        "memory_items",
        ["conversation_id", "status"],
    )
    op.create_table(
        "memory_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("memory_id", sa.Uuid()),
        sa.Column("command_job_id", sa.Uuid()),
        sa.Column("actor_participant_id", sa.Uuid()),
        sa.Column("action_code", sa.String(64), nullable=False),
        sa.Column("deletion_reason", sa.String(32)),
        sa.Column("affected_count", sa.Integer()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["memory_id"], ["memory_items.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["command_job_id"], ["telegram_command_jobs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["actor_participant_id"], ["participants.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("memory_events")
    op.drop_constraint(
        "outbound_action_payload",
        "outbound_actions",
        type_="check",
    )
    # SPEC-007 cannot represent a physically redacted action. Preserve the
    # row and idempotency key with a non-secret tombstone before its check returns.
    op.execute(
        "UPDATE outbound_actions SET kind = 'text', text = '[redacted]', "
        "sticker_intent = NULL WHERE payload_redacted_at IS NOT NULL"
    )
    op.create_check_constraint(
        "outbound_action_payload",
        "outbound_actions",
        "(kind = 'text' AND text IS NOT NULL AND btrim(text) <> '' "
        "AND sticker_intent IS NULL) OR (kind = 'sticker' AND text IS NULL "
        "AND sticker_intent IS NOT NULL)",
    )
    op.drop_constraint(
        "command_arguments_length",
        "telegram_command_jobs",
        type_="check",
    )
    op.execute(
        "UPDATE telegram_command_jobs SET arguments = left(arguments, 160) "
        "WHERE length(arguments) > 160"
    )
    op.create_check_constraint(
        "command_arguments_length",
        "telegram_command_jobs",
        "length(arguments) <= 160",
    )
    op.alter_column(
        "telegram_command_jobs",
        "arguments",
        existing_type=sa.String(500),
        type_=sa.String(160),
    )
    op.drop_column("participants", "privacy_deleted_at")
    op.drop_column("conversations", "memory_privacy_revision")
    for table, column in (
        ("outbound_actions", "payload_redacted_at"),
        ("response_plans", "content_redacted_at"),
        ("telegram_command_jobs", "arguments_redacted_at"),
        ("incoming_platform_updates", "payload_redacted_at"),
        ("messages", "content_redacted_at"),
    ):
        op.drop_column(table, column)
    op.drop_index("ix_memory_items_active_conversation", table_name="memory_items")
    op.drop_table("memory_items")
