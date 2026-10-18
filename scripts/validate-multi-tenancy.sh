#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$root/scripts/lib/resolve-uv.sh"
uv_bin="$(resolve_uv "$root")"

repository_only=false
if [ "${1:-}" = "--repository-only" ]; then
  repository_only=true
elif [ "$#" -ne 0 ]; then
  printf 'usage: %s [--repository-only]\n' "$0" >&2
  exit 2
fi

env -u JANUARY_ENVIRONMENT "$uv_bin" run pytest \
  backend/tests/test_conversation_eligibility.py \
  backend/tests/test_config.py \
  backend/tests/test_provider_governance.py \
  backend/tests/test_proactive_scheduler_worker.py \
  backend/tests/test_telegram_connection_operations.py -q

env -u JANUARY_ENVIRONMENT PYTHONPATH=backend "$uv_bin" run python - "$root" <<'PY'
import ast
from pathlib import Path
import sys

from app.infrastructure.telemetry import PROHIBITED_LABEL_NAMES

root = Path(sys.argv[1])
targets = (
    root / "backend/app/infrastructure/database/tenancy.py",
    root / "backend/app/infrastructure/database/provider_governance.py",
    root / "backend/app/interface/http/control_plane.py",
    root / "backend/app/runtime/response_planning_worker.py",
    root / "backend/app/runtime/outbound_delivery_worker.py",
    root / "backend/app/runtime/telegram_command_worker.py",
    root / "backend/app/runtime/telegram_poller.py",
)
for target in targets:
    tree = ast.parse(target.read_text(), filename=str(target))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in {"increment", "observe", "set_gauge"}:
            continue
        if any(keyword.arg is None for keyword in node.keywords):
            raise SystemExit(f"dynamic metric labels are not allowed: {target}")
        unsafe = PROHIBITED_LABEL_NAMES.intersection(
            keyword.arg for keyword in node.keywords if keyword.arg is not None
        )
        if unsafe:
            raise SystemExit(f"prohibited metric labels in {target}: {sorted(unsafe)}")
PY

if rg -n 'pytest\.skip|pytest\.xfail|status_code in \{|asyncio\.sleep|time\.sleep' \
  backend/tests/integration/test_multi_tenant_model.py; then
  printf '%s\n' "SPEC-030 proof contains a prohibited skip, broad assertion, or fake race." >&2
  exit 1
fi

if "$repository_only"; then
  printf '%s\n' \
    "Repository SPEC-030 proof passed; PostgreSQL migration/concurrency proof PENDING (exit 2)." >&2
  exit 2
fi

export COMPOSE_PROJECT_NAME="${JANUARY_SPEC030_COMPOSE_PROJECT_NAME:-january-spec030-validation}"
export JANUARY_DB_HOST_PORT="${JANUARY_DB_HOST_PORT:-5444}"
export JANUARY_REDIS_HOST_PORT="${JANUARY_REDIS_HOST_PORT:-6391}"
export JANUARY_ENVIRONMENT=test
export JANUARY_DATABASE_HOST=127.0.0.1
export JANUARY_DATABASE_PORT="$JANUARY_DB_HOST_PORT"
export JANUARY_REDIS_URL="redis://127.0.0.1:${JANUARY_REDIS_HOST_PORT}/0"

if ! docker compose version >/dev/null 2>&1; then
  printf '%s\n' "Docker Compose is required for SPEC-030 integration proof." >&2
  exit 1
fi

guard_log=""
conflict_log=""
cleanup() {
  result=$?
  trap - EXIT
  for path in "$guard_log" "$conflict_log"; do
    if [ -n "$path" ] && [ -f "$path" ]; then
      rm -f "$path"
    fi
  done
  if ! docker compose down -v --remove-orphans; then
    printf '%s\n' "SPEC-030 temporary project cleanup failed." >&2
    result=1
  fi
  exit "$result"
}
trap cleanup EXIT

start_fresh() {
  docker compose down -v --remove-orphans
  docker compose up --detach --wait database redis
}

start_fresh
"$uv_bin" run alembic upgrade 0020_proactive_scheduling

docker compose exec -T database psql -v ON_ERROR_STOP=1 -U january -d january <<'SQL'
INSERT INTO control_tenants (id, slug, name)
VALUES
 ('10000000-0000-4000-8000-000000000001', 'legacy-a', 'Legacy A'),
 ('10000000-0000-4000-8000-000000000002', 'legacy-b', 'Legacy B');
