"""Add authoritative Telegram replies and ordered response delivery.

Revision ID: 0023_telegram_reply_ordered_delivery
Revises: 0022_knowledge_base_rag
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_telegram_reply_ordered_delivery"
down_revision: str | None = "0022_knowledge_base_rag"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("reply_to_platform_message_id", sa.String(255)))
    op.drop_constraint(
        "fk_messages_reply_to_message_id_messages", "messages", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_messages_reply_conversation",
        "messages",
        "messages",
        ["reply_to_message_id", "conversation_id"],
        ["id", "conversation_id"],
        ondelete="RESTRICT",
    )

    op.add_column("outbound_actions", sa.Column("sequence_count", sa.Integer()))
    op.execute("""
        UPDATE outbound_actions AS action
           SET sequence_count = grouped.sequence_count
          FROM (
                SELECT response_plan_id, max(sequence_number) AS sequence_count
                  FROM outbound_actions
                 GROUP BY response_plan_id
               ) AS grouped
         WHERE action.response_plan_id = grouped.response_plan_id
    """)
    op.alter_column(
        "outbound_actions",
        "sequence_count",
        nullable=False,
        server_default="1",
    )
    op.create_check_constraint(
        "outbound_action_sequence_bounds",
        "outbound_actions",
        "sequence_number BETWEEN 1 AND sequence_count "
        "AND sequence_count BETWEEN 1 AND 5",
    )
    op.create_check_constraint(
        "outbound_action_text_size",
        "outbound_actions",
        "text IS NULL OR char_length(text) <= 3400",
    )
    op.create_check_constraint(
        "response_plan_text_size",
        "response_plans",
        "text IS NULL OR char_length(text) <= 13600",
    )
    op.drop_constraint(
        "fk_outbound_actions_reply_to_message_id_messages",
        "outbound_actions",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_outbound_actions_reply_conversation",
        "outbound_actions",
        "messages",
        ["reply_to_message_id", "conversation_id"],
        ["id", "conversation_id"],
        ondelete="RESTRICT",
    )

    op.add_column(
        "outbound_delivery_attempts",
        sa.Column(
            "reply_fallback_used",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "outbound_delivery_attempts",
        sa.Column("reply_fallback_error_code", sa.String(64)),
    )
    op.create_check_constraint(
        "outbound_attempt_reply_fallback_shape",
        "outbound_delivery_attempts",
        "(NOT reply_fallback_used AND reply_fallback_error_code IS NULL) OR "
        "(reply_fallback_used AND reply_fallback_error_code IS NOT NULL)",
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


def downgrade() -> None:
    op.execute("""
    DO $$
    BEGIN
      IF EXISTS (
           SELECT 1 FROM messages
            WHERE reply_to_platform_message_id IS NOT NULL
         ) OR EXISTS (
           SELECT 1 FROM outbound_actions WHERE sequence_count > 1
         ) OR EXISTS (
           SELECT 1 FROM outbound_delivery_attempts
            WHERE reply_fallback_used OR reply_fallback_error_code IS NOT NULL
         ) THEN
        RAISE EXCEPTION 'SPEC-034 reply or ordered delivery state blocks downgrade';
      END IF;
    END;
    $$;
    """)
    op.execute(
        "DROP TRIGGER trg_spec034_immutable_outbound_sequence ON outbound_actions"
    )
    op.execute("DROP FUNCTION spec034_immutable_outbound_sequence()")

    op.drop_constraint(
        "outbound_attempt_reply_fallback_shape",
        "outbound_delivery_attempts",
        type_="check",
    )
    op.drop_column("outbound_delivery_attempts", "reply_fallback_error_code")
    op.drop_column("outbound_delivery_attempts", "reply_fallback_used")

    op.drop_constraint(
        "fk_outbound_actions_reply_conversation",
        "outbound_actions",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_outbound_actions_reply_to_message_id_messages",
        "outbound_actions",
        "messages",
        ["reply_to_message_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint("response_plan_text_size", "response_plans", type_="check")
    op.drop_constraint(
        "outbound_action_text_size",
        "outbound_actions",
        type_="check",
    )
    op.drop_constraint(
        "outbound_action_sequence_bounds",
        "outbound_actions",
        type_="check",
    )
    op.drop_column("outbound_actions", "sequence_count")

    op.drop_constraint("fk_messages_reply_conversation", "messages", type_="foreignkey")
    op.create_foreign_key(
        "fk_messages_reply_to_message_id_messages",
        "messages",
        "messages",
        ["reply_to_message_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_column("messages", "reply_to_platform_message_id")
