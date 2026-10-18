"""Add durable bounded conversation summaries.

Revision ID: 0012_conversation_summaries
Revises: 0011_ambient_participation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_conversation_summaries"
down_revision: str | None = "0011_ambient_participation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation_summaries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversations.id"),
            nullable=False,
        ),
        sa.Column("platform_thread_id", sa.String(255)),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(32)),
        sa.Column("model", sa.String(255)),
        sa.Column(
            "source_first_message_id",
            sa.Uuid(),
            sa.ForeignKey("messages.id"),
            nullable=False,
        ),
        sa.Column(
            "source_last_message_id",
            sa.Uuid(),
            sa.ForeignKey("messages.id"),
            nullable=False,
        ),
        sa.Column("source_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=False),
        sa.Column("source_window_hash", sa.String(64), nullable=False),
        sa.Column("summary_text", sa.Text()),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("invalidated_at", sa.DateTime(timezone=True)),
        sa.Column("invalidation_reason", sa.String(64)),
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
        sa.UniqueConstraint("conversation_id", "source_window_hash", "schema_version"),
    )
    op.create_index(
        "ix_conversation_summaries_active",
        "conversation_summaries",
        ["conversation_id", "platform_thread_id", "status", "expires_at"],
    )
    op.create_index(
        "ix_conversation_summaries_expiry",
        "conversation_summaries",
        ["status", "expires_at"],
    )
    op.create_table(
        "conversation_summary_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversations.id"),
            nullable=False,
        ),
        sa.Column("platform_thread_id", sa.String(255)),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column(
            "source_first_message_id",
            sa.Uuid(),
            sa.ForeignKey("messages.id"),
            nullable=False,
        ),
        sa.Column(
            "source_last_message_id",
            sa.Uuid(),
            sa.ForeignKey("messages.id"),
            nullable=False,
        ),
        sa.Column("source_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=False),
        sa.Column("source_window_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_owner", sa.String(255)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_category", sa.String(64)),
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
        sa.UniqueConstraint("conversation_id", "source_window_hash", "schema_version"),
    )
    op.create_index(
        "ix_conversation_summary_jobs_claim",
        "conversation_summary_jobs",
        ["status", "available_at", "created_at"],
    )
    op.create_index(
        "ix_conversation_summary_jobs_lease",
        "conversation_summary_jobs",
        ["status", "lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversation_summary_jobs_lease", table_name="conversation_summary_jobs"
    )
    op.drop_index(
        "ix_conversation_summary_jobs_claim", table_name="conversation_summary_jobs"
    )
    op.drop_table("conversation_summary_jobs")
    op.drop_index(
        "ix_conversation_summaries_expiry", table_name="conversation_summaries"
    )
    op.drop_index(
        "ix_conversation_summaries_active", table_name="conversation_summaries"
    )
    op.drop_table("conversation_summaries")
