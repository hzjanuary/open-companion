"""Add durable response planning jobs, attempts, and plans.

Revision ID: 0004_response_planning
Revises: 0003_conversation_domain
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_response_planning"
down_revision: str | None = "0003_conversation_domain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def enum(name: str, values: list[str]) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True)


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
    provider = ["openai", "gemini", "groq", "openrouter", "ollama"]
    errors = [
        "invalid_configuration",
        "authentication",
        "permission",
        "invalid_request",
        "unsupported_capability",
        "rate_limited",
        "timeout",
        "transport",
        "provider_unavailable",
        "malformed_response",
        "structured_output",
        "safety_refusal",
        "context_too_large",
    ]
    op.create_table(
        "response_planning_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_processing_record_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            enum(
                "response_planning_job_status",
                ["pending", "leased", "completed", "no_response", "failed"],
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_owner", sa.String(length=255), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("response_schema_version", sa.String(length=64), nullable=False),
        sa.Column(
            "selected_provider",
            enum("response_planning_provider", provider),
            nullable=True,
        ),
        sa.Column("selected_model", sa.String(length=255), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_error_category",
            enum("response_planning_error_category", errors),
            nullable=True,
        ),
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
        sa.PrimaryKeyConstraint("id", name="pk_response_planning_jobs"),
        sa.UniqueConstraint(
            "conversation_processing_record_id",
            name="uq_response_planning_jobs_conversation_processing_record_id",
        ),
    )
    op.create_index(
        "ix_response_planning_jobs_claim",
        "response_planning_jobs",
        ["status", "available_at", "created_at"],
    )
    op.create_index(
        "ix_response_planning_jobs_lease",
        "response_planning_jobs",
        ["status", "lease_expires_at"],
    )
    op.create_table(
        "model_generation_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("planning_job_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column(
            "provider", enum("generation_attempt_provider", provider), nullable=False
        ),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column(
            "attempt_kind",
            enum("generation_attempt_kind", ["primary", "correction", "fallback"]),
            nullable=False,
        ),
        sa.Column(
            "status",
            enum("generation_attempt_status", ["succeeded", "failed", "refused"]),
            nullable=False,
        ),
        sa.Column("provider_request_id", sa.String(length=255), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_milliseconds", sa.Integer(), nullable=True),
        sa.Column(
            "error_category",
            enum("generation_attempt_error_category", errors),
            nullable=True,
        ),
        sa.Column("retryable", sa.Boolean(), nullable=True),
        sa.Column(
            "diagnostic_metadata",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        *timestamps(),
        sa.ForeignKeyConstraint(
            ["planning_job_id"], ["response_planning_jobs.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_model_generation_attempts"),
        sa.UniqueConstraint(
            "planning_job_id",
            "attempt_number",
            name="uq_model_generation_attempts_planning_job_id",
        ),
    )
    op.create_table(
        "response_plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("planning_job_id", sa.Uuid(), nullable=False),
        sa.Column("should_respond", sa.Boolean(), nullable=False),
        sa.Column(
            "reason_code",
            enum(
                "response_plan_reason_code",
                [
                    "social_reply",
                    "answer",
                    "acknowledgement",
                    "silence",
                    "safety_refusal",
                    "invalid_output",
                ],
            ),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("reply_to_message_id", sa.Uuid(), nullable=True),
        sa.Column(
            "mention_participant_ids", sa.dialects.postgresql.JSONB(), nullable=False
        ),
        sa.Column(
            "sticker_intent",
            enum(
                "response_plan_sticker_intent",
                [
                    "laugh",
                    "celebrate",
                    "awkward",
                    "suspicious",
                    "facepalm",
                    "support",
                    "sad",
                    "angry_cute",
                    "confused",
                ],
            ),
            nullable=True,
        ),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(
            ["planning_job_id"], ["response_planning_jobs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["reply_to_message_id"], ["messages.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_response_plans"),
        sa.UniqueConstraint(
            "planning_job_id", name="uq_response_plans_planning_job_id"
        ),
    )


def downgrade() -> None:
    op.drop_table("response_plans")
    op.drop_table("model_generation_attempts")
    op.drop_index(
        "ix_response_planning_jobs_lease", table_name="response_planning_jobs"
    )
    op.drop_index(
        "ix_response_planning_jobs_claim", table_name="response_planning_jobs"
    )
    op.drop_table("response_planning_jobs")
