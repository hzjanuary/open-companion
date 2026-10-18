"""Canonicalize tenant and Assistant ownership for SPEC-030.

Revision ID: 0021_multi_assistant_tenancy
Revises: 0020_proactive_scheduling
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_multi_assistant_tenancy"
down_revision: str | None = "0020_proactive_scheduling"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_TENANT_ID = "00000000-0000-4000-8000-000000000030"
LEGACY_TENANT_SLUG = "legacy-default"


def upgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM control_tenants
            WHERE slug = '{LEGACY_TENANT_SLUG}'
              AND id <> '{LEGACY_TENANT_ID}'::uuid
          ) OR EXISTS (
            SELECT 1 FROM control_tenants
            WHERE id = '{LEGACY_TENANT_ID}'::uuid
              AND slug <> '{LEGACY_TENANT_SLUG}'
          ) THEN
            RAISE EXCEPTION 'reserved SPEC-030 legacy tenant identity conflicts';
          END IF;

          IF EXISTS (
            SELECT 1
            FROM memory_items m
            JOIN conversations c ON c.id = m.conversation_id
            JOIN platform_connections pc ON pc.id = c.platform_connection_id
            WHERE m.platform_connection_id <> c.platform_connection_id
               OR m.assistant_id <> pc.assistant_id
          ) THEN
            RAISE EXCEPTION 'contradictory memory ownership blocks SPEC-030';
          END IF;

          IF EXISTS (
            SELECT 1
            FROM memory_recall_policies r
            JOIN conversations c ON c.id = r.conversation_id
            JOIN platform_connections pc ON pc.id = c.platform_connection_id
            WHERE r.platform_connection_id <> c.platform_connection_id
               OR r.assistant_id <> pc.assistant_id
          ) THEN
            RAISE EXCEPTION 'contradictory recall ownership blocks SPEC-030';
          END IF;

          IF EXISTS (
            SELECT 1 FROM provider_work_policy_snapshots s
            JOIN platform_connections pc ON pc.id = s.connection_id
            WHERE (s.assistant_id IS NOT NULL
                   AND s.assistant_id <> pc.assistant_id)
          ) OR EXISTS (
            SELECT 1 FROM provider_usage_attempts u
            JOIN platform_connections pc ON pc.id = u.connection_id
            WHERE (u.assistant_id IS NOT NULL
                   AND u.assistant_id <> pc.assistant_id)
          ) OR EXISTS (
            SELECT 1 FROM provider_work_policy_snapshots s
            JOIN response_planning_jobs j ON j.id = s.planning_job_id
            JOIN conversations c ON c.id = j.conversation_id
            JOIN platform_connections pc ON pc.id = c.platform_connection_id
            WHERE (s.assistant_id IS NOT NULL
                   AND s.assistant_id <> pc.assistant_id)
               OR (s.connection_id IS NOT NULL
                   AND s.connection_id <> pc.id)
          ) OR EXISTS (
            SELECT 1 FROM provider_work_policy_snapshots s
            JOIN conversation_summary_jobs j ON j.id = s.summary_job_id
            JOIN conversations c ON c.id = j.conversation_id
            JOIN platform_connections pc ON pc.id = c.platform_connection_id
            WHERE (s.assistant_id IS NOT NULL
                   AND s.assistant_id <> pc.assistant_id)
               OR (s.connection_id IS NOT NULL
                   AND s.connection_id <> pc.id)
          ) OR EXISTS (
            SELECT 1 FROM provider_work_policy_snapshots s
            JOIN explicit_memory_semantic_index_jobs j
              ON j.id = s.semantic_index_job_id
            JOIN memory_items m ON m.id = j.memory_id
            JOIN platform_connections pc ON pc.id = m.platform_connection_id
            WHERE (s.assistant_id IS NOT NULL
                   AND s.assistant_id <> pc.assistant_id)
               OR (s.connection_id IS NOT NULL
                   AND s.connection_id <> pc.id)
          ) OR EXISTS (
            SELECT 1 FROM provider_usage_attempts u
            JOIN response_planning_jobs j ON j.id = u.planning_job_id
            JOIN conversations c ON c.id = j.conversation_id
            JOIN platform_connections pc ON pc.id = c.platform_connection_id
            WHERE (u.assistant_id IS NOT NULL
                   AND u.assistant_id <> pc.assistant_id)
               OR (u.connection_id IS NOT NULL
                   AND u.connection_id <> pc.id)
          ) OR EXISTS (
            SELECT 1 FROM provider_usage_attempts u
            JOIN conversation_summary_jobs j ON j.id = u.summary_job_id
            JOIN conversations c ON c.id = j.conversation_id
            JOIN platform_connections pc ON pc.id = c.platform_connection_id
            WHERE (u.assistant_id IS NOT NULL
                   AND u.assistant_id <> pc.assistant_id)
               OR (u.connection_id IS NOT NULL
                   AND u.connection_id <> pc.id)
          ) OR EXISTS (
            SELECT 1 FROM provider_usage_attempts u
            JOIN explicit_memory_semantic_index_jobs j
              ON j.id = u.semantic_index_job_id
            JOIN memory_items m ON m.id = j.memory_id
            JOIN platform_connections pc ON pc.id = m.platform_connection_id
            WHERE (u.assistant_id IS NOT NULL
                   AND u.assistant_id <> pc.assistant_id)
               OR (u.connection_id IS NOT NULL
                   AND u.connection_id <> pc.id)
          ) THEN
            RAISE EXCEPTION 'contradictory provider work ownership blocks SPEC-030';
          END IF;
        END $$
        """
    )
    op.execute(
        """
        CREATE TEMPORARY TABLE spec030_owner_candidates (
          assistant_id uuid NOT NULL,
          tenant_id uuid NOT NULL
        )
        """
    )
    op.execute(
        """
        INSERT INTO spec030_owner_candidates
        SELECT assistant_id, tenant_id FROM control_assistant_bindings
        UNION ALL
        SELECT pc.assistant_id, b.tenant_id
          FROM control_connection_bindings b
          JOIN platform_connections pc ON pc.id = b.connection_id
        UNION ALL
        SELECT pc.assistant_id, g.tenant_id
          FROM control_group_bindings g
          JOIN platform_connections pc ON pc.id = g.connection_id
        UNION ALL
        SELECT assistant_id, tenant_id
          FROM provider_routing_policy_revisions
         WHERE assistant_id IS NOT NULL
        UNION ALL
        SELECT pc.assistant_id, r.tenant_id
          FROM provider_routing_policy_revisions r
          JOIN platform_connections pc ON pc.id = r.connection_id
         WHERE r.connection_id IS NOT NULL
        UNION ALL
        SELECT assistant_id, tenant_id
          FROM provider_budgets
         WHERE assistant_id IS NOT NULL
        UNION ALL
        SELECT pc.assistant_id, b.tenant_id
          FROM provider_budgets b
          JOIN platform_connections pc ON pc.id = b.connection_id
         WHERE b.connection_id IS NOT NULL
        UNION ALL
        SELECT assistant_id, tenant_id
          FROM provider_work_policy_snapshots
         WHERE assistant_id IS NOT NULL AND tenant_id IS NOT NULL
        UNION ALL
        SELECT pc.assistant_id, s.tenant_id
          FROM provider_work_policy_snapshots s
          JOIN platform_connections pc ON pc.id = s.connection_id
         WHERE s.tenant_id IS NOT NULL
        UNION ALL
        SELECT pc.assistant_id, s.tenant_id
          FROM provider_work_policy_snapshots s
          JOIN response_planning_jobs j ON j.id = s.planning_job_id
          JOIN conversations c ON c.id = j.conversation_id
          JOIN platform_connections pc ON pc.id = c.platform_connection_id
         WHERE s.tenant_id IS NOT NULL
        UNION ALL
        SELECT pc.assistant_id, s.tenant_id
          FROM provider_work_policy_snapshots s
          JOIN conversation_summary_jobs j ON j.id = s.summary_job_id
          JOIN conversations c ON c.id = j.conversation_id
          JOIN platform_connections pc ON pc.id = c.platform_connection_id
         WHERE s.tenant_id IS NOT NULL
        UNION ALL
        SELECT pc.assistant_id, s.tenant_id
          FROM provider_work_policy_snapshots s
          JOIN explicit_memory_semantic_index_jobs j
            ON j.id = s.semantic_index_job_id
          JOIN memory_items m ON m.id = j.memory_id
          JOIN platform_connections pc ON pc.id = m.platform_connection_id
         WHERE s.tenant_id IS NOT NULL
        UNION ALL
        SELECT assistant_id, tenant_id
          FROM provider_usage_attempts
         WHERE assistant_id IS NOT NULL AND tenant_id IS NOT NULL
        UNION ALL
        SELECT pc.assistant_id, u.tenant_id
          FROM provider_usage_attempts u
          JOIN platform_connections pc ON pc.id = u.connection_id
         WHERE u.tenant_id IS NOT NULL
        UNION ALL
        SELECT pc.assistant_id, u.tenant_id
          FROM provider_usage_attempts u
          JOIN response_planning_jobs j ON j.id = u.planning_job_id
          JOIN conversations c ON c.id = j.conversation_id
          JOIN platform_connections pc ON pc.id = c.platform_connection_id
         WHERE u.tenant_id IS NOT NULL
        UNION ALL
        SELECT pc.assistant_id, u.tenant_id
          FROM provider_usage_attempts u
          JOIN conversation_summary_jobs j ON j.id = u.summary_job_id
          JOIN conversations c ON c.id = j.conversation_id
          JOIN platform_connections pc ON pc.id = c.platform_connection_id
         WHERE u.tenant_id IS NOT NULL
        UNION ALL
        SELECT pc.assistant_id, u.tenant_id
          FROM provider_usage_attempts u
          JOIN explicit_memory_semantic_index_jobs j
            ON j.id = u.semantic_index_job_id
          JOIN memory_items m ON m.id = j.memory_id
          JOIN platform_connections pc ON pc.id = m.platform_connection_id
         WHERE u.tenant_id IS NOT NULL
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT assistant_id
              FROM spec030_owner_candidates
             GROUP BY assistant_id
            HAVING count(DISTINCT tenant_id) > 1
          ) THEN
            RAISE EXCEPTION 'contradictory tenant ownership blocks SPEC-030';
          END IF;

          IF EXISTS (
            SELECT 1 FROM provider_routing_policy_revisions
             WHERE (scope_type = 'assistant'
                    AND scope_key <> 'assistant:' || assistant_id::text)
                OR (scope_type = 'platform_connection'
                    AND scope_key <> 'platform_connection:' || connection_id::text)
          ) OR EXISTS (
            SELECT 1 FROM provider_budgets
             WHERE (scope_type = 'assistant'
                    AND scope_key <> 'assistant:' || assistant_id::text)
                OR (scope_type = 'platform_connection'
                    AND scope_key <> 'platform_connection:' || connection_id::text)
          ) THEN
            RAISE EXCEPTION 'contradictory provider scope key blocks SPEC-030';
          END IF;
        END $$
        """
    )

    op.add_column(
        "control_tenants",
        sa.Column("revision", sa.Integer(), nullable=True, server_default="1"),
    )
    op.add_column("assistants", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.add_column("assistants", sa.Column("slug", sa.String(80), nullable=True))
    op.add_column(
        "assistants",
        sa.Column("revision", sa.Integer(), nullable=True, server_default="1"),
    )
    op.add_column(
        "platform_connections", sa.Column("tenant_id", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "platform_connections",
        sa.Column("revision", sa.Integer(), nullable=True, server_default="1"),
    )

    op.execute(
        f"""
        INSERT INTO control_tenants (id, slug, name, status, revision)
        SELECT '{LEGACY_TENANT_ID}'::uuid, '{LEGACY_TENANT_SLUG}',
               'Legacy deployment', 'active', 1
         WHERE NOT EXISTS (SELECT 1 FROM control_tenants)
            OR EXISTS (
                 SELECT 1 FROM assistants a
                  WHERE NOT EXISTS (
                    SELECT 1 FROM spec030_owner_candidates c
                     WHERE c.assistant_id = a.id
                  )
               )
        ON CONFLICT (id) DO NOTHING;
        """
    )
    op.execute(
        f"""
        UPDATE assistants a
           SET tenant_id = COALESCE(
                 (SELECT min(c.tenant_id::text)::uuid
                    FROM spec030_owner_candidates c
                   WHERE c.assistant_id = a.id),
                 '{LEGACY_TENANT_ID}'::uuid
               ),
               slug = 'assistant-' || replace(a.id::text, '-', ''),
               revision = 1;
        """
    )
    op.execute(
        """
        UPDATE platform_connections pc
           SET tenant_id = a.tenant_id,
               revision = 1
          FROM assistants a
         WHERE a.id = pc.assistant_id;
        """
    )
    op.execute(
        """
        INSERT INTO control_assistant_bindings
          (id, tenant_id, assistant_id, created_at, updated_at)
        SELECT gen_random_uuid(), a.tenant_id, a.id, now(), now()
          FROM assistants a
         WHERE NOT EXISTS (
           SELECT 1 FROM control_assistant_bindings b
            WHERE b.assistant_id = a.id
         );
        """
    )
    op.execute(
        """
        INSERT INTO control_connection_bindings
          (id, tenant_id, connection_id, created_at, updated_at)
        SELECT gen_random_uuid(), pc.tenant_id, pc.id, now(), now()
          FROM platform_connections pc
         WHERE NOT EXISTS (
           SELECT 1 FROM control_connection_bindings b
            WHERE b.connection_id = pc.id
         );
        """
    )
    op.execute(
        """
        WITH resolved AS (
          SELECT s.id, pc.tenant_id, pc.assistant_id, pc.id AS connection_id
            FROM provider_work_policy_snapshots s
            JOIN response_planning_jobs j ON j.id = s.planning_job_id
            JOIN conversations c ON c.id = j.conversation_id
            JOIN platform_connections pc ON pc.id = c.platform_connection_id
          UNION ALL
          SELECT s.id, pc.tenant_id, pc.assistant_id, pc.id
            FROM provider_work_policy_snapshots s
            JOIN conversation_summary_jobs j ON j.id = s.summary_job_id
            JOIN conversations c ON c.id = j.conversation_id
            JOIN platform_connections pc ON pc.id = c.platform_connection_id
          UNION ALL
          SELECT s.id, pc.tenant_id, pc.assistant_id, pc.id
            FROM provider_work_policy_snapshots s
            JOIN explicit_memory_semantic_index_jobs j
              ON j.id = s.semantic_index_job_id
            JOIN memory_items m ON m.id = j.memory_id
            JOIN platform_connections pc ON pc.id = m.platform_connection_id
        )
        UPDATE provider_work_policy_snapshots s
           SET tenant_id = r.tenant_id,
               assistant_id = r.assistant_id,
               connection_id = r.connection_id
          FROM resolved r
         WHERE r.id = s.id;
        """
    )
    op.execute(
        """
        WITH resolved AS (
          SELECT u.id, pc.tenant_id, pc.assistant_id, pc.id AS connection_id
            FROM provider_usage_attempts u
            JOIN response_planning_jobs j ON j.id = u.planning_job_id
            JOIN conversations c ON c.id = j.conversation_id
            JOIN platform_connections pc ON pc.id = c.platform_connection_id
          UNION ALL
          SELECT u.id, pc.tenant_id, pc.assistant_id, pc.id
            FROM provider_usage_attempts u
            JOIN conversation_summary_jobs j ON j.id = u.summary_job_id
            JOIN conversations c ON c.id = j.conversation_id
            JOIN platform_connections pc ON pc.id = c.platform_connection_id
          UNION ALL
          SELECT u.id, pc.tenant_id, pc.assistant_id, pc.id
            FROM provider_usage_attempts u
            JOIN explicit_memory_semantic_index_jobs j
              ON j.id = u.semantic_index_job_id
            JOIN memory_items m ON m.id = j.memory_id
            JOIN platform_connections pc ON pc.id = m.platform_connection_id
        )
        UPDATE provider_usage_attempts u
           SET tenant_id = r.tenant_id,
               assistant_id = r.assistant_id,
               connection_id = r.connection_id
          FROM resolved r
         WHERE r.id = u.id;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM assistants WHERE tenant_id IS NULL)
             OR EXISTS (SELECT 1 FROM platform_connections WHERE tenant_id IS NULL)
             OR EXISTS (
               SELECT 1 FROM control_assistant_bindings b
               JOIN assistants a ON a.id = b.assistant_id
               WHERE b.tenant_id <> a.tenant_id
             ) OR EXISTS (
               SELECT 1 FROM control_connection_bindings b
               JOIN platform_connections pc ON pc.id = b.connection_id
               WHERE b.tenant_id <> pc.tenant_id
             ) OR EXISTS (
               SELECT 1 FROM control_group_bindings g
               JOIN platform_connections pc ON pc.id = g.connection_id
               WHERE g.tenant_id <> pc.tenant_id
             ) THEN
            RAISE EXCEPTION 'SPEC-030 ownership backfill validation failed';
          END IF;
        END $$
        """
    )
    op.execute("DROP TABLE spec030_owner_candidates")

    op.alter_column("control_tenants", "revision", nullable=False, server_default=None)
    op.alter_column("assistants", "tenant_id", nullable=False)
    op.alter_column("assistants", "slug", nullable=False)
    op.alter_column("assistants", "revision", nullable=False, server_default=None)
    op.alter_column("platform_connections", "tenant_id", nullable=False)
    op.alter_column(
        "platform_connections", "revision", nullable=False, server_default=None
    )

    op.drop_constraint("assistant_status", "assistants", type_="check")
    op.create_check_constraint(
        "assistant_status", "assistants", "status IN ('active','disabled','retired')"
    )
    op.drop_constraint(
        "platform_connection_status", "platform_connections", type_="check"
    )
    op.create_check_constraint(
        "platform_connection_status",
        "platform_connections",
        "status IN ('active','disabled','error','retired')",
    )
    op.create_check_constraint(
        "tenant_status",
        "control_tenants",
        "status IN ('active','disabled','retired')",
    )
    op.create_check_constraint(
        "control_tenant_revision_positive", "control_tenants", "revision > 0"
    )
    op.create_check_constraint(
        "assistant_revision_positive", "assistants", "revision > 0"
    )
    op.create_check_constraint(
        "platform_connection_revision_positive",
        "platform_connections",
        "revision > 0",
    )

    op.create_foreign_key(
        "fk_assistants_tenant",
        "assistants",
        "control_tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_assistants_tenant_id", "assistants", ["tenant_id"])
    op.create_unique_constraint(
        "uq_assistants_tenant_slug", "assistants", ["tenant_id", "slug"]
    )
    op.create_unique_constraint(
        "uq_assistants_id_tenant", "assistants", ["id", "tenant_id"]
    )

    op.create_foreign_key(
        "fk_platform_connections_tenant",
        "platform_connections",
        "control_tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_platform_connections_tenant_id", "platform_connections", ["tenant_id"]
    )
    op.create_unique_constraint(
        "uq_platform_connections_id_tenant",
        "platform_connections",
        ["id", "tenant_id"],
    )
    op.create_unique_constraint(
        "uq_platform_connections_id_assistant",
        "platform_connections",
        ["id", "assistant_id"],
    )
    op.create_foreign_key(
        "fk_platform_connections_assistant_tenant",
        "platform_connections",
        "assistants",
        ["assistant_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_conversations_id_connection",
        "conversations",
        ["id", "platform_connection_id"],
    )

    for name, table, target, local, remote in (
        (
            "fk_control_assistant_binding_owner",
            "control_assistant_bindings",
            "assistants",
            ["assistant_id", "tenant_id"],
            ["id", "tenant_id"],
        ),
        (
            "fk_control_connection_binding_owner",
            "control_connection_bindings",
            "platform_connections",
            ["connection_id", "tenant_id"],
            ["id", "tenant_id"],
        ),
        (
            "fk_control_group_binding_owner",
            "control_group_bindings",
            "platform_connections",
            ["connection_id", "tenant_id"],
            ["id", "tenant_id"],
        ),
    ):
        op.create_foreign_key(name, table, target, local, remote, ondelete="RESTRICT")

    op.execute(
        """
        CREATE FUNCTION spec030_reject_authority_reassignment()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          IF TG_TABLE_NAME = 'assistants'
             AND NEW.tenant_id IS DISTINCT FROM OLD.tenant_id THEN
            RAISE EXCEPTION USING
              ERRCODE = '23514',
              MESSAGE = 'SPEC-030 assistant tenant reassignment is not supported';
          END IF;
          IF TG_TABLE_NAME = 'platform_connections'
             AND (NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
                  OR NEW.assistant_id IS DISTINCT FROM OLD.assistant_id) THEN
            RAISE EXCEPTION USING
              ERRCODE = '23514',
              MESSAGE = 'SPEC-030 connection authority reassignment is not supported';
          END IF;
          RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER spec030_assistant_tenant_immutable
        BEFORE UPDATE OF tenant_id ON assistants
        FOR EACH ROW EXECUTE FUNCTION spec030_reject_authority_reassignment()
        """
    )
    op.execute(
        """
        CREATE TRIGGER spec030_connection_authority_immutable
        BEFORE UPDATE OF tenant_id, assistant_id ON platform_connections
        FOR EACH ROW EXECUTE FUNCTION spec030_reject_authority_reassignment()
        """
    )

    for name, table, target, local, remote in (
        (
            "fk_memory_items_connection_assistant",
            "memory_items",
            "platform_connections",
            ["platform_connection_id", "assistant_id"],
            ["id", "assistant_id"],
        ),
        (
            "fk_memory_items_conversation_connection",
            "memory_items",
            "conversations",
            ["conversation_id", "platform_connection_id"],
            ["id", "platform_connection_id"],
        ),
        (
            "fk_memory_recall_connection_assistant",
            "memory_recall_policies",
            "platform_connections",
            ["platform_connection_id", "assistant_id"],
            ["id", "assistant_id"],
        ),
        (
            "fk_memory_recall_conversation_connection",
            "memory_recall_policies",
            "conversations",
            ["conversation_id", "platform_connection_id"],
            ["id", "platform_connection_id"],
        ),
        (
            "fk_provider_routing_assistant_owner",
            "provider_routing_policy_revisions",
            "assistants",
            ["assistant_id", "tenant_id"],
            ["id", "tenant_id"],
        ),
        (
            "fk_provider_routing_connection_owner",
            "provider_routing_policy_revisions",
            "platform_connections",
            ["connection_id", "tenant_id"],
            ["id", "tenant_id"],
        ),
        (
            "fk_provider_budget_assistant_owner",
            "provider_budgets",
            "assistants",
            ["assistant_id", "tenant_id"],
            ["id", "tenant_id"],
        ),
        (
            "fk_provider_budget_connection_owner",
            "provider_budgets",
            "platform_connections",
            ["connection_id", "tenant_id"],
            ["id", "tenant_id"],
        ),
        (
            "fk_provider_snapshot_assistant_owner",
            "provider_work_policy_snapshots",
            "assistants",
            ["assistant_id", "tenant_id"],
            ["id", "tenant_id"],
        ),
        (
            "fk_provider_snapshot_connection_owner",
            "provider_work_policy_snapshots",
            "platform_connections",
            ["connection_id", "tenant_id"],
            ["id", "tenant_id"],
        ),
        (
            "fk_provider_usage_assistant_owner",
            "provider_usage_attempts",
            "assistants",
            ["assistant_id", "tenant_id"],
            ["id", "tenant_id"],
        ),
        (
            "fk_provider_usage_connection_owner",
            "provider_usage_attempts",
            "platform_connections",
            ["connection_id", "tenant_id"],
            ["id", "tenant_id"],
        ),
    ):
        op.create_foreign_key(name, table, target, local, remote, ondelete="RESTRICT")


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
               SELECT 1 FROM control_tenants
                WHERE id <> '00000000-0000-4000-8000-000000000030'::uuid
             )
             OR EXISTS (SELECT 1 FROM assistants WHERE status = 'retired')
             OR EXISTS (SELECT 1 FROM platform_connections WHERE status = 'retired')
             OR EXISTS (SELECT 1 FROM control_tenants WHERE revision <> 1)
             OR EXISTS (SELECT 1 FROM assistants WHERE revision <> 1)
             OR EXISTS (SELECT 1 FROM platform_connections WHERE revision <> 1)
             OR EXISTS (
               SELECT 1 FROM assistants
                WHERE slug <> 'assistant-' || replace(id::text, '-', '')
             ) THEN
            RAISE EXCEPTION 'SPEC-030 tenancy state blocks downgrade';
          END IF;
        END $$;
        """
    )

    op.execute(
        "DROP TRIGGER spec030_connection_authority_immutable ON platform_connections"
    )
    op.execute("DROP TRIGGER spec030_assistant_tenant_immutable ON assistants")
    op.execute("DROP FUNCTION spec030_reject_authority_reassignment()")

    for name, table in (
        ("fk_provider_usage_connection_owner", "provider_usage_attempts"),
        ("fk_provider_usage_assistant_owner", "provider_usage_attempts"),
        ("fk_provider_snapshot_connection_owner", "provider_work_policy_snapshots"),
        ("fk_provider_snapshot_assistant_owner", "provider_work_policy_snapshots"),
        ("fk_provider_budget_connection_owner", "provider_budgets"),
        ("fk_provider_budget_assistant_owner", "provider_budgets"),
        ("fk_provider_routing_connection_owner", "provider_routing_policy_revisions"),
        ("fk_provider_routing_assistant_owner", "provider_routing_policy_revisions"),
        ("fk_memory_recall_conversation_connection", "memory_recall_policies"),
        ("fk_memory_recall_connection_assistant", "memory_recall_policies"),
        ("fk_memory_items_conversation_connection", "memory_items"),
        ("fk_memory_items_connection_assistant", "memory_items"),
        ("fk_control_group_binding_owner", "control_group_bindings"),
        ("fk_control_connection_binding_owner", "control_connection_bindings"),
        ("fk_control_assistant_binding_owner", "control_assistant_bindings"),
    ):
        op.drop_constraint(name, table, type_="foreignkey")

    op.drop_constraint(
        "fk_platform_connections_assistant_tenant",
        "platform_connections",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_conversations_id_connection", "conversations", type_="unique"
    )
    op.drop_constraint(
        "uq_platform_connections_id_assistant",
        "platform_connections",
        type_="unique",
    )
    op.drop_constraint(
        "uq_platform_connections_id_tenant", "platform_connections", type_="unique"
    )
    op.drop_index(
        "ix_platform_connections_tenant_id", table_name="platform_connections"
    )
    op.drop_constraint(
        "fk_platform_connections_tenant", "platform_connections", type_="foreignkey"
    )
    op.drop_constraint("uq_assistants_id_tenant", "assistants", type_="unique")
    op.drop_constraint("uq_assistants_tenant_slug", "assistants", type_="unique")
    op.drop_index("ix_assistants_tenant_id", table_name="assistants")
    op.drop_constraint("fk_assistants_tenant", "assistants", type_="foreignkey")

    op.drop_constraint(
        "platform_connection_revision_positive",
        "platform_connections",
        type_="check",
    )
    op.drop_constraint("assistant_revision_positive", "assistants", type_="check")
    op.drop_constraint(
        "control_tenant_revision_positive", "control_tenants", type_="check"
    )
    op.drop_constraint("tenant_status", "control_tenants", type_="check")
    op.drop_constraint(
        "platform_connection_status", "platform_connections", type_="check"
    )
    op.create_check_constraint(
        "platform_connection_status",
        "platform_connections",
        "status IN ('active','disabled','error')",
    )
    op.drop_constraint("assistant_status", "assistants", type_="check")
    op.create_check_constraint(
        "assistant_status", "assistants", "status IN ('active','disabled')"
    )

    op.drop_column("platform_connections", "revision")
    op.drop_column("platform_connections", "tenant_id")
    op.drop_column("assistants", "revision")
    op.drop_column("assistants", "slug")
    op.drop_column("assistants", "tenant_id")
    op.drop_column("control_tenants", "revision")