INSERT INTO control_operator_identities (id, issuer, subject)
VALUES ('11000000-0000-4000-8000-000000000001', 'spec030', 'migration');
INSERT INTO assistants (id, name, status)
VALUES
 ('20000000-0000-4000-8000-000000000001', 'Same display', 'active'),
 ('20000000-0000-4000-8000-000000000002', 'Same display', 'active');
INSERT INTO platform_connections
  (id, assistant_id, platform, external_bot_id, status)
VALUES
 ('30000000-0000-4000-8000-000000000001',
  '20000000-0000-4000-8000-000000000001', 'telegram', 'legacy-bot-a', 'active'),
 ('30000000-0000-4000-8000-000000000002',
  '20000000-0000-4000-8000-000000000002', 'telegram', 'legacy-bot-b', 'active');
INSERT INTO control_assistant_bindings (id, tenant_id, assistant_id)
VALUES
 ('40000000-0000-4000-8000-000000000001',
  '10000000-0000-4000-8000-000000000001',
  '20000000-0000-4000-8000-000000000001'),
 ('40000000-0000-4000-8000-000000000002',
  '10000000-0000-4000-8000-000000000002',
  '20000000-0000-4000-8000-000000000002');
INSERT INTO control_connection_bindings (id, tenant_id, connection_id)
VALUES
 ('41000000-0000-4000-8000-000000000001',
  '10000000-0000-4000-8000-000000000001',
  '30000000-0000-4000-8000-000000000001'),
 ('41000000-0000-4000-8000-000000000002',
  '10000000-0000-4000-8000-000000000002',
  '30000000-0000-4000-8000-000000000002');
INSERT INTO conversations
  (id, platform_connection_id, platform_conversation_id, conversation_type,
   status, response_mode)
VALUES
 ('50000000-0000-4000-8000-000000000001',
  '30000000-0000-4000-8000-000000000001', 'legacy-private-a', 'private',
  'active', 'mention_only'),
 ('50000000-0000-4000-8000-000000000002',
  '30000000-0000-4000-8000-000000000002', 'legacy-private-b', 'private',
  'active', 'mention_only');
INSERT INTO participants
  (id, conversation_id, platform_user_id, display_name, role,
   mention_allowed, teasing_allowed)
VALUES
 ('60000000-0000-4000-8000-000000000001',
  '50000000-0000-4000-8000-000000000001', 'same-user', 'Same user',
  'member', true, false),
 ('60000000-0000-4000-8000-000000000002',
  '50000000-0000-4000-8000-000000000002', 'same-user', 'Same user',
  'member', true, false);
INSERT INTO messages
  (id, conversation_id, participant_id, platform_message_id, direction,
   message_type, text, processing_status)
VALUES ('70000000-0000-4000-8000-000000000001',
  '50000000-0000-4000-8000-000000000001',
  '60000000-0000-4000-8000-000000000001', 'legacy-message', 'incoming',
  'text', 'legacy fixture', 'processed');
INSERT INTO incoming_platform_updates
  (id, platform_connection_id, platform, platform_update_id, update_type,
   ingress_source, raw_payload, status, received_at)
VALUES ('71000000-0000-4000-8000-000000000001',
  '30000000-0000-4000-8000-000000000001', 'telegram', 'legacy-update',
  'message', 'webhook', '{}', 'received', now());
INSERT INTO conversation_processing_records
  (id, incoming_update_id, outcome, conversation_id, message_id)
VALUES ('72000000-0000-4000-8000-000000000001',
  '71000000-0000-4000-8000-000000000001', 'message_created',
  '50000000-0000-4000-8000-000000000001',
  '70000000-0000-4000-8000-000000000001');
INSERT INTO telegram_command_jobs
  (id, conversation_processing_record_id, conversation_id, message_id,
   participant_id, command_name, arguments)
VALUES ('73000000-0000-4000-8000-000000000001',
  '72000000-0000-4000-8000-000000000001',
  '50000000-0000-4000-8000-000000000001',
  '70000000-0000-4000-8000-000000000001',
  '60000000-0000-4000-8000-000000000001', 'memory', 'fixture');
INSERT INTO response_planning_jobs
  (id, conversation_processing_record_id, conversation_id, message_id,
   prompt_version, response_schema_version)
