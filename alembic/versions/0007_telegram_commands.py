"""Add durable Telegram command jobs and participant preference events.

Revision ID: 0007_telegram_commands
Revises: 0006_personality_config
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_telegram_commands"
down_revision: str | None = "0006_personality_config"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamps() -> list[sa.Column[object]]:
    return [
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
    ]


def upgrade() -> None:
    # SQLAlchemy's non-native enum checks were created in SPEC-005. Extend both
    # stored eligibility columns before command handoff starts writing its new
    # stable reason.
    op.execute(
        "ALTER TABLE messages DROP CONSTRAINT ck_messages_message_eligibility_reason"
    )
    op.create_check_constraint(
        "message_eligibility_reason",
        "messages",
        "eligibility_reason IN ("
        "'eligible_private_message','eligible_assistant_mentioned',"
        "'eligible_reply_to_assistant','eligible_assistant_name',"
        "'eligible_ambient_candidate','conversation_paused','connection_inactive',"
        "'assistant_inactive','sender_is_assistant','sender_is_bot',"
        "'unsupported_message_type','edited_message_no_response',"
        "'not_addressed_to_assistant','membership_event_no_response',"
        "'command_handoff')",
    )
    op.execute(
        "ALTER TABLE conversation_processing_records DROP CONSTRAINT "
        "ck_conversation_processing_records_processing_eligibili_9062"
    )
    op.create_check_constraint(
        "processing_eligibility_reason",
        "conversation_processing_records",
        "eligibility_reason IN ("
        "'eligible_private_message','eligible_assistant_mentioned',"
        "'eligible_reply_to_assistant','eligible_assistant_name',"
        "'eligible_ambient_candidate','conversation_paused','connection_inactive',"
        "'assistant_inactive','sender_is_assistant','sender_is_bot',"
        "'unsupported_message_type','edited_message_no_response',"
        "'not_addressed_to_assistant','membership_event_no_response',"
        "'command_handoff')",
    )
    op.create_table(
        "telegram_command_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_processing_record_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("participant_id", sa.Uuid(), nullable=False),
        sa.Column("command_name", sa.String(32), nullable=False),
        sa.Column("arguments", sa.String(160), nullable=False, server_default=""),
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
        sa.Column("authorization_outcome", sa.String(32)),
        sa.Column("result_code", sa.String(64)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        *timestamps(),
        sa.ForeignKeyConstraint(
            ["conversation_processing_record_id"],
            ["conversation_processing_records.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["participant_id"], ["participants.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_processing_record_id"),
        sa.CheckConstraint(
            "command_name ~ '^[a-z][a-z0-9_]{0,31}$'", name="command_name_format"
        ),
        sa.CheckConstraint("length(arguments) <= 160", name="command_arguments_length"),
        sa.CheckConstraint(
            "status IN ('pending', 'leased', 'completed', 'failed')",
            name="command_job_status_values",
        ),
        sa.CheckConstraint(
            "authorization_outcome IS NULL OR authorization_outcome IN "
            "('allowed', 'denied', 'retryable_failure', 'permanent_failure')",
            name="command_authorization_outcome_values",
        ),
    )
    op.create_index(
        "ix_telegram_command_jobs_claim",
        "telegram_command_jobs",
        ["status", "available_at", "created_at"],
    )
    op.create_index(
        "ix_telegram_command_jobs_lease",
        "telegram_command_jobs",
        ["status", "lease_expires_at"],
    )
    op.create_table(
        "participant_preference_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("participant_id", sa.Uuid(), nullable=False),
        sa.Column("command_job_id", sa.Uuid(), nullable=False),
        sa.Column("previous_mention_allowed", sa.Boolean(), nullable=False),
        sa.Column("mention_allowed", sa.Boolean(), nullable=False),
        sa.Column("previous_teasing_allowed", sa.Boolean(), nullable=False),
        sa.Column("teasing_allowed", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(
            ["participant_id"], ["participants.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["command_job_id"], ["telegram_command_jobs.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("command_job_id"),
    )
    op.alter_column(
        "response_plans", "planning_job_id", existing_type=sa.Uuid(), nullable=True
    )
    op.add_column("response_plans", sa.Column("command_job_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_response_plans_command_job",
        "response_plans",
        "telegram_command_jobs",
        ["command_job_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_response_plans_command_job", "response_plans", ["command_job_id"]
    )
    op.create_check_constraint(
        "response_plan_exactly_one_source",
        "response_plans",
        "(planning_job_id IS NOT NULL) <> (command_job_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "response_plan_exactly_one_source", "response_plans", type_="check"
    )
    op.drop_constraint(
        "uq_response_plans_command_job", "response_plans", type_="unique"
    )
    op.drop_constraint(
        "fk_response_plans_command_job", "response_plans", type_="foreignkey"
    )
    op.drop_column("response_plans", "command_job_id")
    op.alter_column(
        "response_plans", "planning_job_id", existing_type=sa.Uuid(), nullable=False
    )
    op.drop_table("participant_preference_events")
    op.drop_index("ix_telegram_command_jobs_lease", table_name="telegram_command_jobs")
    op.drop_index("ix_telegram_command_jobs_claim", table_name="telegram_command_jobs")
    op.drop_table("telegram_command_jobs")
    op.execute(
        "ALTER TABLE conversation_processing_records DROP CONSTRAINT IF EXISTS "
        "ck_conversation_processing_records_processing_eligibili_9062"
    )
    op.create_check_constraint(
        "processing_eligibility_reason",
        "conversation_processing_records",
        "eligibility_reason <> 'command_handoff'",
    )
    op.execute(
        "ALTER TABLE messages DROP CONSTRAINT IF EXISTS "
        "ck_messages_message_eligibility_reason"
    )
    op.create_check_constraint(
        "message_eligibility_reason",
        "messages",
        "eligibility_reason <> 'command_handoff'",
    )
