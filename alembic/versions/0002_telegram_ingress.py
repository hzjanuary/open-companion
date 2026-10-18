"""Create durable Telegram ingress inbox, outbox, and polling cursor.

Revision ID: 0002_telegram_ingress
Revises: 0001_initial_persistence
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_telegram_ingress"
down_revision: str | None = "0001_initial_persistence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def enum(name: str, values: list[str]) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True)


def timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "incoming_platform_updates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("platform_connection_id", sa.Uuid(), nullable=False),
        sa.Column("platform", enum("incoming_platform", ["telegram", "zalo"]), nullable=False),
        sa.Column("platform_update_id", sa.String(length=255), nullable=False),
        sa.Column("update_type", sa.String(length=64), nullable=False),
        sa.Column("ingress_source", enum("ingress_source", ["webhook", "polling"]), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", enum("incoming_update_status", ["received", "queued", "rejected"]), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(["platform_connection_id"], ["platform_connections.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_incoming_platform_updates"),
        sa.UniqueConstraint("platform_connection_id", "platform_update_id", name="uq_incoming_platform_updates_platform_connection_id"),
    )
    op.create_index("ix_incoming_platform_updates_pending", "incoming_platform_updates", ["status", "received_at"])
    op.create_index("ix_incoming_platform_updates_connection_received", "incoming_platform_updates", ["platform_connection_id", "received_at"])
    op.create_table(
        "ingress_outbox_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("incoming_update_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("status", enum("ingress_outbox_status", ["pending", "published"]), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_category", sa.String(length=64), nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(["incoming_update_id"], ["incoming_platform_updates.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_ingress_outbox_events"),
        sa.UniqueConstraint("incoming_update_id", name="uq_ingress_outbox_events_incoming_update_id"),
    )
    op.create_index("ix_ingress_outbox_events_pending", "ingress_outbox_events", ["status", "available_at", "created_at"])
    op.create_table(
        "polling_cursors",
        sa.Column("platform_connection_id", sa.Uuid(), nullable=False),
        sa.Column("next_offset", sa.String(length=255), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["platform_connection_id"], ["platform_connections.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("platform_connection_id", name="pk_polling_cursors"),
    )


def downgrade() -> None:
    op.drop_table("polling_cursors")
    op.drop_index("ix_ingress_outbox_events_pending", table_name="ingress_outbox_events")
    op.drop_table("ingress_outbox_events")
    op.drop_index("ix_incoming_platform_updates_connection_received", table_name="incoming_platform_updates")
    op.drop_index("ix_incoming_platform_updates_pending", table_name="incoming_platform_updates")
    op.drop_table("incoming_platform_updates")