VALUES ('74000000-0000-4000-8000-000000000001',
  '72000000-0000-4000-8000-000000000001',
  '50000000-0000-4000-8000-000000000001',
  '70000000-0000-4000-8000-000000000001', 'legacy', 'response-plan-v2');
INSERT INTO memory_items
  (id, public_id, assistant_id, platform_connection_id, conversation_id,
   creator_participant_id, kind, scope, visibility, content,
   normalized_content_hash, confidence, source_message_id,
   source_command_job_id)
VALUES ('75000000-0000-4000-8000-000000000001', 'LEGACYMEMORY000000000001',
  '20000000-0000-4000-8000-000000000001',
  '30000000-0000-4000-8000-000000000001',
  '50000000-0000-4000-8000-000000000001',
  '60000000-0000-4000-8000-000000000001', 'explicit_fact',
  'private_conversation', 'same_conversation', 'legacy memory', repeat('a', 64),
  1.0, '70000000-0000-4000-8000-000000000001',
  '73000000-0000-4000-8000-000000000001');
INSERT INTO proactive_schedules
  (id, public_id, conversation_id, creator_participant_id,
   source_command_job_id, kind, recurrence, timezone_name, local_time_minute,
   weekday_mask, starts_on, one_time_at, next_run_at, ends_at, reminder_text)
VALUES ('76000000-0000-4000-8000-000000000001', 'SCHD00000001',
  '50000000-0000-4000-8000-000000000001',
  '60000000-0000-4000-8000-000000000001',
  '73000000-0000-4000-8000-000000000001', 'reminder', 'once', 'UTC', 720, 0,
  current_date, now() + interval '1 hour', now() + interval '1 hour',
  now() + interval '1 day', 'legacy reminder');
INSERT INTO provider_routing_policy_revisions
  (id, scope_type, scope_key, tenant_id, assistant_id, workload_class,
   schema_version, version, requirements, effective_at, created_by_identity_id)
VALUES ('77000000-0000-4000-8000-000000000001', 'assistant',
  'assistant:20000000-0000-4000-8000-000000000001',
  '10000000-0000-4000-8000-000000000001',
  '20000000-0000-4000-8000-000000000001', 'chat_generation',
  'provider-routing-v1', 1, '{}', now(),
  '11000000-0000-4000-8000-000000000001');
INSERT INTO provider_work_policy_snapshots
  (id, source_key, planning_job_id, workload_class, policy_revision_id,
   tenant_id, assistant_id, connection_id)
VALUES ('78000000-0000-4000-8000-000000000001', 'legacy-source',
  '74000000-0000-4000-8000-000000000001', 'chat_generation',
  '77000000-0000-4000-8000-000000000001',
  '10000000-0000-4000-8000-000000000001',
  '20000000-0000-4000-8000-000000000001',
  '30000000-0000-4000-8000-000000000001');
INSERT INTO provider_usage_attempts
  (id, attempt_key, source_key, record_origin, planning_job_id, workload_class,
   operation, attempt_ordinal, route_role, provider_id, model, tenant_id,
   assistant_id, connection_id, state, provider_outcome, request_count,
   usage_quality, estimate_quality)
VALUES ('79000000-0000-4000-8000-000000000001', 'legacy-attempt',
  'legacy-source', 'legacy_backfill',
  '74000000-0000-4000-8000-000000000001', 'chat_generation',
  'response_planning', 1, 'primary', 'openai', 'legacy-model',
  '10000000-0000-4000-8000-000000000001',
  '20000000-0000-4000-8000-000000000001',
  '30000000-0000-4000-8000-000000000001', 'no_io',
  'governance_unavailable', 0, 'missing', 'unavailable');
SQL

"$uv_bin" run alembic upgrade 0021_multi_assistant_tenancy
docker compose exec -T database psql -At -v ON_ERROR_STOP=1 -U january -d january \
  -c "SELECT string_agg(a.tenant_id::text || ':' || pc.tenant_id::text, ',' ORDER BY a.id) FROM assistants a JOIN platform_connections pc ON pc.assistant_id=a.id" \
  | grep -q '10000000-0000-4000-8000-000000000001:10000000-0000-4000-8000-000000000001,10000000-0000-4000-8000-000000000002:10000000-0000-4000-8000-000000000002'
