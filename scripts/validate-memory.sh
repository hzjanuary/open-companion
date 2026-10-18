#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$project_root/scripts/lib/resolve-uv.sh"
source "$project_root/scripts/lib/db-ready.sh"
uv_bin="$(resolve_uv "$project_root")"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-january-memory-validation}"

export JANUARY_ENVIRONMENT=test JANUARY_DATABASE_HOST=127.0.0.1
export JANUARY_DATABASE_PORT="${JANUARY_DB_HOST_PORT:-5432}"
export JANUARY_REDIS_URL="redis://127.0.0.1:${JANUARY_REDIS_HOST_PORT:-6379}/0"

if ! docker compose version >/dev/null 2>&1; then
  printf '%s\n' "Docker Compose is required for memory/privacy integration validation." >&2
  exit 1
fi

cleanup() {
  status=$?
  trap - EXIT
  if ! docker compose stop database redis >/dev/null 2>&1; then
    printf '%s\n' "Memory validator cleanup failed." >&2
    status=1
  fi
  exit "$status"
}
trap cleanup EXIT
docker compose up --detach database redis
pg_ready && redis_ready || { printf '%s\n' "PostgreSQL or Redis did not become ready." >&2; exit 1; }
# This validator owns its migration lifecycle. Do not let fixtures from a
# preceding chained validator masquerade as a downgrade failure.
docker compose down -v --remove-orphans
docker compose up --detach --wait database redis
"$uv_bin" run alembic upgrade head
# SPEC-028 refuses a destructive 0019->0018 downgrade while media or
# transcription state exists. Never swallow that refusal: verify the guarded
# downgrade explicitly, remove SPEC-028 test-owned state when present, then
# prove a state-free reversal. Any other Alembic error fails the validator.
if downgrade_output=$("$uv_bin" run alembic downgrade 0018_user_controlled_memory 2>&1); then
  printf '%s\n' "SPEC-028 schema downgrade 0019->0018: valid (no guarded media/transcription state)"
else
  printf '%s\n' "$downgrade_output"
  printf '%s\n' "$downgrade_output" \
    | grep -q 'SPEC-028 media or transcription state blocks downgrade' \
    || {
      printf '%s\n' "Schema downgrade failed with an unexpected error; " \
        "expected only the SPEC-028 media/transcription downgrade guard." >&2
      exit 1
    }
  "$uv_bin" run alembic current | grep -q '0026_conversation_feedback'
  printf '%s\n' "SPEC-028 downgrade guard refusal verified; removing guarded state and retrying." >&2
  docker compose exec -T database psql -U january -d january -v ON_ERROR_STOP=1 <<'SQL'
DELETE FROM outbound_delivery_attempts
 WHERE outbound_action_id IN (
   SELECT outbound_actions.id FROM outbound_actions
   JOIN response_plans ON response_plans.id = outbound_actions.response_plan_id
   JOIN response_planning_jobs ON response_planning_jobs.id = response_plans.planning_job_id
   WHERE response_planning_jobs.message_id IN (
     SELECT id FROM messages WHERE message_type IN ('photo','voice','audio')));
UPDATE messages SET outbound_action_id = NULL
 WHERE outbound_action_id IN (
   SELECT outbound_actions.id FROM outbound_actions
   JOIN response_plans ON response_plans.id = outbound_actions.response_plan_id
   JOIN response_planning_jobs ON response_planning_jobs.id = response_plans.planning_job_id
   WHERE response_planning_jobs.message_id IN (
     SELECT id FROM messages WHERE message_type IN ('photo','voice','audio')));
DELETE FROM outbound_actions
 WHERE response_plan_id IN (
   SELECT response_plans.id FROM response_plans
   JOIN response_planning_jobs ON response_planning_jobs.id = response_plans.planning_job_id
   WHERE response_planning_jobs.message_id IN (
     SELECT id FROM messages WHERE message_type IN ('photo','voice','audio')));
DELETE FROM response_plans
 WHERE planning_job_id IN (
   SELECT id FROM response_planning_jobs
   WHERE message_id IN (SELECT id FROM messages WHERE message_type IN ('photo','voice','audio')));
DELETE FROM model_generation_attempts
 WHERE planning_job_id IN (
   SELECT id FROM response_planning_jobs
   WHERE message_id IN (SELECT id FROM messages WHERE message_type IN ('photo','voice','audio')));
DELETE FROM response_planning_jobs
 WHERE message_id IN (SELECT id FROM messages WHERE message_type IN ('photo','voice','audio'));
DELETE FROM conversation_processing_records
 WHERE message_id IN (SELECT id FROM messages WHERE message_type IN ('photo','voice','audio'));
DELETE FROM message_media
 WHERE message_id IN (SELECT id FROM messages WHERE message_type IN ('photo','voice','audio'));
DELETE FROM messages WHERE message_type IN ('photo','voice','audio');
DELETE FROM provider_price_revisions WHERE unit_basis = 'transcription_request';
DELETE FROM provider_usage_attempts
 WHERE workload_class = 'transcription' OR operation = 'media_transcription';
DELETE FROM provider_budgets WHERE workload_class = 'transcription';
DELETE FROM provider_work_policy_snapshots WHERE workload_class = 'transcription';
DELETE FROM provider_routing_policy_heads WHERE workload_class = 'transcription';
DELETE FROM provider_routing_policy_revisions WHERE workload_class = 'transcription';
DELETE FROM provider_capabilities WHERE workload_class = 'transcription';
SQL
  "$uv_bin" run alembic downgrade 0018_user_controlled_memory
fi
"$uv_bin" run alembic current | grep -q '0018_user_controlled_memory'
"$uv_bin" run alembic upgrade head
"$uv_bin" run alembic current | grep -q '0026_conversation_feedback'
"$uv_bin" run pytest backend/tests/test_memory.py backend/tests/test_conversation_context.py
"$uv_bin" run pytest -m memory_integration
