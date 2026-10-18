"""Add normalized conversation state and business-processing ledger.

Revision ID: 0003_conversation_domain
Revises: 0002_telegram_ingress
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_conversation_domain"
down_revision: str | None = "0002_telegram_ingress"
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
    membership_values = ["member", "restricted", "left", "kicked", "unknown"]
    op.add_column(
        "conversations",
        sa.Column(
            "assistant_membership_status",
            enum("assistant_membership_status", membership_values),
            nullable=True,
        ),
    )
    op.add_column(
        "conversations",
        sa.Column(
            "assistant_membership_updated_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "conversations",
        sa.Column(
            "last_platform_activity_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "participants",
        sa.Column(
            "membership_status",
            enum("participant_membership_status", membership_values),
            server_default="member",
            nullable=False,
        ),
    )
    op.add_column(
        "participants",
        sa.Column("is_bot", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "participants",
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "participants",
        sa.Column(
            "last_membership_updated_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "messages",
        sa.Column("platform_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column("platform_thread_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "messages", sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "messages",
        sa.Column(
            "mentions_assistant",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "messages",
        sa.Column(
            "replies_to_assistant",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column("messages", sa.Column("eligible", sa.Boolean(), nullable=True))
    op.add_column(
        "messages",
        sa.Column(
            "eligibility_reason",
            enum(
                "message_eligibility_reason",
                [
                    item
                    for item in [
                        "eligible_private_message",
                        "eligible_assistant_mentioned",
                        "eligible_reply_to_assistant",
                        "eligible_assistant_name",
                        "eligible_ambient_candidate",
                        "conversation_paused",
                        "connection_inactive",
                        "assistant_inactive",
                        "sender_is_assistant",
                        "sender_is_bot",
                        "unsupported_message_type",
                        "edited_message_no_response",
                        "not_addressed_to_assistant",
                        "membership_event_no_response",
                    ]
                ],
            ),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_messages_context", "messages", ["conversation_id", "platform_sent_at", "id"]
    )
    op.create_index(
        "ix_messages_topic_context",
        "messages",
        ["conversation_id", "platform_thread_id", "platform_sent_at"],
    )
    op.create_table(
        "conversation_processing_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("incoming_update_id", sa.Uuid(), nullable=False),
        sa.Column(
            "outcome",
            enum(
                "conversation_processing_outcome",
                [
                    "message_created",
                    "message_edited",
                    "membership_applied",
                    "ignored",
                    "rejected_malformed",
                ],
            ),
            nullable=False,
        ),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("message_id", sa.Uuid(), nullable=True),
        sa.Column("eligible", sa.Boolean(), nullable=True),
        sa.Column(
            "eligibility_reason",
            enum(
                "processing_eligibility_reason",
                [
                    "eligible_private_message",
                    "eligible_assistant_mentioned",
                    "eligible_reply_to_assistant",
                    "eligible_assistant_name",
                    "eligible_ambient_candidate",
                    "conversation_paused",
                    "connection_inactive",
                    "assistant_inactive",
                    "sender_is_assistant",
                    "sender_is_bot",
                    "unsupported_message_type",
                    "edited_message_no_response",
                    "not_addressed_to_assistant",
                    "membership_event_no_response",
                ],
            ),
            nullable=True,
        ),
        sa.Column("permanent_error", sa.String(length=64), nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(
            ["incoming_update_id"],
            ["incoming_platform_updates.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_conversation_processing_records"),
        sa.UniqueConstraint(
            "incoming_update_id",
            name="uq_conversation_processing_records_incoming_update_id",
        ),
    )


def downgrade() -> None:
    op.drop_table("conversation_processing_records")
    op.drop_index("ix_messages_topic_context", table_name="messages")
    op.drop_index("ix_messages_context", table_name="messages")
    for name in [
        "eligibility_reason",
        "eligible",
        "replies_to_assistant",
        "mentions_assistant",
        "edited_at",
        "platform_thread_id",
        "platform_sent_at",
    ]:
        op.drop_column("messages", name)
    for name in [
        "last_membership_updated_at",
        "last_seen_at",
        "is_bot",
        "membership_status",
    ]:
        op.drop_column("participants", name)
    for name in [
        "last_platform_activity_at",
        "assistant_membership_updated_at",
        "assistant_membership_status",
    ]:
        op.drop_column("conversations", name)
