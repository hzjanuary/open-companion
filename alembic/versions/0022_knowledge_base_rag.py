"""Add PostgreSQL-authoritative Assistant knowledge and derived-index jobs.

Revision ID: 0022_knowledge_base_rag
Revises: 0021_multi_assistant_tenancy
"""

# SQL constraint expressions are intentionally kept as auditable single strings.
# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_knowledge_base_rag"
down_revision: str | None = "0021_multi_assistant_tenancy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column[object]]:
    return [
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
    ]


def upgrade() -> None:
    op.add_column(
        "assistants",
        sa.Column(
            "knowledge_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "response_planning_jobs",
        sa.Column(
            "knowledge_provenance",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.execute(r"""
    CREATE FUNCTION spec033_valid_knowledge_provenance(value jsonb)
    RETURNS boolean LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
      SELECT jsonb_typeof(value) = 'array'
         AND jsonb_array_length(value) <= 6
         AND NOT EXISTS (
           SELECT 1
             FROM jsonb_array_elements(value) AS entries(item)
            WHERE jsonb_typeof(item) <> 'object'
               OR (SELECT array_agg(key ORDER BY key)
                     FROM jsonb_object_keys(item) AS keys(key))
                    IS DISTINCT FROM ARRAY[
                      'chunk_id', 'document_id', 'knowledge_base_id', 'revision_id'
                    ]::text[]
               OR EXISTS (
                    SELECT 1
                      FROM jsonb_each(item) AS fields(key, field_value)
                     WHERE jsonb_typeof(field_value) <> 'string'
                        OR trim(both '"' from field_value::text)
                           !~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
                  )
         )
    $$
    """)
    op.create_check_constraint(
        "response_planning_knowledge_provenance_shape",
        "response_planning_jobs",
        "spec033_valid_knowledge_provenance(knowledge_provenance::jsonb)",
    )

    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("assistant_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column("retired_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.UniqueConstraint(
            "assistant_id", "slug", name="uq_knowledge_bases_assistant_slug"
        ),
        sa.UniqueConstraint(
            "id", "tenant_id", "assistant_id", name="uq_knowledge_bases_owner"
        ),
        sa.ForeignKeyConstraint(
            ["assistant_id", "tenant_id"],
            ["assistants.id", "assistants.tenant_id"],
            name="fk_knowledge_bases_assistant_owner",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN ('draft','active','disabled','retired')",
            name="knowledge_base_status",
        ),
        sa.CheckConstraint("revision > 0", name="knowledge_base_revision"),
    )
    op.create_index(
        "ix_knowledge_bases_owner_status",
        "knowledge_bases",
        ["tenant_id", "assistant_id", "status"],
    )

    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("assistant_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("source_label", sa.String(160)),
        sa.Column("source_reference", sa.String(2048)),
        sa.Column("content_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column(
            "latest_revision_number", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("current_revision_id", sa.Uuid()),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.UniqueConstraint(
            "knowledge_base_id", "slug", name="uq_knowledge_documents_base_slug"
        ),
        sa.UniqueConstraint(
            "id",
            "knowledge_base_id",
            "tenant_id",
            "assistant_id",
            name="uq_knowledge_documents_owner",
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id", "tenant_id", "assistant_id"],
            [
                "knowledge_bases.id",
                "knowledge_bases.tenant_id",
                "knowledge_bases.assistant_id",
            ],
            name="fk_knowledge_documents_base_owner",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "content_type IN ('text/plain','text/markdown')",
            name="knowledge_document_content_type",
        ),
        sa.CheckConstraint(
            "status IN ('active','deleted')", name="knowledge_document_status"
        ),
        sa.CheckConstraint(
            "latest_revision_number >= 0 AND revision > 0",
            name="knowledge_document_revisions_positive",
        ),
    )

    op.create_table(
        "knowledge_document_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("assistant_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text()),
        sa.Column("content_checksum", sa.String(64)),
        sa.Column("character_count", sa.Integer(), nullable=False),
        sa.Column("byte_count", sa.Integer(), nullable=False),
        sa.Column("chunking_version", sa.String(64), nullable=False),
        sa.Column(
            "index_state", sa.String(16), nullable=False, server_default="pending"
        ),
        sa.Column("created_by_identity_id", sa.Uuid(), nullable=False),
        sa.Column("ready_at", sa.DateTime(timezone=True)),
        sa.Column("failed_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.UniqueConstraint(
            "document_id",
            "revision_number",
            name="uq_knowledge_revisions_document_number",
        ),
        sa.UniqueConstraint(
            "id",
            "document_id",
            "knowledge_base_id",
            "tenant_id",
            "assistant_id",
            name="uq_knowledge_revisions_owner",
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "knowledge_base_id", "tenant_id", "assistant_id"],
            [
                "knowledge_documents.id",
                "knowledge_documents.knowledge_base_id",
                "knowledge_documents.tenant_id",
                "knowledge_documents.assistant_id",
            ],
            name="fk_knowledge_revisions_document_owner",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_identity_id"],
            ["control_operator_identities.id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("revision_number > 0", name="knowledge_revision_number"),
        sa.CheckConstraint(
            "character_count BETWEEN 0 AND 200000 AND byte_count BETWEEN 0 AND 262144",
            name="knowledge_revision_size",
        ),
        sa.CheckConstraint(
            "index_state IN ('pending','indexing','ready','failed','deleting','deleted')",
            name="knowledge_revision_index_state",
        ),
        sa.CheckConstraint(
            "(deleted_at IS NULL AND content IS NOT NULL AND content_checksum IS NOT NULL) "
            "OR (deleted_at IS NOT NULL AND content IS NULL AND content_checksum IS NULL)",
            name="knowledge_revision_redaction",
        ),
    )
    op.create_foreign_key(
        "fk_knowledge_documents_current_revision",
        "knowledge_documents",
        "knowledge_document_revisions",
        ["current_revision_id", "id", "knowledge_base_id", "tenant_id", "assistant_id"],
        ["id", "document_id", "knowledge_base_id", "tenant_id", "assistant_id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("assistant_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text()),
        sa.Column("content_checksum", sa.String(64)),
        sa.Column("character_count", sa.Integer(), nullable=False),
        sa.Column("embedding_version", sa.String(160)),
        sa.Column("index_schema_version", sa.String(64)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.UniqueConstraint(
            "revision_id", "ordinal", name="uq_knowledge_chunks_revision_ordinal"
        ),
        sa.UniqueConstraint(
            "id",
            "revision_id",
            "document_id",
            "knowledge_base_id",
            "tenant_id",
            "assistant_id",
            name="uq_knowledge_chunks_owner",
        ),
        sa.ForeignKeyConstraint(
            [
                "revision_id",
                "document_id",
                "knowledge_base_id",
                "tenant_id",
                "assistant_id",
            ],
            [
                "knowledge_document_revisions.id",
                "knowledge_document_revisions.document_id",
                "knowledge_document_revisions.knowledge_base_id",
                "knowledge_document_revisions.tenant_id",
                "knowledge_document_revisions.assistant_id",
            ],
            name="fk_knowledge_chunks_revision_owner",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "ordinal BETWEEN 0 AND 255 AND start_offset >= 0 AND end_offset > start_offset",
            name="knowledge_chunk_offsets",
        ),
        sa.CheckConstraint(
            "character_count BETWEEN 1 AND 1200", name="knowledge_chunk_size"
        ),
        sa.CheckConstraint(
            "(deleted_at IS NULL AND content IS NOT NULL AND content_checksum IS NOT NULL) "
            "OR (deleted_at IS NOT NULL AND content IS NULL AND content_checksum IS NULL)",
            name="knowledge_chunk_redaction",
        ),
    )
    op.create_index(
        "ix_knowledge_chunks_revalidation",
        "knowledge_chunks",
        ["tenant_id", "assistant_id", "knowledge_base_id", "id"],
    )

    op.create_table(
        "knowledge_index_collections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("embedding_version", sa.String(160), nullable=False),
        sa.Column("physical_collection", sa.String(160), nullable=False),
        sa.Column("index_schema_version", sa.String(64), nullable=False),
        sa.Column(
            "active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "activated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("retired_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.UniqueConstraint(
            "embedding_version",
            "physical_collection",
            name="uq_knowledge_collections_version_physical",
        ),
    )
    op.create_index(
        "uq_knowledge_collections_one_active",
        "knowledge_index_collections",
        ["embedding_version"],
        unique=True,
        postgresql_where=sa.text("active"),
    )

    op.create_table(
        "knowledge_index_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("assistant_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("embedding_version", sa.String(160), nullable=False),
        sa.Column("target_collection", sa.String(160), nullable=False),
        sa.Column("index_schema_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_owner", sa.String(255)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_category", sa.String(64)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.UniqueConstraint(
            "chunk_id",
            "operation",
            "embedding_version",
            "target_collection",
            name="uq_knowledge_index_jobs_idempotency",
        ),
        sa.ForeignKeyConstraint(
            [
                "chunk_id",
                "revision_id",
                "document_id",
                "knowledge_base_id",
                "tenant_id",
                "assistant_id",
            ],
            [
                "knowledge_chunks.id",
                "knowledge_chunks.revision_id",
                "knowledge_chunks.document_id",
                "knowledge_chunks.knowledge_base_id",
                "knowledge_chunks.tenant_id",
                "knowledge_chunks.assistant_id",
            ],
            name="fk_knowledge_jobs_chunk_owner",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "operation IN ('upsert','delete')", name="knowledge_job_operation"
        ),
        sa.CheckConstraint(
            "status IN ('pending','leased','completed','failed')",
            name="knowledge_job_status",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="knowledge_job_attempts"),
    )
    op.create_index(
        "ix_knowledge_index_jobs_claim",
        "knowledge_index_jobs",
        ["status", "available_at", "created_at"],
    )
    op.create_index(
        "ix_knowledge_index_jobs_lease",
        "knowledge_index_jobs",
        ["status", "lease_expires_at"],
    )

    op.add_column(
        "provider_work_policy_snapshots", sa.Column("knowledge_index_job_id", sa.Uuid())
    )
    op.add_column(
        "provider_usage_attempts", sa.Column("knowledge_index_job_id", sa.Uuid())
    )
    op.create_foreign_key(
        "fk_provider_snapshot_knowledge_job",
        "provider_work_policy_snapshots",
        "knowledge_index_jobs",
        ["knowledge_index_job_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_provider_usage_knowledge_job",
        "provider_usage_attempts",
        "knowledge_index_jobs",
        ["knowledge_index_job_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "provider_work_snapshot_one_source",
        "provider_work_policy_snapshots",
        type_="check",
    )
    op.drop_constraint(
        "provider_usage_attempt_one_source",
        "provider_usage_attempts",
        type_="check",
    )
    op.create_check_constraint(
        "provider_work_snapshot_one_source",
        "provider_work_policy_snapshots",
        "num_nonnulls(planning_job_id, summary_job_id, semantic_index_job_id, knowledge_index_job_id) = 1",
    )
    op.create_check_constraint(
        "provider_usage_attempt_one_source",
        "provider_usage_attempts",
        "num_nonnulls(planning_job_id, summary_job_id, semantic_index_job_id, knowledge_index_job_id) = 1",
    )
    op.drop_constraint(
        "provider_usage_operation", "provider_usage_attempts", type_="check"
    )
    op.create_check_constraint(
        "provider_usage_operation",
        "provider_usage_attempts",
        "operation IN ('response_planning','summary_generation','semantic_query','semantic_index','semantic_rebuild','media_transcription','knowledge_query','knowledge_index','knowledge_rebuild')",
    )

    op.execute("""
    CREATE FUNCTION spec033_reject_knowledge_owner_change() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF OLD.tenant_id <> NEW.tenant_id OR OLD.assistant_id <> NEW.assistant_id THEN
        RAISE EXCEPTION 'knowledge ownership is immutable';
      END IF;
      IF (to_jsonb(OLD) ? 'knowledge_base_id'
          AND to_jsonb(OLD)->>'knowledge_base_id'
              IS DISTINCT FROM to_jsonb(NEW)->>'knowledge_base_id')
         OR (to_jsonb(OLD) ? 'document_id'
          AND to_jsonb(OLD)->>'document_id'
              IS DISTINCT FROM to_jsonb(NEW)->>'document_id')
         OR (to_jsonb(OLD) ? 'revision_id'
          AND to_jsonb(OLD)->>'revision_id'
              IS DISTINCT FROM to_jsonb(NEW)->>'revision_id')
         OR (to_jsonb(OLD) ? 'chunk_id'
          AND to_jsonb(OLD)->>'chunk_id'
              IS DISTINCT FROM to_jsonb(NEW)->>'chunk_id') THEN
        RAISE EXCEPTION 'knowledge ownership is immutable';
      END IF;
      RETURN NEW;
    END $$
    """)
    op.execute(
        "CREATE TRIGGER trg_knowledge_bases_owner_immutable BEFORE UPDATE ON knowledge_bases FOR EACH ROW EXECUTE FUNCTION spec033_reject_knowledge_owner_change()"
    )
    op.execute(
        "CREATE TRIGGER trg_knowledge_documents_owner_immutable BEFORE UPDATE ON knowledge_documents FOR EACH ROW EXECUTE FUNCTION spec033_reject_knowledge_owner_change()"
    )
    op.execute(
        "CREATE TRIGGER trg_knowledge_revisions_owner_immutable BEFORE UPDATE ON knowledge_document_revisions FOR EACH ROW EXECUTE FUNCTION spec033_reject_knowledge_owner_change()"
    )
    op.execute(
        "CREATE TRIGGER trg_knowledge_chunks_owner_immutable BEFORE UPDATE ON knowledge_chunks FOR EACH ROW EXECUTE FUNCTION spec033_reject_knowledge_owner_change()"
    )
    op.execute(
        "CREATE TRIGGER trg_knowledge_jobs_owner_immutable BEFORE UPDATE ON knowledge_index_jobs FOR EACH ROW EXECUTE FUNCTION spec033_reject_knowledge_owner_change()"
    )


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM knowledge_bases)
         OR EXISTS (SELECT 1 FROM knowledge_documents)
         OR EXISTS (SELECT 1 FROM knowledge_document_revisions)
         OR EXISTS (SELECT 1 FROM knowledge_chunks)
         OR EXISTS (SELECT 1 FROM knowledge_index_jobs)
         OR EXISTS (SELECT 1 FROM knowledge_index_collections)
         OR EXISTS (SELECT 1 FROM assistants WHERE knowledge_enabled)
         OR EXISTS (SELECT 1 FROM response_planning_jobs WHERE knowledge_provenance::jsonb <> '[]'::jsonb)
         OR EXISTS (SELECT 1 FROM provider_work_policy_snapshots WHERE knowledge_index_job_id IS NOT NULL)
         OR EXISTS (SELECT 1 FROM provider_usage_attempts WHERE knowledge_index_job_id IS NOT NULL)
      THEN RAISE EXCEPTION 'SPEC-033 knowledge state blocks downgrade'; END IF;
    END $$;
    """)
    op.execute(
        "DROP TRIGGER trg_knowledge_jobs_owner_immutable ON knowledge_index_jobs"
    )
    op.execute("DROP TRIGGER trg_knowledge_chunks_owner_immutable ON knowledge_chunks")
    op.execute(
        "DROP TRIGGER trg_knowledge_revisions_owner_immutable ON knowledge_document_revisions"
    )
    op.execute(
        "DROP TRIGGER trg_knowledge_documents_owner_immutable ON knowledge_documents"
    )
    op.execute("DROP TRIGGER trg_knowledge_bases_owner_immutable ON knowledge_bases")
    op.execute("DROP FUNCTION spec033_reject_knowledge_owner_change()")
    op.drop_constraint(
        "provider_usage_operation", "provider_usage_attempts", type_="check"
    )
    op.create_check_constraint(
        "provider_usage_operation",
        "provider_usage_attempts",
        "operation IN ('response_planning','summary_generation','semantic_query','semantic_index','semantic_rebuild','media_transcription')",
    )
    op.drop_constraint(
        "provider_usage_attempt_one_source",
        "provider_usage_attempts",
        type_="check",
    )
    op.drop_constraint(
        "provider_work_snapshot_one_source",
        "provider_work_policy_snapshots",
        type_="check",
    )
    op.drop_constraint(
        "fk_provider_usage_knowledge_job", "provider_usage_attempts", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_provider_snapshot_knowledge_job",
        "provider_work_policy_snapshots",
        type_="foreignkey",
    )
    op.drop_column("provider_usage_attempts", "knowledge_index_job_id")
    op.drop_column("provider_work_policy_snapshots", "knowledge_index_job_id")
    op.create_check_constraint(
        "provider_usage_attempt_one_source",
        "provider_usage_attempts",
        "num_nonnulls(planning_job_id, summary_job_id, semantic_index_job_id) = 1",
    )
    op.create_check_constraint(
        "provider_work_snapshot_one_source",
        "provider_work_policy_snapshots",
        "num_nonnulls(planning_job_id, summary_job_id, semantic_index_job_id) = 1",
    )
    op.drop_table("knowledge_index_jobs")
    op.drop_table("knowledge_index_collections")
    op.drop_table("knowledge_chunks")
    op.drop_constraint(
        "fk_knowledge_documents_current_revision",
        "knowledge_documents",
        type_="foreignkey",
    )
    op.drop_table("knowledge_document_revisions")
    op.drop_table("knowledge_documents")
    op.drop_table("knowledge_bases")
    op.drop_constraint(
        "response_planning_knowledge_provenance_shape",
        "response_planning_jobs",
        type_="check",
    )
    op.execute("DROP FUNCTION spec033_valid_knowledge_provenance(jsonb)")
    op.drop_column("response_planning_jobs", "knowledge_provenance")
    op.drop_column("assistants", "knowledge_enabled")
