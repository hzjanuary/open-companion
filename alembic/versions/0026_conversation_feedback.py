"""Add explicit conversation feedback current state and immutable events.

Revision ID: 0026_conversation_feedback
Revises: 0025_telegram_voice_tts
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026_conversation_feedback"
down_revision: str | None = "0025_telegram_voice_tts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _scope_columns() -> list[sa.Column[object]]:
    return [
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("assistant_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("response_plan_id", sa.Uuid(), nullable=False),
        sa.Column("participant_id", sa.Uuid(), nullable=False),
        sa.Column("target_message_id", sa.Uuid(), nullable=False),
        sa.Column("target_outbound_action_id", sa.Uuid(), nullable=False),
        sa.Column("value", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
    ]


def _scope_foreign_keys(prefix: str) -> list[sa.ForeignKeyConstraint]:
    return [
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["control_tenants.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["assistant_id", "tenant_id"],
            ["assistants.id", "assistants.tenant_id"],
            name=f"fk_{prefix}_assistant_owner",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["platform_connections.id", "platform_connections.tenant_id"],
            name=f"fk_{prefix}_connection_owner",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "assistant_id"],
            ["platform_connections.id", "platform_connections.assistant_id"],
            name=f"fk_{prefix}_connection_assistant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id", "connection_id"],
            ["conversations.id", "conversations.platform_connection_id"],
            name=f"fk_{prefix}_conversation_connection",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["response_plan_id"], ["response_plans.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["participant_id", "conversation_id"],
            ["participants.id", "participants.conversation_id"],
            name=f"fk_{prefix}_participant_conversation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_message_id", "conversation_id"],
            ["messages.id", "messages.conversation_id"],
            name=f"fk_{prefix}_target_message",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_outbound_action_id", "conversation_id"],
            ["outbound_actions.id", "outbound_actions.conversation_id"],
            name=f"fk_{prefix}_target_action",
            ondelete="RESTRICT",
        ),
    ]


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_outbound_actions_id_conversation",
        "outbound_actions",
        ["id", "conversation_id"],
    )
    op.create_table(
        "conversation_feedback",
        sa.Column("id", sa.Uuid(), primary_key=True),
        *_scope_columns(),
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
        *_scope_foreign_keys("conversation_feedback"),
        sa.UniqueConstraint(
            "tenant_id",
            "assistant_id",
            "connection_id",
            "conversation_id",
            "response_plan_id",
            "participant_id",
            name="uq_conversation_feedback_current",
        ),
        sa.UniqueConstraint(
            "id",
            "tenant_id",
            "assistant_id",
            "connection_id",
            "conversation_id",
            "response_plan_id",
            "participant_id",
            name="uq_conversation_feedback_id_scope",
        ),
        sa.CheckConstraint(
            "value IN ('helpful','unhelpful')", name="conversation_feedback_value"
        ),
        sa.CheckConstraint(
            "revision BETWEEN 1 AND 10", name="conversation_feedback_revision"
        ),
    )
    op.create_index(
        "ix_conversation_feedback_participant",
        "conversation_feedback",
        ["participant_id", "created_at"],
    )
    op.create_index(
        "ix_conversation_feedback_response",
        "conversation_feedback",
        ["response_plan_id"],
    )
    op.create_table(
        "conversation_feedback_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("feedback_id", sa.Uuid(), nullable=False),
        *_scope_columns(),
        sa.Column("command_job_id", sa.Uuid(), nullable=False),
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
            [
                "feedback_id",
                "tenant_id",
                "assistant_id",
                "connection_id",
                "conversation_id",
                "response_plan_id",
                "participant_id",
            ],
            [
                "conversation_feedback.id",
                "conversation_feedback.tenant_id",
                "conversation_feedback.assistant_id",
                "conversation_feedback.connection_id",
                "conversation_feedback.conversation_id",
                "conversation_feedback.response_plan_id",
                "conversation_feedback.participant_id",
            ],
            name="fk_conversation_feedback_events_current_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_message_id", "conversation_id"],
            ["messages.id", "messages.conversation_id"],
            name="fk_conversation_feedback_events_target_message",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_outbound_action_id", "conversation_id"],
            ["outbound_actions.id", "outbound_actions.conversation_id"],
            name="fk_conversation_feedback_events_target_action",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["command_job_id"], ["telegram_command_jobs.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("command_job_id"),
        sa.UniqueConstraint("feedback_id", "revision"),
        sa.CheckConstraint(
            "value IN ('helpful','unhelpful')",
            name="conversation_feedback_event_value",
        ),
        sa.CheckConstraint(
            "revision BETWEEN 1 AND 10",
            name="conversation_feedback_event_revision",
        ),
    )
    op.create_index(
        "ix_conversation_feedback_events_participant",
        "conversation_feedback_events",
        ["participant_id", "created_at"],
    )

    op.execute("""
    CREATE FUNCTION spec039_feedback_target_valid(
      p_tenant uuid, p_assistant uuid, p_connection uuid, p_conversation uuid,
      p_plan uuid, p_participant uuid, p_message uuid, p_action uuid
    ) RETURNS boolean LANGUAGE sql STABLE AS $$
      SELECT EXISTS (
        SELECT 1
          FROM control_tenants t
          JOIN assistants ast ON ast.tenant_id = t.id
          JOIN platform_connections pc
            ON pc.tenant_id = t.id AND pc.assistant_id = ast.id
          JOIN conversations c ON c.platform_connection_id = pc.id
          JOIN participants pt
            ON pt.conversation_id = c.id AND pt.id = p_participant
          JOIN messages m ON m.conversation_id = c.id AND m.id = p_message
          JOIN outbound_actions a
            ON a.conversation_id = c.id AND a.id = p_action
          JOIN response_plans rp ON rp.id = p_plan
          JOIN response_planning_jobs pj ON pj.id = rp.planning_job_id
          LEFT JOIN generated_voice_artifacts va
            ON va.id = a.generated_voice_artifact_id
         WHERE t.id = p_tenant AND ast.id = p_assistant
           AND pc.id = p_connection AND c.id = p_conversation
           AND t.status = 'active' AND ast.status = 'active'
           AND pc.status = 'active' AND pc.platform = 'telegram'
           AND c.status = 'active' AND pt.privacy_deleted_at IS NULL
           AND m.direction = 'outgoing' AND m.content_redacted_at IS NULL
           AND a.status = 'delivered' AND rp.should_respond
           AND rp.content_redacted_at IS NULL AND pj.conversation_id = c.id
           AND NOT EXISTS (
             SELECT 1 FROM outbound_actions uncertain
              WHERE uncertain.response_plan_id = rp.id
                AND uncertain.status = 'delivery_unknown'
           )
           AND (
             (m.message_type = 'text' AND a.kind = 'text'
                AND m.outbound_action_id = a.id AND a.response_plan_id = rp.id)
             OR
             (m.message_type = 'text' AND a.kind = 'edit_text'
                AND a.edit_target_message_id = m.id
                AND a.response_plan_id = rp.id)
             OR
             (m.message_type = 'voice' AND a.kind = 'voice'
                AND m.outbound_action_id = a.id
                AND va.conversation_id = c.id
                AND va.source_response_plan_id = rp.id)
           )
      )
    $$
    """)
    op.execute("""
    CREATE FUNCTION spec039_validate_feedback_current()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NOT spec039_feedback_target_valid(
        NEW.tenant_id, NEW.assistant_id, NEW.connection_id, NEW.conversation_id,
        NEW.response_plan_id, NEW.participant_id, NEW.target_message_id,
        NEW.target_outbound_action_id
      ) THEN
        RAISE EXCEPTION 'SPEC-039 feedback target authority is inconsistent';
      END IF;
      IF TG_OP = 'UPDATE' THEN
        IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
           OR NEW.assistant_id IS DISTINCT FROM OLD.assistant_id
           OR NEW.connection_id IS DISTINCT FROM OLD.connection_id
           OR NEW.conversation_id IS DISTINCT FROM OLD.conversation_id
           OR NEW.response_plan_id IS DISTINCT FROM OLD.response_plan_id
           OR NEW.participant_id IS DISTINCT FROM OLD.participant_id
           OR NEW.target_message_id IS DISTINCT FROM OLD.target_message_id
           OR NEW.target_outbound_action_id
                IS DISTINCT FROM OLD.target_outbound_action_id THEN
          RAISE EXCEPTION 'SPEC-039 feedback identity is immutable';
        END IF;
        IF NEW.value IS NOT DISTINCT FROM OLD.value
           OR NEW.revision <> OLD.revision + 1 THEN
          RAISE EXCEPTION 'SPEC-039 feedback revision is invalid';
        END IF;
      END IF;
      RETURN NEW;
    END $$
    """)
    op.execute("""
    CREATE TRIGGER trg_spec039_validate_feedback_current
    BEFORE INSERT OR UPDATE ON conversation_feedback
    FOR EACH ROW EXECUTE FUNCTION spec039_validate_feedback_current()
    """)
    op.execute("""
    CREATE FUNCTION spec039_validate_feedback_event()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE command_conversation uuid; command_participant uuid;
            command_message uuid; command_name text; reply_target uuid;
    BEGIN
      IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'SPEC-039 feedback events are immutable';
      END IF;
      IF TG_OP = 'DELETE' THEN
        IF EXISTS (
          SELECT 1 FROM participants p
           WHERE p.id = OLD.participant_id
             AND p.privacy_deleted_at IS NOT NULL
        ) OR EXISTS (
          SELECT 1 FROM response_plans p
           WHERE p.id = OLD.response_plan_id
             AND p.content_redacted_at IS NOT NULL
        ) THEN
          RETURN OLD;
        END IF;
        RAISE EXCEPTION 'SPEC-039 feedback events are immutable';
      END IF;
      SELECT cj.conversation_id, cj.participant_id, cj.message_id, cj.command_name,
             cm.reply_to_message_id
        INTO command_conversation, command_participant, command_message,
             command_name, reply_target
        FROM telegram_command_jobs cj
        JOIN messages cm ON cm.id = cj.message_id
       WHERE cj.id = NEW.command_job_id;
      IF command_name <> 'feedback'
         OR command_conversation <> NEW.conversation_id
         OR command_participant <> NEW.participant_id
         OR reply_target <> NEW.target_message_id
         OR NOT spec039_feedback_target_valid(
           NEW.tenant_id, NEW.assistant_id, NEW.connection_id,
           NEW.conversation_id, NEW.response_plan_id, NEW.participant_id,
           NEW.target_message_id, NEW.target_outbound_action_id
         ) THEN
        RAISE EXCEPTION 'SPEC-039 feedback event authority is inconsistent';
      END IF;
      RETURN NEW;
    END $$
    """)
    op.execute("""
    CREATE TRIGGER trg_spec039_validate_feedback_event
    BEFORE INSERT OR UPDATE OR DELETE ON conversation_feedback_events
    FOR EACH ROW EXECUTE FUNCTION spec039_validate_feedback_event()
    """)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM conversation_feedback)
         OR EXISTS (SELECT 1 FROM conversation_feedback_events)
      THEN
        RAISE EXCEPTION 'SPEC-039 conversation feedback state blocks downgrade';
      END IF;
    END $$;
    """)
    op.execute(
        "DROP TRIGGER trg_spec039_validate_feedback_event "
        "ON conversation_feedback_events"
    )
    op.execute("DROP FUNCTION spec039_validate_feedback_event()")
    op.execute(
        "DROP TRIGGER trg_spec039_validate_feedback_current ON conversation_feedback"
    )
    op.execute("DROP FUNCTION spec039_validate_feedback_current()")
    op.execute(
        "DROP FUNCTION spec039_feedback_target_valid(uuid, uuid, uuid, uuid, uuid, "
        "uuid, uuid, uuid)"
    )
    op.drop_index(
        "ix_conversation_feedback_events_participant",
        table_name="conversation_feedback_events",
    )
    op.drop_table("conversation_feedback_events")
    op.drop_index(
        "ix_conversation_feedback_response", table_name="conversation_feedback"
    )
    op.drop_index(
        "ix_conversation_feedback_participant", table_name="conversation_feedback"
    )
    op.drop_table("conversation_feedback")
    op.drop_constraint(
        "uq_outbound_actions_id_conversation",
        "outbound_actions",
        type_="unique",
    )
