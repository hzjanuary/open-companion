"""Add durable, content-free recovery classification and history.

Revision ID: 0010_operational_recovery
Revises: 0009_safety_rate_limiting
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_operational_recovery"
down_revision: str | None = "0009_safety_rate_limiting"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "operational_recovery_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("work_kind", sa.String(32), nullable=False),
        sa.Column("work_id", sa.Uuid(), nullable=False),
        sa.Column("disposition", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(64), nullable=False),
        sa.Column("replayed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("work_kind", "work_id"),
    )
    op.create_index("ix_operational_recovery_items_disposition", "operational_recovery_items", ["disposition", "created_at"])
    op.create_table(
        "operational_recovery_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recovery_item_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["recovery_item_id"], ["operational_recovery_items.id"], ondelete="RESTRICT"), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_operational_recovery_events_item", "operational_recovery_events", ["recovery_item_id"])


def downgrade() -> None:
    op.drop_index("ix_operational_recovery_events_item", table_name="operational_recovery_events")
    op.drop_table("operational_recovery_events")
    op.drop_index("ix_operational_recovery_items_disposition", table_name="operational_recovery_items")
    op.drop_table("operational_recovery_items")
