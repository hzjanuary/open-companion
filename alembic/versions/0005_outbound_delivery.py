"""Add durable outbound actions and delivery attempts.

Revision ID: 0005_outbound_delivery
Revises: 0004_response_planning
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_outbound_delivery"
down_revision: str | None = "0004_response_planning"
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
    op.create_table(
        "outbound_actions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("response_plan_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column(
            "kind", enum("outbound_action_kind", ["text", "sticker"]), nullable=False
        ),
        sa.Column(
            "status",
            enum(
                "outbound_action_status",
                [
                    "pending",
                    "leased",
                    "delivered",
                    "skipped",
                    "permanently_failed",
                    "delivery_unknown",
                ],
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
        sa.Column("lease_owner", sa.String(length=255)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reply_to_message_id", sa.Uuid()),
        sa.Column("message_thread_id", sa.String(length=255)),
        sa.Column("text", sa.Text()),
        sa.Column(
            "mention_participant_ids", sa.dialects.postgresql.JSONB(), nullable=False
        ),
        sa.Column(
            "sticker_intent",
            enum(
                "outbound_sticker_intent",
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
        ),
        sa.Column("delivered_message_id", sa.Uuid()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("delivery_unknown_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_category", sa.String(length=64)),
        sa.Column("last_error_code", sa.String(length=64)),
        sa.Column("last_error_at", sa.DateTime(timezone=True)),
        *timestamps(),
        sa.ForeignKeyConstraint(
            ["response_plan_id"], ["response_plans.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["reply_to_message_id"], ["messages.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["delivered_message_id"], ["messages.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_outbound_actions"),
        sa.UniqueConstraint(
            "response_plan_id",
            "sequence_number",
            name="uq_outbound_actions_response_plan_id",
        ),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_outbound_actions_idempotency_key"
        ),
        sa.UniqueConstraint(
            "delivered_message_id", name="uq_outbound_actions_delivered_message_id"
        ),
        sa.CheckConstraint(
            "(kind = 'text' AND text IS NOT NULL AND btrim(text) <> '' "
            "AND sticker_intent IS NULL) OR (kind = 'sticker' AND text IS NULL "
            "AND sticker_intent IS NOT NULL)",
            name="outbound_action_payload",
        ),
    )
    op.create_index(
        "ix_outbound_actions_claim",
        "outbound_actions",
        ["status", "available_at", "created_at"],
    )
    op.create_index(
        "ix_outbound_actions_lease", "outbound_actions", ["status", "lease_expires_at"]
    )
    op.add_column("messages", sa.Column("outbound_action_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_messages_outbound_action_id_outbound_actions",
        "messages",
        "outbound_actions",
        ["outbound_action_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_messages_outbound_action_id", "messages", ["outbound_action_id"]
    )
    op.create_table(
        "outbound_delivery_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("outbound_action_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column(
            "platform", sa.String(length=32), nullable=False, server_default="telegram"
        ),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("external_started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("latency_milliseconds", sa.Integer()),
        sa.Column(
            "status",
            enum(
                "outbound_delivery_attempt_status",
                ["started", "confirmed", "rejected", "unknown"],
            ),
            nullable=False,
        ),
        sa.Column(
            "certainty",
            enum(
                "outbound_delivery_certainty",
                ["not_sent", "rejected", "confirmed", "unknown"],
            ),
            nullable=False,
        ),
        sa.Column("error_category", sa.String(length=64)),
        sa.Column("error_code", sa.String(length=64)),
        sa.Column("retry_after_seconds", sa.Float()),
        sa.Column("migration_conversation_id", sa.String(length=255)),
        *timestamps(),
        sa.ForeignKeyConstraint(
            ["outbound_action_id"], ["outbound_actions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_outbound_delivery_attempts"),
        sa.UniqueConstraint(
            "outbound_action_id",
            "attempt_number",
            name="uq_outbound_delivery_attempts_outbound_action_id",
        ),
    )
    op.create_table(
        "outbound_recovery_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("outbound_action_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(
            ["outbound_action_id"], ["outbound_actions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_outbound_recovery_events"),
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS outbound_recovery_events")
    op.drop_table("outbound_delivery_attempts")
    op.drop_constraint("uq_messages_outbound_action_id", "messages", type_="unique")
    op.drop_constraint(
        "fk_messages_outbound_action_id_outbound_actions",
        "messages",
        type_="foreignkey",
    )
    op.drop_column("messages", "outbound_action_id")
    op.drop_index("ix_outbound_actions_lease", table_name="outbound_actions")
    op.drop_index("ix_outbound_actions_claim", table_name="outbound_actions")
    op.drop_table("outbound_actions")
