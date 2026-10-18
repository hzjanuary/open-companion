"""Add durable explicit-memory semantic-index work.

Revision ID: 0013_semantic_memory_index
Revises: 0012_conversation_summaries
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_semantic_memory_index"
down_revision: str | None = "0012_conversation_summaries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "explicit_memory_semantic_index_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "memory_id", sa.Uuid(), sa.ForeignKey("memory_items.id"), nullable=False
        ),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("embedding_version", sa.String(64), nullable=False),
        sa.Column("target_collection", sa.String(128)),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_owner", sa.String(255)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_category", sa.String(64)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
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
        sa.UniqueConstraint("memory_id", "operation", "embedding_version"),
    )
    op.create_index(
        "ix_semantic_memory_jobs_claim",
        "explicit_memory_semantic_index_jobs",
        ["status", "available_at", "created_at"],
    )
    op.create_index(
        "ix_semantic_memory_jobs_lease",
        "explicit_memory_semantic_index_jobs",
        ["status", "lease_expires_at"],
    )
    op.create_index(
        "ix_explicit_memory_semantic_index_jobs_memory_id",
        "explicit_memory_semantic_index_jobs",
        ["memory_id"],
    )
    op.create_table(
        "explicit_memory_semantic_index_collections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("embedding_version", sa.String(64), nullable=False),
        sa.Column("collection_name", sa.String(128), nullable=False),
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
        sa.UniqueConstraint("embedding_version"),
    )


def downgrade() -> None:
    # Allow local pre-release databases that ran an earlier draft of this
    # uncommitted revision to complete the required downgrade rehearsal.
    op.execute("DROP TABLE IF EXISTS explicit_memory_semantic_index_collections")
    op.drop_index(
        "ix_explicit_memory_semantic_index_jobs_memory_id",
        table_name="explicit_memory_semantic_index_jobs",
    )
    op.drop_index(
        "ix_semantic_memory_jobs_lease",
        table_name="explicit_memory_semantic_index_jobs",
    )
    op.drop_index(
        "ix_semantic_memory_jobs_claim",
        table_name="explicit_memory_semantic_index_jobs",
    )
    op.drop_table("explicit_memory_semantic_index_jobs")
