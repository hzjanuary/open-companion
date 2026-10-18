"""Add authoritative Telegram response regeneration and durable edit delivery.

Revision ID: 0024_telegram_response_regeneration
Revises: 0023_telegram_reply_ordered_delivery
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_telegram_response_regeneration"
down_revision: str | None = "0023_telegram_reply_ordered_delivery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "response_planning_jobs", sa.Column("source_command_job_id", sa.Uuid())
    )
    op.add_column(
        "response_planning_jobs", sa.Column("root_response_plan_id", sa.Uuid())
    )
    op.add_column(
        "response_planning_jobs", sa.Column("parent_response_plan_id", sa.Uuid())
    )
    op.add_column(
        "response_planning_jobs", sa.Column("regeneration_ordinal", sa.Integer())
    )
    op.create_foreign_key(
        "fk_planning_regen_command",
        "response_planning_jobs",
        "telegram_command_jobs",
        ["source_command_job_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_planning_regen_root_plan",
        "response_planning_jobs",
        "response_plans",
        ["root_response_plan_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_planning_regen_parent_plan",
        "response_planning_jobs",
        "response_plans",
        ["parent_response_plan_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_planning_regen_command",
        "response_planning_jobs",
        ["source_command_job_id"],
    )
    op.create_unique_constraint(
        "uq_planning_regen_root_ordinal",
        "response_planning_jobs",
        ["root_response_plan_id", "regeneration_ordinal"],
    )
    op.create_index(
        "ix_response_planning_jobs_root_response_plan_id",
        "response_planning_jobs",
        ["root_response_plan_id"],
    )
    op.create_index(
        "ix_response_planning_jobs_parent_response_plan_id",
        "response_planning_jobs",
        ["parent_response_plan_id"],
    )
    op.create_check_constraint(
        "response_planning_regeneration_shape",
        "response_planning_jobs",
        "(source_command_job_id IS NULL AND root_response_plan_id IS NULL "
        "AND parent_response_plan_id IS NULL AND regeneration_ordinal IS NULL) "
        "OR (source_command_job_id IS NOT NULL "
        "AND root_response_plan_id IS NOT NULL "
        "AND parent_response_plan_id IS NOT NULL "
        "AND regeneration_ordinal BETWEEN 1 AND 3)",
    )

    op.execute(
        "DROP TRIGGER trg_spec034_immutable_outbound_sequence ON outbound_actions"
    )
    op.execute("DROP FUNCTION spec034_immutable_outbound_sequence()")
    op.drop_constraint("outbound_action_kind", "outbound_actions", type_="check")
    op.alter_column(
        "outbound_actions",
        "kind",
        existing_type=sa.String(7),
        type_=sa.String(16),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "outbound_action_kind",
        "outbound_actions",
        "kind IN ('text','edit_text','sticker')",
    )
    op.drop_constraint("outbound_action_status", "outbound_actions", type_="check")
    op.create_check_constraint(
        "outbound_action_status",
        "outbound_actions",
        "status IN ('pending','fallback_blocked','leased','delivered','skipped',"
        "'permanently_failed','delivery_unknown')",
    )
    op.drop_constraint("outbound_action_payload", "outbound_actions", type_="check")
    op.create_check_constraint(
        "outbound_action_payload",
        "outbound_actions",
        "(payload_redacted_at IS NOT NULL AND text IS NULL "
        "AND sticker_intent IS NULL) OR "
        "(kind IN ('text','edit_text') AND text IS NOT NULL AND btrim(text) <> '' "
        "AND sticker_intent IS NULL) OR (kind = 'sticker' AND text IS NULL "
        "AND sticker_intent IS NOT NULL)",
    )
    op.add_column("outbound_actions", sa.Column("edit_target_message_id", sa.Uuid()))
    op.add_column(
        "outbound_actions",
        sa.Column("edit_target_platform_message_id", sa.String(255)),
    )
    op.add_column("outbound_actions", sa.Column("fallback_for_action_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_outbound_actions_edit_target_conversation",
        "outbound_actions",
        "messages",
        ["edit_target_message_id", "conversation_id"],
        ["id", "conversation_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_outbound_fallback_action",
        "outbound_actions",
        "outbound_actions",
        ["fallback_for_action_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_outbound_actions_fallback_for_action_id",
        "outbound_actions",
        ["fallback_for_action_id"],
    )
    op.create_index(
        "ix_outbound_actions_edit_target_message_id",
        "outbound_actions",
        ["edit_target_message_id"],
    )
    op.create_index(
        "ix_outbound_actions_fallback_for_action_id",
        "outbound_actions",
        ["fallback_for_action_id"],
    )
    op.create_check_constraint(
        "outbound_action_edit_shape",
        "outbound_actions",
        "(kind = 'edit_text' AND edit_target_message_id IS NOT NULL "
        "AND edit_target_platform_message_id IS NOT NULL "
        "AND fallback_for_action_id IS NULL "
        "AND (text IS NOT NULL OR payload_redacted_at IS NOT NULL)) OR "
        "(kind <> 'edit_text' AND edit_target_message_id IS NULL "
        "AND edit_target_platform_message_id IS NULL)",
    )
    op.create_check_constraint(
        "outbound_action_fallback_shape",
        "outbound_actions",
        "fallback_for_action_id IS NULL OR "
        "(kind = 'text' AND fallback_for_action_id <> id)",
    )

    op.execute("""
    CREATE FUNCTION spec036_validate_regeneration_job()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE
      command_conversation uuid;
      root_conversation uuid;
      root_source_command uuid;
      parent_conversation uuid;
      parent_root uuid;
    BEGIN
      IF NEW.source_command_job_id IS NULL THEN
        RETURN NEW;
      END IF;
      SELECT conversation_id INTO command_conversation
        FROM telegram_command_jobs WHERE id = NEW.source_command_job_id;
      SELECT j.conversation_id, j.source_command_job_id
        INTO root_conversation, root_source_command
        FROM response_plans p
        JOIN response_planning_jobs j ON j.id = p.planning_job_id
       WHERE p.id = NEW.root_response_plan_id;
      SELECT j.conversation_id, j.root_response_plan_id
        INTO parent_conversation, parent_root
        FROM response_plans p
        JOIN response_planning_jobs j ON j.id = p.planning_job_id
       WHERE p.id = NEW.parent_response_plan_id;
      IF command_conversation IS NULL OR root_conversation IS NULL
         OR parent_conversation IS NULL
         OR command_conversation <> NEW.conversation_id
         OR root_conversation <> NEW.conversation_id
         OR parent_conversation <> NEW.conversation_id
         OR root_source_command IS NOT NULL
         OR NOT (
           NEW.parent_response_plan_id = NEW.root_response_plan_id
           OR parent_root = NEW.root_response_plan_id
         ) THEN
        RAISE EXCEPTION 'SPEC-036 regeneration authority is inconsistent';
      END IF;
      IF NOT EXISTS (
        SELECT 1 FROM messages m
         WHERE m.id = NEW.message_id
           AND m.conversation_id = NEW.conversation_id
           AND m.direction = 'incoming'
           AND m.content_redacted_at IS NULL
      ) THEN
        RAISE EXCEPTION 'SPEC-036 regeneration source is unavailable';
      END IF;
      RETURN NEW;
    END;
    $$
    """)
    op.execute("""
    CREATE TRIGGER trg_spec036_validate_regeneration_job
    BEFORE INSERT OR UPDATE ON response_planning_jobs
    FOR EACH ROW EXECUTE FUNCTION spec036_validate_regeneration_job()
    """)
    op.execute("""
    CREATE FUNCTION spec036_immutable_regeneration_lineage()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.source_command_job_id IS DISTINCT FROM OLD.source_command_job_id
         OR NEW.root_response_plan_id IS DISTINCT FROM OLD.root_response_plan_id
         OR NEW.parent_response_plan_id IS DISTINCT FROM OLD.parent_response_plan_id
         OR NEW.regeneration_ordinal IS DISTINCT FROM OLD.regeneration_ordinal
         OR NEW.message_id IS DISTINCT FROM OLD.message_id
         OR NEW.conversation_id IS DISTINCT FROM OLD.conversation_id THEN
        RAISE EXCEPTION 'SPEC-036 regeneration lineage is immutable';
      END IF;
      RETURN NEW;
    END;
    $$
    """)
    op.execute("""
    CREATE TRIGGER trg_spec036_immutable_regeneration_lineage
    BEFORE UPDATE ON response_planning_jobs
    FOR EACH ROW EXECUTE FUNCTION spec036_immutable_regeneration_lineage()
    """)
    op.execute("""
    CREATE FUNCTION spec036_validate_outbound_presentation()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE target_plan uuid; target_conversation uuid; target_kind text;
    BEGIN
      IF NEW.kind = 'edit_text' AND NEW.payload_redacted_at IS NULL
         AND NOT EXISTS (
        SELECT 1 FROM messages m
         WHERE m.id = NEW.edit_target_message_id
           AND m.conversation_id = NEW.conversation_id
           AND m.platform_message_id = NEW.edit_target_platform_message_id
           AND m.direction = 'outgoing'
           AND m.message_type = 'text'
           AND m.content_redacted_at IS NULL
      ) THEN
        RAISE EXCEPTION 'SPEC-036 edit target is inconsistent';
      END IF;
      IF NEW.fallback_for_action_id IS NOT NULL THEN
        SELECT response_plan_id, conversation_id, kind
          INTO target_plan, target_conversation, target_kind
          FROM outbound_actions WHERE id = NEW.fallback_for_action_id;
        IF target_kind <> 'edit_text' OR target_plan <> NEW.response_plan_id
           OR target_conversation <> NEW.conversation_id
           OR NEW.sequence_number <= (
             SELECT sequence_number FROM outbound_actions
              WHERE id = NEW.fallback_for_action_id
           ) THEN
          RAISE EXCEPTION 'SPEC-036 fallback authority is inconsistent';
        END IF;
      END IF;
      IF NEW.status = 'delivered' AND NEW.kind = 'edit_text' AND EXISTS (
        SELECT 1 FROM outbound_actions f
         WHERE f.fallback_for_action_id = NEW.id
           AND f.status NOT IN ('fallback_blocked','skipped')
      ) THEN
        RAISE EXCEPTION 'SPEC-036 edit and fallback cannot both be canonical';
      END IF;
      IF NEW.status = 'delivered' AND NEW.fallback_for_action_id IS NOT NULL
         AND NOT EXISTS (
           SELECT 1 FROM outbound_actions e
            WHERE e.id = NEW.fallback_for_action_id AND e.status = 'skipped'
         ) THEN
        RAISE EXCEPTION 'SPEC-036 fallback requires rejected edit';
      END IF;
      RETURN NEW;
    END;
    $$
    """)
    op.execute("""
    CREATE TRIGGER trg_spec036_validate_outbound_presentation
    BEFORE INSERT OR UPDATE ON outbound_actions
    FOR EACH ROW EXECUTE FUNCTION spec036_validate_outbound_presentation()
    """)
    op.execute("""
    CREATE FUNCTION spec036_immutable_outbound_identity()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.response_plan_id IS DISTINCT FROM OLD.response_plan_id
         OR NEW.conversation_id IS DISTINCT FROM OLD.conversation_id
         OR NEW.sequence_number IS DISTINCT FROM OLD.sequence_number
         OR NEW.sequence_count IS DISTINCT FROM OLD.sequence_count
         OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
         OR NEW.kind IS DISTINCT FROM OLD.kind
         OR NEW.edit_target_message_id IS DISTINCT FROM OLD.edit_target_message_id
         OR NEW.edit_target_platform_message_id IS DISTINCT FROM
            OLD.edit_target_platform_message_id
         OR NEW.fallback_for_action_id IS DISTINCT FROM OLD.fallback_for_action_id THEN
        RAISE EXCEPTION 'SPEC-034 outbound sequence identity is immutable';
      END IF;
      RETURN NEW;
    END;
    $$
    """)
    op.execute("""
    CREATE TRIGGER trg_spec036_immutable_outbound_identity
    BEFORE UPDATE ON outbound_actions
    FOR EACH ROW EXECUTE FUNCTION spec036_immutable_outbound_identity()
    """)


def downgrade() -> None:
    op.execute("""
    DO $$
    BEGIN
      IF EXISTS (
        SELECT 1 FROM response_planning_jobs WHERE source_command_job_id IS NOT NULL
      ) OR EXISTS (
        SELECT 1 FROM outbound_actions
         WHERE kind = 'edit_text' OR fallback_for_action_id IS NOT NULL
      ) THEN
        RAISE EXCEPTION 'SPEC-036 regeneration or edit state blocks downgrade';
      END IF;
    END;
    $$
    """)
    op.execute(
        "DROP TRIGGER trg_spec036_immutable_outbound_identity ON outbound_actions"
    )
    op.execute("DROP FUNCTION spec036_immutable_outbound_identity()")
    op.execute(
        "DROP TRIGGER trg_spec036_validate_outbound_presentation ON outbound_actions"
    )
    op.execute("DROP FUNCTION spec036_validate_outbound_presentation()")
    op.execute(
        "DROP TRIGGER trg_spec036_immutable_regeneration_lineage "
        "ON response_planning_jobs"
    )
    op.execute("DROP FUNCTION spec036_immutable_regeneration_lineage()")
    op.execute(
        "DROP TRIGGER trg_spec036_validate_regeneration_job ON response_planning_jobs"
    )
    op.execute("DROP FUNCTION spec036_validate_regeneration_job()")

    op.drop_constraint(
        "outbound_action_fallback_shape", "outbound_actions", type_="check"
    )
    op.drop_constraint("outbound_action_edit_shape", "outbound_actions", type_="check")
    op.drop_index(
        "ix_outbound_actions_fallback_for_action_id", table_name="outbound_actions"
    )
    op.drop_index(
        "ix_outbound_actions_edit_target_message_id", table_name="outbound_actions"
    )
    op.drop_constraint(
        "uq_outbound_actions_fallback_for_action_id", "outbound_actions", type_="unique"
    )
    op.drop_constraint(
        "fk_outbound_fallback_action",
        "outbound_actions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_outbound_actions_edit_target_conversation",
        "outbound_actions",
        type_="foreignkey",
    )
    op.drop_column("outbound_actions", "fallback_for_action_id")
    op.drop_column("outbound_actions", "edit_target_platform_message_id")
    op.drop_column("outbound_actions", "edit_target_message_id")
    op.drop_constraint("outbound_action_payload", "outbound_actions", type_="check")
    op.create_check_constraint(
        "outbound_action_payload",
        "outbound_actions",
        "(payload_redacted_at IS NOT NULL AND text IS NULL "
        "AND sticker_intent IS NULL) OR "
        "(kind = 'text' AND text IS NOT NULL AND btrim(text) <> '' "
        "AND sticker_intent IS NULL) OR (kind = 'sticker' AND text IS NULL "
        "AND sticker_intent IS NOT NULL)",
    )
    op.drop_constraint("outbound_action_status", "outbound_actions", type_="check")
    op.create_check_constraint(
        "outbound_action_status",
        "outbound_actions",
        "status IN ('pending','leased','delivered','skipped',"
        "'permanently_failed','delivery_unknown')",
    )
    op.drop_constraint("outbound_action_kind", "outbound_actions", type_="check")
    op.alter_column(
        "outbound_actions",
        "kind",
        existing_type=sa.String(16),
        type_=sa.String(7),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "outbound_action_kind", "outbound_actions", "kind IN ('text','sticker')"
    )

    op.execute("""
    CREATE FUNCTION spec034_immutable_outbound_sequence()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.response_plan_id IS DISTINCT FROM OLD.response_plan_id
         OR NEW.conversation_id IS DISTINCT FROM OLD.conversation_id
         OR NEW.sequence_number IS DISTINCT FROM OLD.sequence_number
         OR NEW.sequence_count IS DISTINCT FROM OLD.sequence_count
         OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
         OR NEW.kind IS DISTINCT FROM OLD.kind THEN
        RAISE EXCEPTION 'SPEC-034 outbound sequence identity is immutable';
      END IF;
      RETURN NEW;
    END;
    $$
    """)
    op.execute("""
    CREATE TRIGGER trg_spec034_immutable_outbound_sequence
    BEFORE UPDATE ON outbound_actions
    FOR EACH ROW EXECUTE FUNCTION spec034_immutable_outbound_sequence()
    """)

    op.drop_constraint(
        "response_planning_regeneration_shape", "response_planning_jobs", type_="check"
    )
    op.drop_index(
        "ix_response_planning_jobs_parent_response_plan_id",
        table_name="response_planning_jobs",
    )
    op.drop_index(
        "ix_response_planning_jobs_root_response_plan_id",
        table_name="response_planning_jobs",
    )
    op.drop_constraint(
        "uq_planning_regen_root_ordinal",
        "response_planning_jobs",
        type_="unique",
    )
    op.drop_constraint(
        "uq_planning_regen_command",
        "response_planning_jobs",
        type_="unique",
    )
    op.drop_constraint(
        "fk_planning_regen_parent_plan",
        "response_planning_jobs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_planning_regen_root_plan",
        "response_planning_jobs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_planning_regen_command",
        "response_planning_jobs",
        type_="foreignkey",
    )
    op.drop_column("response_planning_jobs", "regeneration_ordinal")
    op.drop_column("response_planning_jobs", "parent_response_plan_id")
    op.drop_column("response_planning_jobs", "root_response_plan_id")
    op.drop_column("response_planning_jobs", "source_command_job_id")
