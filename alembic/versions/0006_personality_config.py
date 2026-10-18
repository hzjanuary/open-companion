"""Add immutable personality profiles and conversation configuration revisions.

Revision ID: 0006_personality_config
Revises: 0005_outbound_delivery
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_personality_config"
down_revision: str | None = "0005_outbound_delivery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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
        "personality_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assistant_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("conversation_id", sa.Uuid()),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        *timestamps(),
        sa.ForeignKeyConstraint(
            ["assistant_id"], ["assistants.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assistant_id", "slug"),
    )
    op.create_table(
        "personality_profile_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_source", sa.String(64), nullable=False),
        sa.Column("created_actor", sa.String(255)),
        sa.Column("role", sa.String(64), nullable=False),
        sa.Column("primary_language", sa.String(16), nullable=False),
        sa.Column("self_reference", sa.String(32), nullable=False),
        sa.Column("default_length", sa.String(16), nullable=False),
        sa.Column("formality", sa.String(16), nullable=False),
        sa.Column("humor_level", sa.Float(), nullable=False),
        sa.Column("teasing_level", sa.Float(), nullable=False),
        sa.Column("emoji_frequency", sa.Float(), nullable=False),
        sa.Column("sticker_frequency", sa.Float(), nullable=False),
        sa.Column("use_member_names", sa.Boolean(), nullable=False),
        sa.Column("use_inside_jokes", sa.Boolean(), nullable=False),
        sa.Column("ask_follow_up_questions", sa.String(16), nullable=False),
        sa.Column("allow_sensitive_teasing", sa.Boolean(), nullable=False),
        sa.Column("stop_teasing_on_request", sa.Boolean(), nullable=False),
        sa.Column("reveal_private_memory_in_groups", sa.Boolean(), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["personality_profiles.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_id", "version_number"),
        sa.CheckConstraint(
            "humor_level >= 0 AND humor_level <= 1", name="profile_humor_range"
        ),
        sa.CheckConstraint(
            "teasing_level >= 0 AND teasing_level <= 0.4", name="profile_teasing_range"
        ),
        sa.CheckConstraint(
            "emoji_frequency >= 0 AND emoji_frequency <= 1",
            name="profile_emoji_range",
        ),
        sa.CheckConstraint(
            "sticker_frequency >= 0 AND sticker_frequency <= 1",
            name="profile_sticker_range",
        ),
        sa.CheckConstraint("use_inside_jokes = false", name="profile_no_inside_jokes"),
        sa.CheckConstraint(
            "allow_sensitive_teasing = false", name="profile_no_sensitive_teasing"
        ),
        sa.CheckConstraint(
            "stop_teasing_on_request = true", name="profile_stop_teasing_required"
        ),
        sa.CheckConstraint(
            "reveal_private_memory_in_groups = false",
            name="profile_no_private_memory_disclosure",
        ),
    )
    op.add_column(
        "assistants", sa.Column("default_personality_profile_version_id", sa.Uuid())
    )
    op.create_foreign_key(
        "fk_assistant_default_personality",
        "assistants",
        "personality_profile_versions",
        ["default_personality_profile_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_table(
        "conversation_configuration_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("personality_profile_version_id", sa.Uuid(), nullable=False),
        sa.Column("response_mode", sa.String(32), nullable=False),
        sa.Column("stickers_enabled", sa.Boolean(), nullable=False),
        sa.Column("default_length", sa.String(16)),
        sa.Column("formality", sa.String(16)),
        sa.Column("humor_level", sa.Float()),
        sa.Column("teasing_level", sa.Float()),
        sa.Column("emoji_frequency", sa.Float()),
        sa.Column("sticker_frequency", sa.Float()),
        sa.Column("use_member_names", sa.Boolean()),
        sa.Column("ask_follow_up_questions", sa.String(16)),
        sa.Column("change_source", sa.String(64), nullable=False),
        sa.Column("actor_participant_id", sa.Uuid()),
        sa.Column("reason_code", sa.String(64)),
        *timestamps(),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["personality_profile_version_id"],
            ["personality_profile_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_participant_id"], ["participants.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", "revision_number"),
        sa.CheckConstraint(
            "humor_level IS NULL OR (humor_level >= 0 AND humor_level <= 1)",
            name="configuration_humor_range",
        ),
        sa.CheckConstraint(
            "teasing_level IS NULL OR (teasing_level >= 0 AND teasing_level <= 0.4)",
            name="configuration_teasing_range",
        ),
        sa.CheckConstraint(
            "emoji_frequency IS NULL OR "
            "(emoji_frequency >= 0 AND emoji_frequency <= 1)",
            name="configuration_emoji_range",
        ),
        sa.CheckConstraint(
            "sticker_frequency IS NULL OR "
            "(sticker_frequency >= 0 AND sticker_frequency <= 1)",
            name="configuration_sticker_range",
        ),
    )
    op.add_column(
        "conversations", sa.Column("current_configuration_revision_id", sa.Uuid())
    )
    op.create_foreign_key(
        "fk_conversation_current_configuration",
        "conversations",
        "conversation_configuration_revisions",
        ["current_configuration_revision_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.add_column(
        "response_planning_jobs", sa.Column("personality_profile_version_id", sa.Uuid())
    )
    op.add_column(
        "response_planning_jobs", sa.Column("configuration_revision_id", sa.Uuid())
    )
    op.create_foreign_key(
        "fk_planning_profile_snapshot",
        "response_planning_jobs",
        "personality_profile_versions",
        ["personality_profile_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_planning_configuration_snapshot",
        "response_planning_jobs",
        "conversation_configuration_revisions",
        ["configuration_revision_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    for name in ("fk_planning_configuration_snapshot", "fk_planning_profile_snapshot"):
        op.drop_constraint(name, "response_planning_jobs", type_="foreignkey")
    op.drop_column("response_planning_jobs", "configuration_revision_id")
    op.drop_column("response_planning_jobs", "personality_profile_version_id")
    op.drop_constraint(
        "fk_conversation_current_configuration", "conversations", type_="foreignkey"
    )
    op.drop_column("conversations", "current_configuration_revision_id")
    op.drop_table("conversation_configuration_revisions")
    op.drop_constraint(
        "fk_assistant_default_personality", "assistants", type_="foreignkey"
    )
    op.drop_column("assistants", "default_personality_profile_version_id")
    op.drop_table("personality_profile_versions")
    op.drop_table("personality_profiles")
