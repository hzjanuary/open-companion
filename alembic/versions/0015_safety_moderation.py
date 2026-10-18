"""Add SPEC-024 safety moderation protection state and review queue.

Revision ID: 0015_safety_moderation
Revises: 0014_authenticated_control_plane
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_safety_moderation"
down_revision: str | None = "0014_authenticated_control_plane"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    uuid = sa.Uuid()

    op.add_column(
        "participants",
        sa.Column(
            "protected_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "conversation_configuration_revisions",
        sa.Column(
            "safety_level",
            sa.String(32),
            nullable=False,
            server_default="standard",
        ),
    )
    op.add_column(
        "conversation_configuration_revisions",
        sa.Column(
            "teasing_cap",
            sa.Integer(),
            nullable=False,
            server_default="3",
        ),
    )
    op.create_table(
        "safety_review_items",
        sa.Column("id", uuid, primary_key=True),
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
        sa.Column("category", sa.String(48), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column(
            "outcome_counts",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "protection_state",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "status", sa.String(32), nullable=False, server_default="open"
        ),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("escalated_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("action", sa.String(32)),
        sa.Column("protection_action", sa.String(32)),
        sa.Column(
            "actor_participant_id",
            uuid,
            sa.ForeignKey("participants.id", ondelete="RESTRICT"),
        ),
        sa.Column("actioned_at", sa.DateTime(timezone=True)),
        sa.Column("source", sa.String(64)),
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
    )
    op.create_index(
        "ix_safety_review_items_conversation",
        "safety_review_items",
        ["conversation_id"],
    )
    op.create_index(
        "ix_safety_review_items_status", "safety_review_items", ["status"]
    )
    op.create_index(
        "ix_safety_review_items_created_at",
        "safety_review_items",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_safety_review_items_created_at", table_name="safety_review_items")
    op.drop_index("ix_safety_review_items_status", table_name="safety_review_items")
    op.drop_index("ix_safety_review_items_conversation", table_name="safety_review_items")
    op.drop_table("safety_review_items")
    op.drop_column("conversation_configuration_revisions", "teasing_cap")
    op.drop_column("conversation_configuration_revisions", "safety_level")
    op.drop_column("participants", "protected_at")
