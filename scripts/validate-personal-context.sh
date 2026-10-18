#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$project_root/scripts/lib/resolve-uv.sh"
source "$project_root/scripts/lib/db-ready.sh"
uv_bin="$(resolve_uv "$project_root")"

validation_mode="full"
if [[ $# -eq 1 && "$1" == "--repository-only" ]]; then
  validation_mode="repository-only"
elif [[ $# -ne 0 ]]; then
  printf '%s\n' "Usage: $0 [--repository-only]" >&2
  exit 2
fi

env -u JANUARY_ENVIRONMENT "$uv_bin" run pytest \
  backend/tests/test_personal_context.py \
  backend/tests/test_memory.py \
  backend/tests/test_conversation_context.py \
  backend/tests/test_response_plan.py \
  backend/tests/test_semantic_memory.py \
  backend/tests/test_provider_governance.py \
  backend/tests/test_telegram_commands.py \
  backend/tests/test_observability.py \
  backend/tests/test_config.py

if [[ "$validation_mode" == "repository-only" ]]; then
  printf '%s\n' "Repository tests passed; Docker integration/migration/runtime proof is PENDING (exit 2)." >&2
  exit 2
fi

export COMPOSE_PROJECT_NAME="${JANUARY_SPEC027_COMPOSE_PROJECT_NAME:-january-spec027-validation}"
export JANUARY_DB_HOST_PORT="${JANUARY_DB_HOST_PORT:-5438}"
export JANUARY_REDIS_HOST_PORT="${JANUARY_REDIS_HOST_PORT:-6385}"
export JANUARY_QDRANT_HOST_PORT="${JANUARY_QDRANT_HOST_PORT:-6336}"
export JANUARY_DATABASE_HOST=127.0.0.1
export JANUARY_DATABASE_PORT="$JANUARY_DB_HOST_PORT"
export JANUARY_REDIS_URL="redis://127.0.0.1:${JANUARY_REDIS_HOST_PORT}/0"
export JANUARY_QDRANT_URL="http://127.0.0.1:${JANUARY_QDRANT_HOST_PORT}"

if ! docker compose version >/dev/null 2>&1; then
  printf '%s\n' "Docker Compose is required for SPEC-027 integration proof." >&2
  exit 1
fi

guard_log=""
cleanup() {
  result=$?
  trap - EXIT
  if [ -n "$guard_log" ] && [ -f "$guard_log" ]; then
    rm -f "$guard_log"
  fi
  if ! docker compose down -v --remove-orphans; then
    printf '%s\n' "SPEC-027 temporary project cleanup failed." >&2
    result=1
  fi
  exit "$result"
}
trap cleanup EXIT

start_dependencies() {
  docker compose up --detach database redis qdrant
  pg_ready && redis_ready || { printf '%s\n' "PostgreSQL or Redis did not become ready." >&2; exit 1; }
  for _ in $(seq 1 30); do
    if curl -fsS "$JANUARY_QDRANT_URL/healthz" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  curl -fsS "$JANUARY_QDRANT_URL/healthz" >/dev/null 2>&1 || { printf '%s\n' "Qdrant did not become ready." >&2; exit 1; }
}

start_dependencies
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic downgrade base
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic upgrade 0017_provider_routing_cost_budgets
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic upgrade 0018_user_controlled_memory
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic downgrade 0017_provider_routing_cost_budgets
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic upgrade 0018_user_controlled_memory
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic current \
  | grep -q '0018_user_controlled_memory'

JANUARY_ENVIRONMENT=test "$uv_bin" run alembic upgrade head
JANUARY_ENVIRONMENT=test "$uv_bin" run pytest \
  backend/tests/integration/test_memory_schema.py \
  backend/tests/integration/test_governance_schema.py \
  backend/tests/integration/test_personal_context_schema.py \
  -m 'memory_integration or governance_integration'
PYTHONPATH=backend JANUARY_ENVIRONMENT=test "$uv_bin" run python - <<'PY'
import asyncio
from uuid import uuid4

from app.application.semantic_memory import EmbeddingVector, SemanticMemoryPoint
from app.core.config import Settings
from app.domain.persistence import MemoryScope
from app.infrastructure.semantic_memory import QdrantSemanticMemoryIndex

async def prove_qdrant_runtime():
    index = QdrantSemanticMemoryIndex(Settings().qdrant_url)
    collection = "spec027_validation_" + uuid4().hex
    point = SemanticMemoryPoint(
        uuid4(), uuid4(), uuid4(), uuid4(), MemoryScope.PRIVATE_CONVERSATION, "synthetic-v1"
    )
    vector = EmbeddingVector.validated((0.1, 0.2), 2)
    try:
        assert await index.health()
        await index.ensure_collection(collection, 2)
        await index.upsert(collection, point, vector)
        assert await index.count(collection) == 1
        scope = dict(
            assistant_id=point.assistant_id,
            platform_connection_id=point.platform_connection_id,
            conversation_id=point.conversation_id,
            scope=point.scope, embedding_version=point.embedding_version,
            limit=5, minimum_score=None,
        )
        matches = await index.query(collection, vector, **scope)
        assert [match.memory_id for match in matches] == [point.memory_id]
        assert await index.query(collection, vector, **{**scope, "conversation_id": uuid4()}) == ()
        await index.upsert(collection, point, EmbeddingVector.validated((0.2, 0.1), 2))
        assert await index.count(collection) == 1
        await index.delete(collection, point.memory_id)
        await index.delete(collection, point.memory_id)
        assert await index.count(collection) == 0
    finally:
        await index.aclose()

asyncio.run(prove_qdrant_runtime())
print("Synthetic Qdrant scoped upsert/query/update/delete proof: passed")
PY
PYTHONPATH=backend JANUARY_ENVIRONMENT=test \
  JANUARY_RETENTION_WORKER_ENABLED=true \
  "$uv_bin" run python -m app.runtime.retention_worker --once

# Isolate the SPEC-027 guard proof from governance tests that deliberately
# create non-legacy SPEC-030 tenants. Seed one exact personal-context scenario
# on a fresh project-owned volume, then require the historical guard verbatim.
docker compose down -v --remove-orphans
start_dependencies
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic upgrade head
JANUARY_ENVIRONMENT=test "$uv_bin" run pytest \
  backend/tests/integration/test_personal_context_schema.py::test_personal_context_replay_race_ownership_recall_and_prompt_scope \
  -m memory_integration
docker compose exec -T database psql -v ON_ERROR_STOP=1 -U january -d january <<'SQL'
UPDATE control_tenants SET revision = 1;
UPDATE assistants
   SET revision = 1,
       slug = 'assistant-' || replace(id::text, '-', '')
 WHERE tenant_id = '00000000-0000-4000-8000-000000000030'::uuid
   AND status <> 'retired';
UPDATE platform_connections SET revision = 1 WHERE status <> 'retired';
SQL
guard_log="$(mktemp "${TMPDIR:-/tmp}/spec027-downgrade-guard.XXXXXX")"
if JANUARY_ENVIRONMENT=test "$uv_bin" run alembic downgrade 0017_provider_routing_cost_budgets >"$guard_log" 2>&1; then
  printf '%s\n' "Downgrade unexpectedly accepted active SPEC-027 state." >&2
  exit 1
fi
grep -q 'SPEC-027 state exists; destructive downgrade is refused' "$guard_log"
rm -f "$guard_log"
guard_log=""
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic current \
  | grep -q '0026_conversation_feedback'

docker compose down -v --remove-orphans
start_dependencies
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic upgrade head
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic downgrade base
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic upgrade head
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic current \
  | grep -q '0026_conversation_feedback'
