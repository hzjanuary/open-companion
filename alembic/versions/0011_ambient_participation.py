"""Add typed ambient participation configuration and delivery origin.

Revision ID: 0011_ambient_participation
Revises: 0010_operational_recovery
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_ambient_participation"
down_revision: str | None = "0010_operational_recovery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversation_configuration_revisions",
        sa.Column(
            "ambient_frequency",
            sa.String(16),
            nullable=False,
            server_default="normal",
        ),
    )
    op.add_column(
        "response_planning_jobs",
        sa.Column("trigger", sa.String(16), nullable=False, server_default="addressed"),
    )
    op.add_column(
        "response_planning_jobs",
        sa.Column("ambient_policy_version", sa.String(64)),
    )
    op.add_column("response_planning_jobs", sa.Column("ambient_reason", sa.String(64)))
    op.add_column(
        "outbound_actions",
        sa.Column("origin", sa.String(16), nullable=False, server_default="addressed"),
    )
    op.create_index(
        "ix_outbound_actions_ambient_confirmed",
        "outbound_actions",
        ["conversation_id", "origin", "status", "completed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_outbound_actions_ambient_confirmed", table_name="outbound_actions"
    )
    op.drop_column("outbound_actions", "origin")
    op.drop_column("response_planning_jobs", "ambient_reason")
    op.drop_column("response_planning_jobs", "ambient_policy_version")
    op.drop_column("response_planning_jobs", "trigger")
    op.drop_column("conversation_configuration_revisions", "ambient_frequency")
