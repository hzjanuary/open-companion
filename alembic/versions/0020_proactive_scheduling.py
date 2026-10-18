"""Add private durable reminders and opted-in proactive check-ins.

Revision ID: 0020_proactive_scheduling
Revises: 0019_telegram_media
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_proactive_scheduling"
down_revision: str | None = "0019_telegram_media"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column[object]]:
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


def upgrade() -> None:
    op.create_table(
        "participant_schedule_preferences",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("participant_id", sa.Uuid(), nullable=False),
        sa.Column("timezone_name", sa.String(64)),
        sa.Column(
            "quiet_hours_enabled", sa.Boolean(), nullable=False, server_default="true"
        ),
        sa.Column(
            "quiet_start_minute", sa.Integer(), nullable=False, server_default="1320"
        ),
        sa.Column(
            "quiet_end_minute", sa.Integer(), nullable=False, server_default="480"
        ),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
        sa.UniqueConstraint("participant_id"),
        sa.ForeignKeyConstraint(
            ["participant_id", "conversation_id"],
            ["participants.id", "participants.conversation_id"],
            name="fk_schedule_preferences_participant_conversation",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "quiet_start_minute BETWEEN 0 AND 1439 AND "
            "quiet_end_minute BETWEEN 0 AND 1439 AND "
            "(NOT quiet_hours_enabled OR quiet_start_minute <> quiet_end_minute)",
            name="schedule_preferences_quiet_bounds",
        ),
        sa.CheckConstraint("revision > 0", name="schedule_preferences_revision"),
    )
    op.create_table(
        "proactive_schedules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("public_id", sa.String(12), nullable=False, unique=True),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("creator_participant_id", sa.Uuid(), nullable=False),
        sa.Column("source_command_job_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("recurrence", sa.String(16), nullable=False),
        sa.Column("timezone_name", sa.String(64)),
        sa.Column("local_time_minute", sa.Integer()),
        sa.Column("weekday_mask", sa.Integer()),
        sa.Column("starts_on", sa.Date()),
        sa.Column("one_time_at", sa.DateTime(timezone=True)),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reminder_text", sa.Text()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("redacted_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["creator_participant_id", "conversation_id"],
            ["participants.id", "participants.conversation_id"],
            name="fk_proactive_schedule_creator_conversation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_command_job_id"],
            ["telegram_command_jobs.id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("kind IN ('reminder','check_in')", name="schedule_kind"),
        sa.CheckConstraint(
            "status IN ('active','completed','cancelled','erased')",
            name="schedule_status",
        ),
        sa.CheckConstraint(
            "recurrence IN ('once','daily','weekly')", name="schedule_recurrence"
        ),
        sa.CheckConstraint(
            "(redacted_at IS NULL AND timezone_name IS NOT NULL "
            "AND local_time_minute BETWEEN 0 AND 1439 "
            "AND starts_on IS NOT NULL AND ("
            "(recurrence = 'once' AND weekday_mask = 0 AND one_time_at IS NOT NULL) OR "
            "(recurrence = 'daily' AND weekday_mask = 127 AND one_time_at IS NULL) OR "
            "(recurrence = 'weekly' AND weekday_mask BETWEEN 1 AND 127 "
            "AND one_time_at IS NULL))) OR "
            "(redacted_at IS NOT NULL AND timezone_name IS NULL "
            "AND local_time_minute IS NULL AND weekday_mask IS NULL "
            "AND starts_on IS NULL AND one_time_at IS NULL)",
            name="schedule_timing_shape",
        ),
        sa.CheckConstraint(
            "(kind = 'reminder' AND ((redacted_at IS NULL "
            "AND reminder_text IS NOT NULL "
            "AND length(btrim(reminder_text)) BETWEEN 1 AND 100) OR "
            "(redacted_at IS NOT NULL AND reminder_text IS NULL))) OR "
            "(kind = 'check_in' AND reminder_text IS NULL)",
            name="schedule_content_shape",
        ),
        sa.CheckConstraint(
            "version > 0 AND ends_at > created_at", name="schedule_version_horizon"
        ),
        sa.CheckConstraint(
            "(status = 'active' AND next_run_at IS NOT NULL "
            "AND cancelled_at IS NULL AND completed_at IS NULL "
            "AND redacted_at IS NULL) OR "
            "(status = 'completed' AND next_run_at IS NULL "
            "AND completed_at IS NOT NULL AND cancelled_at IS NULL) OR "
            "(status = 'cancelled' AND next_run_at IS NULL "
            "AND cancelled_at IS NOT NULL) OR "
            "(status = 'erased' AND next_run_at IS NULL AND reminder_text IS NULL "
            "AND redacted_at IS NOT NULL)",
            name="schedule_status_shape",
        ),
    )
    op.create_index(
        "ix_proactive_schedules_due",
        "proactive_schedules",
        ["status", "next_run_at", "created_at", "id"],
    )
    op.create_index(
        "ix_proactive_schedules_scope",
        "proactive_schedules",
        ["creator_participant_id", "conversation_id", "status"],
    )
    op.create_index(
        "uq_proactive_schedules_active_checkin",
        "proactive_schedules",
        ["creator_participant_id", "conversation_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'check_in' AND status = 'active'"),
    )
    op.create_table(
        "proactive_schedule_command_receipts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("command_job_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("participant_id", sa.Uuid(), nullable=False),
        sa.Column("schedule_id", sa.Uuid()),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("outcome", sa.String(24), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["command_job_id"], ["telegram_command_jobs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["participant_id", "conversation_id"],
            ["participants.id", "participants.conversation_id"],
            name="fk_schedule_receipt_participant_conversation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["schedule_id"], ["proactive_schedules.id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "operation IN ('timezone_set','quiet_hours_set','reminder_create',"
            "'reminder_cancel','checkins_enable','checkins_disable')",
            name="schedule_receipt_operation",
        ),
        sa.CheckConstraint(
            "outcome IN ('created','updated','cancelled','unchanged','not_found',"
            "'limit_reached','too_late','invalid','denied')",
            name="schedule_receipt_outcome",
        ),
    )
    op.create_table(
        "proactive_schedule_occurrences",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("schedule_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("participant_id", sa.Uuid(), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True)),
        sa.Column("local_date", sa.Date()),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("reason_code", sa.String(32), nullable=False, server_default="none"),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("lease_owner", sa.String(255)),
        sa.Column("lease_token", sa.Uuid()),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("schedule_version", sa.Integer(), nullable=False),
        sa.Column("privacy_revision", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("redacted_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.UniqueConstraint("schedule_id", "local_date"),
        sa.ForeignKeyConstraint(
            ["schedule_id"], ["proactive_schedules.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["participant_id", "conversation_id"],
            ["participants.id", "participants.conversation_id"],
            name="fk_schedule_occurrence_participant_conversation",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN ('pending','leased','enqueued','delivered','skipped',"
            "'permanently_failed','delivery_unknown','history_redacted')",
            name="schedule_occurrence_status",
        ),
        sa.CheckConstraint(
            "reason_code IN ('none','stale','quiet_hours','recent_activity',"
            "'cancelled','privacy','membership','paused','expired',"
            "'delivery_rejected','delivery_unknown')",
            name="schedule_occurrence_reason",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND schedule_version > 0 AND privacy_revision >= 0",
            name="schedule_occurrence_revisions",
        ),
        sa.CheckConstraint(
            "(status = 'leased' AND lease_owner IS NOT NULL "
            "AND lease_token IS NOT NULL "
            "AND lease_expires_at IS NOT NULL AND attempt_count > 0) OR "
            "(status <> 'leased' AND lease_owner IS NULL AND lease_token IS NULL "
            "AND lease_expires_at IS NULL)",
            name="schedule_occurrence_lease_shape",
        ),
        sa.CheckConstraint(
            "(redacted_at IS NULL AND scheduled_for IS NOT NULL "
            "AND local_date IS NOT NULL) OR "
            "(redacted_at IS NOT NULL AND status = 'history_redacted' "
            "AND scheduled_for IS NULL AND local_date IS NULL)",
            name="schedule_occurrence_history_shape",
        ),
    )
    op.create_index(
        "ix_schedule_occurrences_claim",
        "proactive_schedule_occurrences",
        ["status", "available_at", "scheduled_for", "id"],
    )
    op.create_index(
        "ix_schedule_occurrences_lease",
        "proactive_schedule_occurrences",
        ["status", "lease_expires_at", "id"],
    )
    op.add_column("response_plans", sa.Column("schedule_occurrence_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_response_plans_schedule_occurrence",
        "response_plans",
        "proactive_schedule_occurrences",
        ["schedule_occurrence_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_response_plans_schedule_occurrence",
        "response_plans",
        ["schedule_occurrence_id"],
    )
    op.drop_constraint(
        "response_plan_exactly_one_source", "response_plans", type_="check"
    )
    op.create_check_constraint(
        "response_plan_exactly_one_source",
        "response_plans",
        "((planning_job_id IS NOT NULL)::int + (command_job_id IS NOT NULL)::int + "
        "(schedule_occurrence_id IS NOT NULL)::int) = 1",
    )
    op.create_check_constraint(
        "outbound_action_origin",
        "outbound_actions",
        "origin IN ('addressed','ambient','command','scheduled')",
    )


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM participant_schedule_preferences)
            OR EXISTS (SELECT 1 FROM proactive_schedules)
            OR EXISTS (SELECT 1 FROM proactive_schedule_command_receipts)
            OR EXISTS (SELECT 1 FROM proactive_schedule_occurrences)
            OR EXISTS (SELECT 1 FROM response_plans
                       WHERE schedule_occurrence_id IS NOT NULL)
            OR EXISTS (SELECT 1 FROM outbound_actions WHERE origin = 'scheduled')
          THEN RAISE EXCEPTION 'SPEC-029 schedule state blocks downgrade';
          END IF;
        END $$;
    """)
    op.drop_constraint("outbound_action_origin", "outbound_actions", type_="check")
    op.drop_constraint(
        "response_plan_exactly_one_source", "response_plans", type_="check"
    )
    op.create_check_constraint(
        "response_plan_exactly_one_source",
        "response_plans",
        "(planning_job_id IS NOT NULL) <> (command_job_id IS NOT NULL)",
    )
    op.drop_constraint(
        "uq_response_plans_schedule_occurrence", "response_plans", type_="unique"
    )
    op.drop_constraint(
        "fk_response_plans_schedule_occurrence",
        "response_plans",
        type_="foreignkey",
    )
    op.drop_column("response_plans", "schedule_occurrence_id")
    op.drop_table("proactive_schedule_occurrences")
    op.drop_table("proactive_schedule_command_receipts")
    op.drop_index(
        "uq_proactive_schedules_active_checkin", table_name="proactive_schedules"
    )
    op.drop_index("ix_proactive_schedules_scope", table_name="proactive_schedules")
    op.drop_index("ix_proactive_schedules_due", table_name="proactive_schedules")
    op.drop_table("proactive_schedules")
    op.drop_table("participant_schedule_preferences")