docker compose exec -T database psql -At -v ON_ERROR_STOP=1 -U january -d january \
  -c "SELECT (SELECT count(*) FROM memory_items),(SELECT count(*) FROM proactive_schedules),(SELECT count(*) FROM provider_work_policy_snapshots WHERE tenant_id='10000000-0000-4000-8000-000000000001'),(SELECT count(*) FROM provider_usage_attempts WHERE connection_id='30000000-0000-4000-8000-000000000001')" \
  | grep -q '1|1|1|1'

guard_log="$(mktemp "${TMPDIR:-/tmp}/spec030-downgrade-guard.XXXXXX")"
if "$uv_bin" run alembic downgrade 0020_proactive_scheduling >"$guard_log" 2>&1; then
  printf '%s\n' "populated SPEC-030 downgrade unexpectedly succeeded" >&2
  exit 1
fi
grep -q 'SPEC-030 tenancy state blocks downgrade' "$guard_log"
rm -f "$guard_log"
guard_log=""
"$uv_bin" run alembic current | grep -q '0021_multi_assistant_tenancy'

start_fresh
"$uv_bin" run alembic upgrade 0020_proactive_scheduling
docker compose exec -T database psql -v ON_ERROR_STOP=1 -U january -d january <<'SQL'
INSERT INTO control_tenants (id, slug, name) VALUES
 ('10000000-0000-4000-8000-000000000001', 'conflict-a', 'Conflict A'),
 ('10000000-0000-4000-8000-000000000002', 'conflict-b', 'Conflict B');
INSERT INTO assistants (id, name, status) VALUES
 ('20000000-0000-4000-8000-000000000001', 'Conflict', 'active');
INSERT INTO platform_connections
 (id, assistant_id, platform, external_bot_id, status) VALUES
 ('30000000-0000-4000-8000-000000000001',
  '20000000-0000-4000-8000-000000000001', 'telegram', 'conflict-bot', 'active');
INSERT INTO control_assistant_bindings (id, tenant_id, assistant_id) VALUES
 ('40000000-0000-4000-8000-000000000001',
  '10000000-0000-4000-8000-000000000001',
  '20000000-0000-4000-8000-000000000001');
INSERT INTO control_connection_bindings (id, tenant_id, connection_id) VALUES
 ('41000000-0000-4000-8000-000000000001',
  '10000000-0000-4000-8000-000000000002',
  '30000000-0000-4000-8000-000000000001');
SQL
conflict_log="$(mktemp "${TMPDIR:-/tmp}/spec030-migration-conflict.XXXXXX")"
if "$uv_bin" run alembic upgrade 0021_multi_assistant_tenancy >"$conflict_log" 2>&1; then
  printf '%s\n' "contradictory legacy ownership unexpectedly migrated" >&2
  exit 1
fi
grep -q 'contradictory tenant ownership blocks SPEC-030' "$conflict_log"
rm -f "$conflict_log"
conflict_log=""
"$uv_bin" run alembic current | grep -q '0020_proactive_scheduling'

start_fresh
"$uv_bin" run alembic upgrade head
"$uv_bin" run pytest -m multi_tenant_integration -q
"$uv_bin" run pytest \
  backend/tests/integration/test_ingress.py \
  backend/tests/integration/test_outbound_delivery.py \
  backend/tests/integration/test_provider_governance_schema.py \
  -m 'ingress_integration or delivery_integration or provider_governance_integration' -q

PYTHONPATH=backend "$uv_bin" run python - <<'PY'
import asyncio
from sqlalchemy import text
from app.core.config import Settings
from app.infrastructure.database.database import Database

async def main() -> None:
    database = Database(Settings(_env_file=None, environment="test"))
    await database.start()
    try:
        async with database.engine.begin() as connection:
            await connection.execute(text("TRUNCATE control_tenants CASCADE"))
    finally:
        await database.stop()

asyncio.run(main())
PY
"$uv_bin" run alembic downgrade 0020_proactive_scheduling
"$uv_bin" run alembic upgrade 0021_multi_assistant_tenancy
"$uv_bin" run alembic downgrade base
"$uv_bin" run alembic upgrade head
"$uv_bin" run alembic current | grep -q '0026_conversation_feedback'

printf '%s\n' "SPEC-030 multi-assistant multi-tenant validation: passed"
