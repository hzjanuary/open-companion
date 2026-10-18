"""Create SPEC-002 platform-independent persistence tables.

Revision ID: 0001_initial_persistence
Revises:
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_persistence"
down_revision: str | None = None
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
        "assistants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("status", enum("assistant_status", ["active", "disabled"]), nullable=False),
        *timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_assistants"),
    )
    op.create_table(
        "platform_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assistant_id", sa.Uuid(), nullable=False),
        sa.Column("platform", enum("platform", ["telegram", "zalo"]), nullable=False),
        sa.Column("external_bot_id", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            enum("platform_connection_status", ["active", "disabled", "error"]),
            nullable=False,
        ),
        sa.Column("credential_reference", sa.String(length=255), nullable=True),
        sa.Column(
            "configuration",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        *timestamps(),
        sa.ForeignKeyConstraint(
            ["assistant_id"], ["assistants.id"], name="fk_platform_connections_assistant_id_assistants", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_platform_connections"),
        sa.UniqueConstraint("platform", "external_bot_id", name="uq_platform_connections_platform"),
    )
    op.create_index("ix_platform_connections_assistant_id", "platform_connections", ["assistant_id"])
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("platform_connection_id", sa.Uuid(), nullable=False),
        sa.Column("platform_conversation_id", sa.String(length=255), nullable=False),
        sa.Column(
            "conversation_type", enum("conversation_type", ["private", "group", "supergroup"]), nullable=False
        ),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("status", enum("conversation_status", ["active", "paused"]), nullable=False),
        sa.Column(
            "response_mode",
            enum("response_mode", ["mention_only", "mention_and_name", "ambient_selective", "paused"]),
            nullable=False,
        ),
        sa.Column(
            "settings", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        *timestamps(),
        sa.ForeignKeyConstraint(
            ["platform_connection_id"], ["platform_connections.id"], name="fk_conversations_platform_connection_id_platform_connections", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conversations"),
        sa.UniqueConstraint("platform_connection_id", "platform_conversation_id", name="uq_conversations_platform_connection_id"),
    )
    op.create_index("ix_conversations_platform_connection_id", "conversations", ["platform_connection_id"])
    op.create_table(
        "participants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("platform_user_id", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("role", enum("participant_role", ["member", "administrator", "owner"]), nullable=False),
        sa.Column("mention_allowed", sa.Boolean(), nullable=False),
        sa.Column("teasing_allowed", sa.Boolean(), nullable=False),
        sa.Column(
            "metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        *timestamps(),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], name="fk_participants_conversation_id_conversations", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_participants"),
        sa.UniqueConstraint("conversation_id", "platform_user_id", name="uq_participants_conversation_id"),
    )
    op.create_index("ix_participants_conversation_id", "participants", ["conversation_id"])
    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("participant_id", sa.Uuid(), nullable=True),
        sa.Column("platform_message_id", sa.String(length=255), nullable=False),
        sa.Column("direction", enum("message_direction", ["incoming", "outgoing"]), nullable=False),
        sa.Column("message_type", enum("message_type", ["text", "sticker", "other"]), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("reply_to_message_id", sa.Uuid(), nullable=True),
        sa.Column(
            "metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "processing_status",
            enum("message_processing_status", ["pending", "processed", "failed"]),
            nullable=False,
        ),
        *timestamps(),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], name="fk_messages_conversation_id_conversations", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["participant_id"], ["participants.id"], name="fk_messages_participant_id_participants", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["reply_to_message_id"], ["messages.id"], name="fk_messages_reply_to_message_id_messages", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_messages"),
        sa.UniqueConstraint("conversation_id", "platform_message_id", name="uq_messages_conversation_id"),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_index("ix_messages_participant_id", "messages", ["participant_id"])
    op.create_index("ix_messages_reply_to_message_id", "messages", ["reply_to_message_id"])


def downgrade() -> None:
    op.drop_index("ix_messages_reply_to_message_id", table_name="messages")
    op.drop_index("ix_messages_participant_id", table_name="messages")
    op.drop_index("ix_messages_conversation_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_participants_conversation_id", table_name="participants")
    op.drop_table("participants")
    op.drop_index("ix_conversations_platform_connection_id", table_name="conversations")
    op.drop_table("conversations")
    op.drop_index("ix_platform_connections_assistant_id", table_name="platform_connections")
    op.drop_table("platform_connections")
    op.drop_table("assistants")
