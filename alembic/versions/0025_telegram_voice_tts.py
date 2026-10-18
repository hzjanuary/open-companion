"""Add governed explicit Telegram voice playback and bounded TTS artifacts.

Revision ID: 0025_telegram_voice_tts
Revises: 0024_telegram_response_regeneration
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_telegram_voice_tts"
down_revision: str | None = "0024_telegram_response_regeneration"
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


def _replace_check(table: str, name: str, condition: str) -> None:
    op.drop_constraint(name, table, type_="check")
    op.create_check_constraint(name, table, condition)


def _provider_checks(*, voice: bool) -> None:
    workloads = "'chat_generation','embedding','transcription'"
    operations = (
        "'response_planning','summary_generation','semantic_query',"
        "'semantic_index','semantic_rebuild','media_transcription',"
        "'knowledge_query','knowledge_index','knowledge_rebuild'"
    )
    requests = "'embedding_request','transcription_request'"
    if voice:
        workloads += ",'text_to_speech'"
        operations += ",'voice_synthesis'"
        requests += ",'tts_request'"
    for table, name in WORKLOAD_CHECKS:
        _replace_check(table, name, f"workload_class IN ({workloads})")
    _replace_check(
        "provider_usage_attempts",
        "provider_usage_operation",
        f"operation IN ({operations})",
    )
    _replace_check(
        "provider_price_revisions",
        "provider_price_unit_basis",
        f"unit_basis IN ('generation_tokens',{requests})",
    )
    _replace_check(
        "provider_price_revisions",
        "provider_price_shape",
        "(unit_basis = 'generation_tokens' AND input_rate IS NOT NULL AND "
        "output_rate IS NOT NULL AND request_rate IS NULL) OR "
        f"(unit_basis IN ({requests}) AND input_rate IS NULL AND "
        "output_rate IS NULL AND request_rate IS NOT NULL)",
    )


def upgrade() -> None:
    op.create_table(
        "telegram_voice_generation_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("command_job_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("assistant_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("source_response_plan_id", sa.Uuid(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("source_character_count", sa.Integer(), nullable=False),
        sa.Column("privacy_revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("lease_owner", sa.String(255)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_attempt_id", sa.Uuid()),
        sa.Column("failure_reason", sa.String(32)),
        sa.Column("io_started_at", sa.DateTime(timezone=True)),
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
        sa.UniqueConstraint("command_job_id"),
        sa.UniqueConstraint(
            "id",
            "tenant_id",
            "assistant_id",
            "connection_id",
            "conversation_id",
            name="uq_voice_jobs_id_scope",
        ),
        sa.ForeignKeyConstraint(
            ["command_job_id"],
            ["telegram_command_jobs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["control_tenants.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["assistant_id", "tenant_id"],
            ["assistants.id", "assistants.tenant_id"],
            name="fk_voice_jobs_assistant_owner",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["platform_connections.id", "platform_connections.tenant_id"],
            name="fk_voice_jobs_connection_owner",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "assistant_id"],
            ["platform_connections.id", "platform_connections.assistant_id"],
            name="fk_voice_jobs_connection_assistant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id", "connection_id"],
            ["conversations.id", "conversations.platform_connection_id"],
            name="fk_voice_jobs_conversation_connection",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_response_plan_id"],
            ["response_plans.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["provider_attempt_id"],
            ["provider_usage_attempts.id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "source_character_count BETWEEN 1 AND 4000",
            name="voice_job_source_size",
        ),
        sa.CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$'", name="voice_job_source_checksum"
        ),
        sa.CheckConstraint("privacy_revision >= 0", name="voice_job_privacy_revision"),
        sa.CheckConstraint(
            "status IN ('pending','leased','io_possible','completed','failed','stale')",
            name="voice_generation_status",
        ),
        sa.CheckConstraint(
            "failure_reason IS NULL OR failure_reason IN "
            "('target_unavailable','too_long','unsupported','admission_denied',"
            "'provider_failed','provider_uncertain','stale_authority')",
            name="voice_failure_reason",
        ),
        sa.CheckConstraint(
            "(status = 'leased' AND lease_owner IS NOT NULL "
            "AND lease_expires_at IS NOT NULL) OR "
            "(status <> 'leased' AND lease_owner IS NULL AND lease_expires_at IS NULL)",
            name="voice_job_lease_shape",
        ),
        sa.CheckConstraint(
            "(status IN ('pending','leased') AND failure_reason IS NULL "
            "AND completed_at IS NULL) OR "
            "(status = 'completed' AND failure_reason IS NULL "
            "AND completed_at IS NOT NULL) OR "
            "(status IN ('io_possible','failed','stale') "
            "AND failure_reason IS NOT NULL AND completed_at IS NOT NULL)",
            name="voice_job_outcome_shape",
        ),
    )
    op.create_index(
        "ix_voice_jobs_recovery",
        "telegram_voice_generation_jobs",
        ["status", "lease_expires_at", "created_at"],
    )

    for table in ("provider_work_policy_snapshots", "provider_usage_attempts"):
        op.add_column(table, sa.Column("voice_generation_job_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_provider_snapshot_voice_job",
        "provider_work_policy_snapshots",
        "telegram_voice_generation_jobs",
        ["voice_generation_job_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_provider_usage_voice_job",
        "provider_usage_attempts",
        "telegram_voice_generation_jobs",
        ["voice_generation_job_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.add_column("rate_limit_events", sa.Column("voice_generation_job_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_rate_limit_events_voice_job",
        "rate_limit_events",
        "telegram_voice_generation_jobs",
        ["voice_generation_job_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_rate_limit_events_voice_generation_job_id",
        "rate_limit_events",
        ["voice_generation_job_id"],
    )
    _replace_check(
        "provider_work_policy_snapshots",
        "provider_work_snapshot_one_source",
        "num_nonnulls(planning_job_id, summary_job_id, semantic_index_job_id, "
        "knowledge_index_job_id, voice_generation_job_id) = 1",
    )
    _replace_check(
        "provider_usage_attempts",
        "provider_usage_attempt_one_source",
        "num_nonnulls(planning_job_id, summary_job_id, semantic_index_job_id, "
        "knowledge_index_job_id, voice_generation_job_id) = 1",
    )
    _provider_checks(voice=True)
    op.create_check_constraint(
        "provider_capability_tts_boundary",
        "provider_capabilities",
        "workload_class <> 'text_to_speech' OR provider_id = 'openai'",
    )

    op.create_table(
        "generated_voice_artifacts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("generation_job_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("assistant_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("source_response_plan_id", sa.Uuid(), nullable=False),
        sa.Column("format", sa.String(16), nullable=False),
        sa.Column("mime_type", sa.String(32), nullable=False),
        sa.Column("audio_bytes", sa.LargeBinary()),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("action_terminal_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purged_at", sa.DateTime(timezone=True)),
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
        sa.UniqueConstraint("generation_job_id"),
        sa.UniqueConstraint(
            "id", "conversation_id", name="uq_voice_artifacts_id_conversation"
        ),
        sa.ForeignKeyConstraint(
            [
                "generation_job_id",
                "tenant_id",
                "assistant_id",
                "connection_id",
                "conversation_id",
            ],
            [
                "telegram_voice_generation_jobs.id",
                "telegram_voice_generation_jobs.tenant_id",
                "telegram_voice_generation_jobs.assistant_id",
                "telegram_voice_generation_jobs.connection_id",
                "telegram_voice_generation_jobs.conversation_id",
            ],
            name="fk_voice_artifacts_job_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_response_plan_id"],
            ["response_plans.id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "format = 'ogg_opus' AND mime_type = 'audio/ogg'",
            name="voice_artifact_format",
        ),
        sa.CheckConstraint(
            "byte_size BETWEEN 1 AND 5242880", name="voice_artifact_size"
        ),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="voice_artifact_checksum"),
        sa.CheckConstraint(
            "status IN ('ready','purged')", name="voice_artifact_status"
        ),
        sa.CheckConstraint(
            "(status = 'ready' AND audio_bytes IS NOT NULL "
            "AND octet_length(audio_bytes) = byte_size AND purged_at IS NULL) OR "
            "(status = 'purged' AND audio_bytes IS NULL AND purged_at IS NOT NULL)",
            name="voice_artifact_content_shape",
        ),
        sa.CheckConstraint(
            "expires_at <= created_at + interval '7 days'",
            name="voice_artifact_expiry_bound",
        ),
    )
    op.create_index(
        "ix_voice_artifacts_retention",
        "generated_voice_artifacts",
        ["status", "expires_at", "created_at"],
    )

    op.add_column(
        "outbound_actions", sa.Column("generated_voice_artifact_id", sa.Uuid())
    )
    op.create_foreign_key(
        "fk_outbound_voice_artifact_conversation",
        "outbound_actions",
        "generated_voice_artifacts",
        ["generated_voice_artifact_id", "conversation_id"],
        ["id", "conversation_id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_outbound_actions_generated_voice_artifact_id",
        "outbound_actions",
        ["generated_voice_artifact_id"],
    )
    op.create_index(
        "ix_outbound_actions_generated_voice_artifact_id",
        "outbound_actions",
        ["generated_voice_artifact_id"],
    )
    _replace_check(
        "outbound_actions",
        "outbound_action_kind",
        "kind IN ('text','edit_text','sticker','voice')",
    )
    _replace_check(
        "outbound_actions",
        "outbound_action_payload",
        "(payload_redacted_at IS NOT NULL AND text IS NULL "
        "AND sticker_intent IS NULL) OR "
        "(kind IN ('text','edit_text') AND text IS NOT NULL AND btrim(text) <> '' "
        "AND sticker_intent IS NULL AND generated_voice_artifact_id IS NULL) OR "
        "(kind = 'sticker' AND text IS NULL AND sticker_intent IS NOT NULL "
        "AND generated_voice_artifact_id IS NULL) OR "
        "(kind = 'voice' AND text IS NULL AND sticker_intent IS NULL "
        "AND generated_voice_artifact_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "outbound_voice_shape",
        "outbound_actions",
        "(kind = 'voice' AND generated_voice_artifact_id IS NOT NULL "
        "AND sequence_number = 1 AND sequence_count = 1 "
        "AND fallback_for_action_id IS NULL) OR "
        "(kind <> 'voice' AND generated_voice_artifact_id IS NULL)",
    )

    op.execute("""
    CREATE FUNCTION spec038_validate_voice_job() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE command_conversation uuid; command_message uuid; command_name text;
            plan_conversation uuid; plan_text text; plan_redacted timestamptz;
    BEGIN
      SELECT conversation_id, message_id, telegram_command_jobs.command_name
        INTO command_conversation, command_message, command_name
        FROM telegram_command_jobs WHERE id = NEW.command_job_id;
      SELECT j.conversation_id, p.text, p.content_redacted_at
        INTO plan_conversation, plan_text, plan_redacted
        FROM response_plans p
        JOIN response_planning_jobs j ON j.id = p.planning_job_id
       WHERE p.id = NEW.source_response_plan_id;
      IF command_name <> 'voice' OR command_conversation <> NEW.conversation_id
         OR command_message IS NULL OR plan_conversation <> NEW.conversation_id
         OR plan_text IS NULL OR plan_redacted IS NOT NULL
         OR char_length(plan_text) <> NEW.source_character_count THEN
        RAISE EXCEPTION 'SPEC-038 voice source authority is inconsistent';
      END IF;
      RETURN NEW;
    END $$
    """)
    op.execute("""
    CREATE TRIGGER trg_spec038_validate_voice_job
    BEFORE INSERT OR UPDATE ON telegram_voice_generation_jobs
    FOR EACH ROW EXECUTE FUNCTION spec038_validate_voice_job()
    """)
    op.execute("""
    CREATE FUNCTION spec038_immutable_voice_identity()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.command_job_id IS DISTINCT FROM OLD.command_job_id
         OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
         OR NEW.assistant_id IS DISTINCT FROM OLD.assistant_id
         OR NEW.connection_id IS DISTINCT FROM OLD.connection_id
         OR NEW.conversation_id IS DISTINCT FROM OLD.conversation_id
         OR NEW.source_response_plan_id IS DISTINCT FROM OLD.source_response_plan_id
         OR NEW.source_sha256 IS DISTINCT FROM OLD.source_sha256
         OR NEW.source_character_count IS DISTINCT FROM OLD.source_character_count
         OR NEW.privacy_revision IS DISTINCT FROM OLD.privacy_revision THEN
        RAISE EXCEPTION 'SPEC-038 voice job identity is immutable';
      END IF;
      RETURN NEW;
    END $$
    """)
    op.execute("""
    CREATE TRIGGER trg_spec038_immutable_voice_identity
    BEFORE UPDATE ON telegram_voice_generation_jobs
    FOR EACH ROW EXECUTE FUNCTION spec038_immutable_voice_identity()
    """)
    op.execute("""
    CREATE FUNCTION spec038_validate_voice_artifact()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE job_plan uuid;
    BEGIN
      SELECT source_response_plan_id INTO job_plan
        FROM telegram_voice_generation_jobs WHERE id = NEW.generation_job_id;
      IF job_plan IS NULL OR job_plan <> NEW.source_response_plan_id THEN
        RAISE EXCEPTION 'SPEC-038 artifact source is inconsistent';
      END IF;
      IF TG_OP = 'UPDATE' AND (
         NEW.generation_job_id IS DISTINCT FROM OLD.generation_job_id
         OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
         OR NEW.assistant_id IS DISTINCT FROM OLD.assistant_id
         OR NEW.connection_id IS DISTINCT FROM OLD.connection_id
         OR NEW.conversation_id IS DISTINCT FROM OLD.conversation_id
         OR NEW.source_response_plan_id IS DISTINCT FROM OLD.source_response_plan_id
         OR NEW.format IS DISTINCT FROM OLD.format
         OR NEW.mime_type IS DISTINCT FROM OLD.mime_type
         OR NEW.byte_size IS DISTINCT FROM OLD.byte_size
         OR NEW.sha256 IS DISTINCT FROM OLD.sha256) THEN
        RAISE EXCEPTION 'SPEC-038 artifact identity is immutable';
      END IF;
      RETURN NEW;
    END $$
    """)
    op.execute("""
    CREATE TRIGGER trg_spec038_validate_voice_artifact
    BEFORE INSERT OR UPDATE ON generated_voice_artifacts
    FOR EACH ROW EXECUTE FUNCTION spec038_validate_voice_artifact()
    """)
    op.execute("""
    CREATE FUNCTION spec038_validate_voice_action()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE artifact_job uuid; artifact_status text; job_command uuid;
            command_message uuid; plan_command uuid;
    BEGIN
      IF NEW.kind <> 'voice' THEN RETURN NEW; END IF;
      SELECT a.generation_job_id, a.status INTO artifact_job, artifact_status
        FROM generated_voice_artifacts a
       WHERE a.id = NEW.generated_voice_artifact_id;
      SELECT command_job_id INTO job_command
        FROM telegram_voice_generation_jobs WHERE id = artifact_job;
      SELECT message_id INTO command_message
        FROM telegram_command_jobs WHERE id = job_command;
      SELECT command_job_id INTO plan_command
        FROM response_plans WHERE id = NEW.response_plan_id;
      IF artifact_job IS NULL OR job_command IS NULL
         OR (TG_OP = 'INSERT' AND artifact_status <> 'ready')
         OR plan_command <> job_command
         OR NEW.reply_to_message_id <> command_message THEN
        RAISE EXCEPTION 'SPEC-038 voice action authority is inconsistent';
      END IF;
      IF TG_OP = 'UPDATE'
         AND NEW.generated_voice_artifact_id
             IS DISTINCT FROM OLD.generated_voice_artifact_id THEN
        RAISE EXCEPTION 'SPEC-038 voice action identity is immutable';
      END IF;
      RETURN NEW;
    END $$
    """)
    op.execute("""
    CREATE TRIGGER trg_spec038_validate_voice_action
    BEFORE INSERT OR UPDATE ON outbound_actions
    FOR EACH ROW EXECUTE FUNCTION spec038_validate_voice_action()
    """)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM telegram_voice_generation_jobs)
         OR EXISTS (SELECT 1 FROM generated_voice_artifacts)
         OR EXISTS (SELECT 1 FROM outbound_actions WHERE kind = 'voice')
         OR EXISTS (SELECT 1 FROM provider_capabilities
                     WHERE workload_class = 'text_to_speech')
         OR EXISTS (SELECT 1 FROM provider_routing_policy_revisions
                     WHERE workload_class = 'text_to_speech')
         OR EXISTS (SELECT 1 FROM provider_routing_policy_heads
                     WHERE workload_class = 'text_to_speech')
         OR EXISTS (SELECT 1 FROM provider_work_policy_snapshots
                     WHERE workload_class = 'text_to_speech')
         OR EXISTS (SELECT 1 FROM provider_budgets
                     WHERE workload_class = 'text_to_speech')
         OR EXISTS (SELECT 1 FROM provider_usage_attempts
                     WHERE workload_class = 'text_to_speech'
                        OR operation = 'voice_synthesis')
         OR EXISTS (SELECT 1 FROM provider_price_revisions
                     WHERE unit_basis = 'tts_request')
         OR EXISTS (SELECT 1 FROM rate_limit_events WHERE operation = 'text_to_speech')
      THEN RAISE EXCEPTION 'SPEC-038 voice or TTS state blocks downgrade'; END IF;
    END $$;
    """)
    op.execute("DROP TRIGGER trg_spec038_validate_voice_action ON outbound_actions")
    op.execute("DROP FUNCTION spec038_validate_voice_action()")
    op.execute(
        "DROP TRIGGER trg_spec038_validate_voice_artifact ON generated_voice_artifacts"
    )
    op.execute("DROP FUNCTION spec038_validate_voice_artifact()")
    op.execute(
        "DROP TRIGGER trg_spec038_immutable_voice_identity "
        "ON telegram_voice_generation_jobs"
    )
    op.execute("DROP FUNCTION spec038_immutable_voice_identity()")
    op.execute(
        "DROP TRIGGER trg_spec038_validate_voice_job ON telegram_voice_generation_jobs"
    )
    op.execute("DROP FUNCTION spec038_validate_voice_job()")

    op.drop_constraint("outbound_voice_shape", "outbound_actions", type_="check")
    _replace_check(
        "outbound_actions",
        "outbound_action_payload",
        "(payload_redacted_at IS NOT NULL AND text IS NULL "
        "AND sticker_intent IS NULL) OR "
        "(kind IN ('text','edit_text') AND text IS NOT NULL AND btrim(text) <> '' "
        "AND sticker_intent IS NULL) OR (kind = 'sticker' AND text IS NULL "
        "AND sticker_intent IS NOT NULL)",
    )
    _replace_check(
        "outbound_actions",
        "outbound_action_kind",
        "kind IN ('text','edit_text','sticker')",
    )
    op.drop_index(
        "ix_outbound_actions_generated_voice_artifact_id",
        table_name="outbound_actions",
    )
    op.drop_constraint(
        "uq_outbound_actions_generated_voice_artifact_id",
        "outbound_actions",
        type_="unique",
    )
    op.drop_constraint(
        "fk_outbound_voice_artifact_conversation",
        "outbound_actions",
        type_="foreignkey",
    )
    op.drop_column("outbound_actions", "generated_voice_artifact_id")
    op.drop_index(
        "ix_voice_artifacts_retention", table_name="generated_voice_artifacts"
    )
    op.drop_table("generated_voice_artifacts")

    op.drop_constraint(
        "provider_capability_tts_boundary", "provider_capabilities", type_="check"
    )
    op.drop_index(
        "ix_rate_limit_events_voice_generation_job_id",
        table_name="rate_limit_events",
    )
    op.drop_constraint(
        "fk_rate_limit_events_voice_job", "rate_limit_events", type_="foreignkey"
    )
    op.drop_column("rate_limit_events", "voice_generation_job_id")
    _provider_checks(voice=False)
    _replace_check(
        "provider_usage_attempts",
        "provider_usage_attempt_one_source",
        "num_nonnulls(planning_job_id, summary_job_id, semantic_index_job_id, "
        "knowledge_index_job_id) = 1",
    )
    _replace_check(
        "provider_work_policy_snapshots",
        "provider_work_snapshot_one_source",
        "num_nonnulls(planning_job_id, summary_job_id, semantic_index_job_id, "
        "knowledge_index_job_id) = 1",
    )
    op.drop_constraint(
        "fk_provider_usage_voice_job", "provider_usage_attempts", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_provider_snapshot_voice_job",
        "provider_work_policy_snapshots",
        type_="foreignkey",
    )
    op.drop_column("provider_usage_attempts", "voice_generation_job_id")
    op.drop_column("provider_work_policy_snapshots", "voice_generation_job_id")
    op.drop_index("ix_voice_jobs_recovery", table_name="telegram_voice_generation_jobs")
    op.drop_table("telegram_voice_generation_jobs")
