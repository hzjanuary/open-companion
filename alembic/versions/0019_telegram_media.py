"""Add source-scoped Telegram media recovery and governed transcription.

Revision ID: 0019_telegram_media
Revises: 0018_user_controlled_memory
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_telegram_media"
down_revision: str | None = "0018_user_controlled_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WORKLOAD_CHECKS = (
    ("provider_capabilities", "provider_capability_workload"),
    ("provider_routing_policy_revisions", "provider_routing_workload"),
    ("provider_routing_policy_heads", "provider_routing_head_workload"),
    ("provider_work_policy_snapshots", "provider_work_snapshot_workload"),
    ("provider_budgets", "provider_budget_workload"),
    ("provider_usage_attempts", "provider_usage_workload"),
)


def _check(table: str, name: str, condition: str) -> None:
    op.drop_constraint(name, table, type_="check")
    op.create_check_constraint(name, table, condition)


def _provider_checks(*, extended: bool) -> None:
    workloads = "'chat_generation','embedding'"
    operations = (
        "'response_planning','summary_generation','semantic_query',"
        "'semantic_index','semantic_rebuild'"
    )
    requests = "'embedding_request'"
    if extended:
        workloads += ",'transcription'"
        operations += ",'media_transcription'"
        requests += ",'transcription_request'"
    for table, name in WORKLOAD_CHECKS:
        _check(table, name, f"workload_class IN ({workloads})")
    _check(
        "provider_usage_attempts",
        "provider_usage_operation",
        f"operation IN ({operations})",
    )
    _check(
        "provider_price_revisions",
        "provider_price_unit_basis",
        f"unit_basis IN ('generation_tokens',{requests})",
    )
    _check(
        "provider_price_revisions",
        "provider_price_shape",
        "(unit_basis = 'generation_tokens' AND input_rate IS NOT NULL AND "
        "output_rate IS NOT NULL AND request_rate IS NULL) OR "
        f"(unit_basis IN ({requests}) AND input_rate IS NULL AND "
        "output_rate IS NULL AND request_rate IS NOT NULL)",
    )


def upgrade() -> None:
    _check(
        "messages",
        "message_type",
        "message_type IN ('text','sticker','other','photo','voice','audio')",
    )
    op.create_unique_constraint(
        "uq_messages_id_conversation", "messages", ["id", "conversation_id"]
    )
    op.create_table(
        "message_media",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("file_id", sa.String(255)),
        sa.Column("file_unique_id", sa.String(255)),
        sa.Column("mime_type", sa.String(32)),
        sa.Column("file_size", sa.BigInteger()),
        sa.Column("width", sa.Integer()),
        sa.Column("height", sa.Integer()),
        sa.Column("duration_seconds", sa.Integer()),
        sa.Column("caption", sa.String(1024)),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("failure_reason", sa.String(32)),
        sa.Column("lease_token", sa.Uuid()),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("planning_attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("privacy_revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_edited_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("redacted_at", sa.DateTime(timezone=True)),
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
        sa.UniqueConstraint("message_id"),
        sa.ForeignKeyConstraint(
            ["message_id", "conversation_id"],
            ["messages.id", "messages.conversation_id"],
            name="fk_message_media_message_conversation",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("kind IN ('photo','voice','audio')", name="media_kind"),
        sa.CheckConstraint(
            "status IN ('pending','preparing','complete',"
            "'failed','ambiguous','redacted')",
            name="media_status",
        ),
        sa.CheckConstraint(
            "failure_reason IS NULL OR failure_reason IN "
            "('unsupported','invalid_format',"
            "'too_large','disabled','unavailable','timeout','ambiguous','privacy_changed',"
            "'stale_lease','budget_denied','rate_limited','concurrency_limited')",
            name="media_failure_reason",
        ),
        sa.CheckConstraint(
            "file_size IS NULL OR file_size BETWEEN 1 AND 10485760",
            name="media_file_size",
        ),
        sa.CheckConstraint(
            "width IS NULL OR width BETWEEN 1 AND 4096", name="media_width"
        ),
        sa.CheckConstraint(
            "height IS NULL OR height BETWEEN 1 AND 4096", name="media_height"
        ),
        sa.CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds BETWEEN 0 AND 300",
            name="media_duration",
        ),
        sa.CheckConstraint(
            "planning_attempt >= 0 AND privacy_revision >= 0",
            name="media_revision_bounds",
        ),
        sa.CheckConstraint(
            "(status = 'preparing' AND lease_token IS NOT NULL "
            "AND lease_expires_at IS NOT NULL AND planning_attempt > 0) OR "
            "(status <> 'preparing' AND lease_token IS NULL "
            "AND lease_expires_at IS NULL)",
            name="media_lease_shape",
        ),
        sa.CheckConstraint(
            "(status IN ('pending','preparing','complete') "
            "AND failure_reason IS NULL) OR "
            "(status IN ('failed','ambiguous','redacted') "
            "AND failure_reason IS NOT NULL)",
            name="media_outcome_shape",
        ),
        sa.CheckConstraint(
            "(status = 'redacted' AND file_id IS NULL AND file_unique_id IS NULL "
            "AND caption IS NULL AND file_size IS NULL AND width IS NULL "
            "AND height IS NULL AND duration_seconds IS NULL AND mime_type IS NULL "
            "AND redacted_at IS NOT NULL) OR "
            "(status <> 'redacted' AND file_id IS NOT NULL "
            "AND file_unique_id IS NOT NULL AND mime_type IS NOT NULL "
            "AND file_id ~ '^[A-Za-z0-9_-]{1,255}$' "
            "AND file_unique_id ~ '^[A-Za-z0-9_-]{1,255}$' "
            "AND redacted_at IS NULL AND "
            "((kind = 'photo' AND mime_type = 'image/jpeg' "
            "AND width IS NOT NULL AND height IS NOT NULL "
            "AND duration_seconds IS NULL) "
            "OR (kind IN ('voice','audio') AND duration_seconds IS NOT NULL "
            "AND width IS NULL AND height IS NULL AND "
            "((kind = 'voice' AND mime_type = 'audio/ogg') "
            "OR (kind = 'audio' AND mime_type = 'audio/mpeg')))))",
            name="media_content_shape",
        ),
    )
    op.create_index(
        "ix_message_media_conversation_id", "message_media", ["conversation_id"]
    )
    op.create_index(
        "ix_message_media_recovery",
        "message_media",
        ["status", "lease_expires_at", "id"],
    )
    _provider_checks(extended=True)
    op.create_check_constraint(
        "provider_capability_transcription_boundary",
        "provider_capabilities",
        "workload_class <> 'transcription' OR provider_id = 'groq'",
    )


def downgrade() -> None:
    # Privacy/usage state cannot be safely discarded to make an old binary run.
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM message_media)
            OR EXISTS (SELECT 1 FROM messages
                       WHERE message_type IN ('photo','voice','audio'))
            OR EXISTS (SELECT 1 FROM provider_capabilities
                       WHERE workload_class = 'transcription')
            OR EXISTS (SELECT 1 FROM provider_routing_policy_revisions
                       WHERE workload_class = 'transcription')
            OR EXISTS (SELECT 1 FROM provider_routing_policy_heads
                       WHERE workload_class = 'transcription')
            OR EXISTS (SELECT 1 FROM provider_work_policy_snapshots
                       WHERE workload_class = 'transcription')
            OR EXISTS (SELECT 1 FROM provider_budgets
                       WHERE workload_class = 'transcription')
            OR EXISTS (SELECT 1 FROM provider_usage_attempts
                       WHERE workload_class = 'transcription'
                       OR operation = 'media_transcription')
            OR EXISTS (SELECT 1 FROM provider_price_revisions
                       WHERE unit_basis = 'transcription_request')
          THEN RAISE EXCEPTION 'SPEC-028 media or transcription state blocks downgrade';
          END IF;
        END $$;
    """)
    op.drop_constraint(
        "provider_capability_transcription_boundary",
        "provider_capabilities",
        type_="check",
    )
    _provider_checks(extended=False)
    op.drop_table("message_media")
    op.drop_constraint("uq_messages_id_conversation", "messages", type_="unique")
    _check("messages", "message_type", "message_type IN ('text','sticker','other')")
