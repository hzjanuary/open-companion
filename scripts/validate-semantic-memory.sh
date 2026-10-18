#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$project_root/scripts/lib/resolve-uv.sh"
source "$project_root/scripts/lib/db-ready.sh"
uv_bin="$(resolve_uv "$project_root")"

export COMPOSE_PROJECT_NAME="${JANUARY_SEMANTIC_MEMORY_COMPOSE_PROJECT_NAME:-january-semantic-memory-validation}"

export JANUARY_DB_HOST_PORT="${JANUARY_DB_HOST_PORT:-5433}"
export JANUARY_REDIS_HOST_PORT="${JANUARY_REDIS_HOST_PORT:-6380}"
export JANUARY_QDRANT_HOST_PORT="${JANUARY_QDRANT_HOST_PORT:-6333}"
export JANUARY_DATABASE_PORT="$JANUARY_DB_HOST_PORT"
export JANUARY_REDIS_URL="redis://127.0.0.1:${JANUARY_REDIS_HOST_PORT}/0"
export JANUARY_QDRANT_URL="http://127.0.0.1:${JANUARY_QDRANT_HOST_PORT}"

cleanup() {
  status=$?
  trap - EXIT
  if ! docker compose down -v --remove-orphans >/dev/null 2>&1; then
    printf '%s\n' "Semantic-memory validator cleanup failed." >&2
    status=1
  fi
  exit "$status"
}
trap cleanup EXIT

start_fresh() {
  docker compose down -v --remove-orphans >/dev/null
  docker compose up -d database redis
}

start_fresh
docker compose up -d qdrant

pg_ready && redis_ready || { printf '%s\n' "PostgreSQL or Redis did not become ready." >&2; exit 1; }
for _ in $(seq 1 30); do
  if curl -fsS "$JANUARY_QDRANT_URL/healthz" >/dev/null; then
    break
  fi
  sleep 1
done
curl -fsS "$JANUARY_QDRANT_URL/healthz" >/dev/null || { printf '%s\n' "Qdrant did not become ready." >&2; exit 1; }

"$uv_bin" run alembic upgrade head
"$uv_bin" run pytest \
  backend/tests/test_semantic_memory.py \
  backend/tests/test_config.py \
  backend/tests/test_conversation_context.py -q
"$uv_bin" run pytest backend/tests/integration/test_memory_schema.py -m memory_integration -q

# The memory_integration suite inserts assistants with non-canonical slugs,
# which the SPEC-030 downgrade guard in 0021_multi_assistant_tenancy must
# refuse. Prove the populated state stays guarded before any reversal.
guard_log="$(mktemp "${TMPDIR:-/tmp}/spec030-semantic-memory-downgrade.XXXXXX")"
if "$uv_bin" run alembic downgrade 0012_conversation_summaries >"$guard_log" 2>&1; then
  printf '%s\n' "populated SPEC-030 semantic-memory downgrade unexpectedly succeeded" >&2
  exit 1
fi
grep -q 'SPEC-030 tenancy state blocks downgrade' "$guard_log"
rm -f "$guard_log"
guard_log=""
"$uv_bin" run alembic current | grep -q '0026_conversation_feedback'

# The historical semantic-memory reversal is an empty-schema proof. Chained
# validators leave canonical tenancy state that must remain guarded, so run it
# on a fresh validator-owned volume.
start_fresh
pg_ready || { printf '%s\n' "PostgreSQL did not become ready." >&2; exit 1; }
"$uv_bin" run alembic upgrade head
"$uv_bin" run alembic downgrade 0012_conversation_summaries
"$uv_bin" run alembic upgrade head
"$uv_bin" run alembic current | grep -q '0026_conversation_feedback'
printf '%s\n' "Semantic-memory validator: valid"
