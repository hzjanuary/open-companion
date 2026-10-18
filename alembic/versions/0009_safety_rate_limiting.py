"""Add content-free safety decisions and distributed limiter events.

Revision ID: 0009_safety_rate_limiting
Revises: 0008_memory_privacy_retention
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_safety_rate_limiting"
down_revision: str | None = "0008_memory_privacy_retention"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "response_planning_jobs",
        sa.Column(
            "safety_policy_version",
            sa.String(64),
            nullable=False,
            server_default="safety-policy-v1",
        ),
    )
    op.add_column(
        "response_plans",
        sa.Column(
            "interaction_kind",
            sa.String(32),
            nullable=False,
            server_default="neutral",
        ),
    )
    op.add_column(
        "response_plans",
        sa.Column(
            "teasing_target_participant_ids",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_table(
        "safety_policy_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("planning_job_id", sa.Uuid()),
        sa.Column("response_plan_id", sa.Uuid()),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("reason_code", sa.String(64)),
        sa.Column(
            "transformed", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
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
            ["planning_job_id"], ["response_planning_jobs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["response_plan_id"], ["response_plans.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_safety_policy_decisions_planning_job",
        "safety_policy_decisions",
        ["planning_job_id"],
    )
    op.create_index(
        "ix_safety_policy_decisions_response_plan",
        "safety_policy_decisions",
        ["response_plan_id"],
    )
    op.create_table(
        "rate_limit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("planning_job_id", sa.Uuid()),
        sa.Column("outbound_action_id", sa.Uuid()),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("limiting_scope", sa.String(32)),
        sa.Column("provider_id", sa.String(32)),
        sa.Column("allowed", sa.Boolean(), nullable=False),
        sa.Column("retry_after_seconds", sa.Integer()),
        sa.Column("configuration_version", sa.String(64), nullable=False),
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
            ["planning_job_id"], ["response_planning_jobs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["outbound_action_id"], ["outbound_actions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rate_limit_events_planning_job", "rate_limit_events", ["planning_job_id"]
    )
    op.create_index(
        "ix_rate_limit_events_outbound_action",
        "rate_limit_events",
        ["outbound_action_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_rate_limit_events_outbound_action", table_name="rate_limit_events"
    )
    op.drop_index("ix_rate_limit_events_planning_job", table_name="rate_limit_events")
    op.drop_table("rate_limit_events")
    op.drop_index(
        "ix_safety_policy_decisions_response_plan", table_name="safety_policy_decisions"
    )
    op.drop_index(
        "ix_safety_policy_decisions_planning_job", table_name="safety_policy_decisions"
    )
    op.drop_table("safety_policy_decisions")
    op.drop_column("response_plans", "teasing_target_participant_ids")
    op.drop_column("response_plans", "interaction_kind")
    op.drop_column("response_planning_jobs", "safety_policy_version")
